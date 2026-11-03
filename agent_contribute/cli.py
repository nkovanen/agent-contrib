"""JSON command-line interface. Remote text never becomes executable argv."""
import argparse
import json
import hashlib
import importlib.resources
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from . import (audit, authrequest, budget, cache, ci, core, drift, feedback, multi, outputs, ownership, policy,
               prbody, remote, signals, signatures, textfmt, tipjar, workspace, __version__)


HOST_INPUT_TIMEOUT = 5.0


def read_host_context_stdin():
    """Bounded explicit input. The transport never authenticates a human mandate."""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            raise OSError('An explicit piped host context is required')
        descriptor = sys.stdin.fileno()
        deadline = time.monotonic() + HOST_INPUT_TIMEOUT
        # An isolated fixed reader can be killed and reaped; a blocked thread cannot.
        reader_code = ('import sys; '
                       f'data = sys.stdin.buffer.read({core.MAX_BYTES + 1}); '
                       'sys.stdout.buffer.write(data)')
        with subprocess.Popen([sys.executable, '-I', '-S', '-c', reader_code],
                              stdin=descriptor, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, close_fds=True) as reader:
            try:
                data, _ = reader.communicate(timeout=max(0, deadline - time.monotonic()))
            except BaseException:
                reader.kill()
                reader.communicate()
                raise
            if reader.returncode:
                raise OSError('Host context reader failed')
        if len(data) > core.MAX_BYTES:
            raise OSError('Host context exceeds the input bound')
        return core.strict_json(data.decode('utf-8'))
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError) as exc:
        raise core.ProtocolError('host_context_input',
                                 'Cannot read explicit bounded UTF-8 host context from stdin') from exc


GLOBAL_OPTIONS = ('--format', '--report-budget', '--min-remaining', '--cache')
# Commands that never read GitHub; GitHub-only global options are refused on them alike.
OFFLINE_COMMANDS = ('instructions', 'schema', 'skill', 'lint', 'scope-check', 'evidence')
AI_POLICY_NOTICE = ('agent-contrib: --ai-policy is deprecated and ignored; '
                    'inspect always adds repository_policy')


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # Global options are parsed only before the subcommand; say so instead of a bare rejection.
        if message.startswith('unrecognized arguments: ') and any(
                token.split('=', 1)[0] in GLOBAL_OPTIONS for token in message.split()[2:]):
            message += ('; global options --format, --report-budget, --min-remaining and --cache go before the subcommand, '
                        'for example: agent-contrib --format text verify task.json')
        raise core.ProtocolError('usage', message)


def notice():
    """Best effort: a missing or closed stderr never changes stdout or the exit status. Not print(): the result
    is the CLI's only print() call."""
    stream = sys.stderr
    try:
        stream.write(AI_POLICY_NOTICE + '\n')
        stream.flush()
    except (AttributeError, OSError, ValueError):
        # As for a broken stdout: close the failed stream so interpreter shutdown cannot retry its buffered write
        # and exit 120. Closing a closed stream is a no-op; a failed final flush still closes it.
        try:
            close = getattr(stream, 'close', None)
            if close is not None:
                close()
        except (OSError, ValueError):
            pass


def create_new(path, text, what, newline=''):
    """Exclusive creation avoids clobbering a hand-reviewed file or symlink."""
    try:
        with Path(path).open('x', encoding='utf-8', newline=newline) as handle:
            handle.write(text)
    except OSError as exc:
        raise core.ProtocolError('file_error', f'Cannot create {what}; choose a new writable path') from exc


def write_new_json(path, value):
    create_new(path, json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n', 'output', newline=None)


def discover_names(args):
    names = args.reference + (multi.read_repositories_file(args.repositories_file) if args.repositories_file else [])
    if not names:
        raise core.ProtocolError('usage', 'the following arguments are required: reference (or a non-empty --repositories-file)')
    return names


def prevalidate(args):
    """The single local argument check, run before any GitHub read (including the optional rate_limit read)."""
    if args.command == 'discover':
        args.limit = core.validate_discovery_limit(args.limit)
        args.names = discover_names(args)
        if args.check_top is not None and (not args.signals or not 1 <= args.check_top <= signals.CHECK_TOP_MAX or
                                           len(args.names) != 1):
            raise core.ProtocolError('usage', f'--check-top needs --signals, one repository and N from 1 to '
                                     f'{signals.CHECK_TOP_MAX}')
        if args.repo_dir is not None and len(args.names) != 1:
            raise core.ProtocolError('usage', '--repo-dir with discover supports one repository')
        core.parse_repository(args.names[0]) if len(args.names) == 1 else multi.validate(args.names)
    elif args.command in ('inspect', 'prepare', 'ownership', 'feedback'):
        core.parse_issue(args.reference)
        if args.command == 'feedback' and args.expected_head is not None and not remote.SHA.fullmatch(args.expected_head):
            raise core.ProtocolError('invalid_head', 'Expected head must be a full 40-character commit SHA')
    elif args.command == 'jar':
        try:
            core.parse_repository(args.repository)
        except core.ProtocolError as exc:
            raise core.ProtocolError('usage', str(exc)) from None
    elif args.command == 'audit':
        core.parse_repository(args.repository)
    elif args.command == 'authorization-request':
        args.task = core.read_json(args.contract)  # read once; dispatch builds from this object
        authrequest.check_contract(args.task)
    elif args.command in ('verify', 'drift', 'pr-body'):
        # Each file is read once; dispatch uses these objects, so a file changed later cannot change the route.
        args.evidence_data = None
        if args.command == 'pr-body' and args.evidence:
            args.evidence_data = core.read_json(args.evidence)
        if args.command == 'drift' and args.policy_sha256 is not None and not re.fullmatch('[0-9a-f]{64}', args.policy_sha256):
            raise core.ProtocolError('usage', '--policy-sha256 must be a lowercase 64-character SHA-256 hex digest')
        task = args.task = core.read_json(args.contract)
        if args.command in ('drift', 'pr-body') and core.validate_contract(task):
            raise core.ProtocolError('invalid_contract', 'Contract does not match its bundled schema')
        if args.command == 'verify':
            version = task.get('schema_version') if isinstance(task, dict) else None
            if version != '0.2' and (args.stage is not None or args.host_context_stdin):
                raise core.ProtocolError('schema_options', 'Lifecycle options require an explicit schema 0.2 task')
            if args.evidence:
                args.evidence_data = core.read_json(args.evidence)


def main(argv=None):
    parser = Parser(prog='agent-contrib',
                    description='Read-only GitHub agent contribution protocol. Output is JSON unless --format text.',
                    epilog='Exit status: 0 when the command succeeds and its gate passes; 1 when a gate is not passed, '
                           'a read is incomplete or an error occurs; 2 for usage errors. '
                           'agent-contrib schema COMMAND prints the JSON Schema of that command\'s output.')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--format', choices=('json', 'text'), default='json',
                        help='Output format (default json; text is an abridged summary). Give it before the subcommand')
    parser.add_argument('--report-budget', action='store_true',
                        help='Add GitHub rate-limit snapshots around a GitHub-reading command')
    parser.add_argument('--min-remaining', type=int, metavar='N',
                        help='With --report-budget, refuse to start below N remaining core requests')
    parser.add_argument('--cache', action='store_true',
                        help='Reuse verified file contents at pinned commits of public repositories from the user cache '
                             '(blob-SHA checked); every other read stays live and output is unchanged')
    commands = parser.add_subparsers(dest='command', required=True, metavar='COMMAND')
    summaries = {'discover': 'Rank open issues of one repository, or 2-20, with policy and overlap context',
                 'inspect': 'Inspect one issue: approval, instructions, exclusions and overlapping PRs',
                 'prepare': 'Write a draft task contract for one issue; it grants no authorization'}
    for command in ('discover', 'inspect', 'prepare'):
        sub = commands.add_parser(command, help=summaries[command])
        if command == 'discover':
            sub.add_argument('reference', nargs='*', help='owner/repo; give 2-20 for a multi-repository run')
            sub.add_argument('--limit', metavar='N',
                             help='Display at most N ranked candidates (1-1000, globally across repositories); '
                                  'all scans still run')
            sub.add_argument('--welcomed-only', action='store_true',
                             help='Select only declared welcomes among named repositories; all scans still run')
            sub.add_argument('--signals', action='store_true',
                             help='Add report-only code-location, clarity, activity and maintainer signals')
            sub.add_argument('--responsiveness', action='store_true',
                             help='Add a report-only repository responsiveness report from one read of recently closed PRs')
            sub.add_argument('--check-top', type=int, metavar='N',
                             help='With --signals and one repository: read ownership signals (one timeline and comment '
                                  'page, at most 4 PR details) for the top N (1-5) and re-rank only those N; report only')
            sub.add_argument('--repositories-file', help='File with one owner/repo per line; # comments are ignored')
            sub.add_argument('--repo-dir', metavar='CHECKOUT',
                             help='One repository only: report issues referenced by local commits not in the source '
                                  'default branch (with --signals they rank below other candidates); report only')
        else:
            sub.add_argument('reference', help="Issue reference such as 'owner/repo#123'")
        if command == 'inspect':
            sub.add_argument('--ownership', action='store_true', help='Add report-only ownership and resolution signals')
            sub.add_argument('--ai-policy', action='store_true',
                             help='Deprecated and ignored (one notice on stderr); inspect always adds '
                                  'repository_policy')
        if command == 'prepare':
            sub.add_argument('--output', required=True, help='New file for the draft contract; never overwritten')
            sub.add_argument('--schema-version', choices=('0.1', '0.2'), default='0.1',
                             help='Task schema (default 0.1; 0.2 is the same-repository candidate route)')
    sub = commands.add_parser('jar', help='Inspect the pinned root Tipjar invitation; inspection only, grants no authority',
                              description='Pinned root invitation inspection only; grants no approval or authority.')
    sub.add_argument('repository', help='GitHub owner/repo to inspect directly, without parent tracker resolution')
    commands.add_parser('instructions', help='Print the installed workflow, CLI version and supported schemas')
    sub = commands.add_parser('schema', help="Print the JSON Schema of a command's JSON output")
    sub.add_argument('name', choices=outputs.SCHEMAS, metavar='COMMAND',
                     help="Command whose output schema to print; 'error' is the error envelope, "
                          "'evidence-init' is evidence init. Choices: " + ', '.join(outputs.SCHEMAS))
    sub = commands.add_parser('skill', help='Export the canonical agent Skill')
    sub.add_argument('--output', required=True, help='New file for SKILL.md; never overwritten')
    sub = commands.add_parser('verify', help='Check a contract and optional evidence against live GitHub state; '
                                             'never runs validation argv')
    sub.add_argument('contract', help='Task contract JSON file')
    sub.add_argument('--evidence', help='Evidence JSON file for this contract')
    sub.add_argument('--repo-dir', help='Local checkout the evidence describes')
    sub.add_argument('--stage', choices=('implementation', 'draft', 'completion'),
                     help='Schema 0.2: stage whose gate sets the exit status (default completion)')
    sub.add_argument('--host-context-stdin', action='store_true',
                     help='Schema 0.2: read a host-issued record as JSON on stdin (8 MiB, 5 s timeout); '
                          'not proof of human consent')
    sub.add_argument('--observe-ci', action='store_true',
                     help='Add report-only CI results for the evidence head; exit status unchanged')
    sub.add_argument('--observe-signatures', action='store_true',
                     help='Add report-only commit-signature observations for the evidence range; never verifies '
                          'locally or changes the exit status')
    sub = commands.add_parser('authorization-request',
                              help='Schema 0.2: print an unsigned mandate request pre-filled from the contract; grants nothing')
    sub.add_argument('contract', help='Task contract JSON file')
    sub = commands.add_parser('lint', help='Offline check of a contract against its schema and the reviewed-contract '
                                           'rules; no GitHub or Git reads')
    sub.add_argument('contract', help='Task contract JSON file')
    sub = commands.add_parser('scope-check', help='Offline check of local changes against the contract scope; never evidence')
    sub.add_argument('contract', help='Task contract JSON file')
    sub.add_argument('--repo-dir', required=True, help='Local checkout to check')
    sub.add_argument('--base', metavar='REV',
                     help='Full SHA, HEAD or refs/... name, optionally ~N/^N (default source.commit); '
                          'must be an ancestor of HEAD')
    sub = commands.add_parser('evidence', help='Evidence file helpers').add_subparsers(
        dest='evidence_command', required=True, metavar='COMMAND').add_parser(
        'init', help='Write an unfilled evidence skeleton from observed Git facts; runs nothing')
    sub.add_argument('contract', help='Task contract JSON file')
    sub.add_argument('--repo-dir', required=True, help='Local checkout the evidence will describe')
    sub.add_argument('--base', required=True, metavar='REV',
                     help='Full SHA, HEAD or refs/... name, optionally ~N/^N; must descend from source.commit '
                          'and be an ancestor of HEAD')
    sub.add_argument('--output', required=True, help='New evidence file outside the checkout; never overwritten')
    sub = commands.add_parser('audit', help='Read-only maintainer report: policy, labels, instructions, issue quality')
    sub.add_argument('repository', help='owner/repo')
    sub.add_argument('--print-policy', action='store_true', help='Include an example policy file; nothing is written')
    sub = commands.add_parser('ownership', help='Report-only ownership and resolution signals for one issue')
    sub.add_argument('reference', help="Issue reference such as 'owner/repo#123'")
    sub = commands.add_parser('drift', help='Report what changed since the contract was prepared; never rewrites it')
    sub.add_argument('contract', help='Task contract JSON file')
    sub.add_argument('--policy-sha256', metavar='HASH',
                     help='The reviewed repository_policy inventory_sha256 (from the ai-policy-review evidence); '
                          're-reads the policy inventory and reports repository_policy_drift')
    sub = commands.add_parser('feedback', help='Latest reviews, comments and checks for one pull request')
    sub.add_argument('reference', help="Pull request reference such as 'owner/repo#45'")
    sub.add_argument('--expected-head', metavar='SHA',
                     help='Full 40-character head SHA; reports head_moved if the PR head differs')
    sub = commands.add_parser('pr-body', help='Render a Markdown PR description; grants no publication authority')
    sub.add_argument('contract', help='Task contract JSON file')
    sub.add_argument('--evidence', help='Evidence JSON file for this contract')
    sub.add_argument('--repo-dir', help='Local checkout the evidence describes')
    sub.add_argument('--closes', action='store_true', help="Write 'Closes' instead of the default 'Refs' issue link")
    sub.add_argument('--assistant', help='Host-reported AI assistant name to disclose')
    sub.add_argument('--output', required=True, help='New file for the Markdown body; never overwritten')
    args = None
    stage_gate = None
    try:
        args = parser.parse_args(argv)
        if args.min_remaining is not None and (not args.report_budget or args.min_remaining < 0):
            raise core.ProtocolError('usage', '--min-remaining requires --report-budget and a non-negative count')
        if args.command in OFFLINE_COMMANDS:
            for flag, given in (('--report-budget', args.report_budget), ('--cache', args.cache)):
                if given:
                    raise core.ProtocolError('usage', flag + ' applies only to commands that read GitHub')
        cache.configure(args.cache and args.command != 'jar')
        if getattr(args, 'ai_policy', False):
            notice()
        prevalidate(args)
        if args.report_budget:
            before = budget.snapshot()
            if args.min_remaining is not None:
                budget.require_remaining(before, args.min_remaining)
        if args.command == 'instructions':
            result = {'cli_version': __version__, 'supported_schema_versions': list(core.SUPPORTED_SCHEMA_VERSIONS),
                      'supported_host_context_versions': list(core.HOST_CONTEXT_VERSIONS),
                      'host_authorization': ('host-asserted; actual human event must be retained outside worker control; '
                                             'host-context 0.2 overlap dispositions waive only bound topical overlaps'),
                      'workflow_markdown': importlib.resources.files('agent_contribute').joinpath('instructions.md').read_text('utf-8'),
                      'resources': {'task_schema': 'agent_contribute/task.schema.json',
                                    'evidence_schema': 'agent_contribute/evidence.schema.json',
                                    'task_schema_0.2': 'agent_contribute/schemas/0.2/task.schema.json',
                                    'evidence_schema_0.2': 'agent_contribute/schemas/0.2/evidence.schema.json',
                                    'host_context_schema': 'agent_contribute/schemas/host-context/0.1.schema.json',
                                    'host_context_schema_0.2': 'agent_contribute/schemas/host-context/0.2.schema.json',
                                    'output_schemas': 'agent_contribute/' + outputs.DIRECTORY},
                      'output_schema_version': outputs.VERSION,
                      'automatic_updates': False}
            code = 0
        elif args.command == 'schema':
            result = outputs.output_schema(args.name)
            code = 0
        elif args.command == 'skill':
            adapter = importlib.resources.files('agent_contribute').joinpath('adapters/agent-contribute/SKILL.md').read_text('utf-8')
            create_new(args.output, adapter, 'adapter')
            result = {'output': str(args.output), 'cli_version': __version__,
                      'sha256': hashlib.sha256(adapter.encode()).hexdigest()}
            code = 0
        elif args.command == 'lint':
            result = core.lint(core.read_json(args.contract))
            code = 0 if result['reviewed'] else 1
        elif args.command == 'scope-check':
            result = workspace.scope_check(core.read_json(args.contract), args.repo_dir, args.base)
            code = 0 if result['within_scope'] else 1
        elif args.command == 'evidence':
            task = core.read_json(args.contract)
            skeleton = workspace.evidence_skeleton(task, args.repo_dir, args.base)
            workspace.require_outside_checkout(args.repo_dir, args.output)
            write_new_json(args.output, skeleton)
            result = {'output': str(args.output), 'evidence_valid': False,
                      'schema_errors': len(core.schema_errors(skeleton, core.bundled_schema('evidence', task['schema_version']))),
                      'warning': 'Skeleton only: fill every result from real runs and reviews; nothing was executed'}
            code = 0
        elif args.command == 'pr-body':
            body, verification = prbody.pr_body(args.task, args.evidence_data, args.repo_dir,
                                                closes=args.closes, assistant=args.assistant)
            create_new(args.output, body, 'PR body')
            result = {'output': str(args.output), 'sha256': hashlib.sha256(body.encode()).hexdigest(),
                      'contract_sha256': verification.get('contract_sha256'),
                      'warning': 'Rendered text only; it grants no publication authority and the CLI never writes to GitHub'}
            code = 0
        elif args.command == 'authorization-request':
            result = authrequest.build(args.task)
            code = 0 if result.get('ready_for_issuance') is True else 1
        elif args.command == 'jar':
            result = tipjar.read_jar(args.repository)
            code = 0 if result['complete'] else 1
        elif args.command == 'audit':
            result = audit.audit(args.repository, print_policy=args.print_policy)
            code = 0 if result['complete'] else 1
        elif args.command == 'ownership':
            result = ownership.ownership(args.reference)
            code = 0 if result['complete'] else 1
        elif args.command == 'drift':
            result = drift.drift(args.task, policy_sha256=args.policy_sha256)
            code = 0 if result['complete'] and result['drifted'] is False else 1
        elif args.command == 'feedback':
            result = feedback.feedback(args.reference, expected_head=args.expected_head)
            code = 0 if result['complete'] else 1
        elif args.command == 'discover':
            options = {key: True for key in ('signals', 'responsiveness') if getattr(args, key)}
            if args.welcomed_only:
                options['welcomed_only'] = True
            names, client = args.names, core.GitHub()
            if args.limit is not None:
                options['limit'] = args.limit
            if args.check_top is not None:
                options['check_top'] = args.check_top
            if args.repo_dir is not None:
                options['repo_dir'] = args.repo_dir
            result = (core.discover(names[0], client, **options) if len(names) == 1 else
                      multi.discover_many(names, client, **options))
            code = 0 if result['complete'] else 1
            # An incomplete opted-in report is a nonzero exit, as for --responsiveness.
            if args.check_top is not None:
                code = code or (0 if result.get('top_check', {}).get('complete') else 1)
            if args.repo_dir is not None:
                code = code or (0 if result['local_work']['complete'] else 1)
            for single in result.get('repositories', [result]):
                if 'commit' in single:  # report only: never part of completeness or the exit code
                    single['repository_policy'] = policy.report(single['repository'], single['commit'],
                                                                single['instructions'], client, tipjar_report=single.get('tipjar'))
            if args.responsiveness:  # Like --ownership: an incomplete opted-in report is a nonzero exit.
                reports = [r.get('repository_signals', {}).get('responsiveness') for r in result.get('repositories', [result])]
                code = code or (0 if all(r and r['complete'] for r in reports) else 1)
        elif args.command in ('inspect', 'prepare'):
            client = core.GitHub()
            result = core.inspect_issue(args.reference, client)
            code = 0 if result['complete'] else 1
            # Default-on, report only: the policy report never changes the result, the contract or the exit code.
            report = policy.for_inspected(result, client) if 'source' in result else None
            if args.command == 'inspect' and 'source' in result:
                if args.ownership:
                    result['ownership_signals'] = ownership.ownership_signals(
                        result['issue_source_repository'], result['source']['issue'], client)
                    code = code or (0 if result['ownership_signals']['complete'] else 1)
                result['repository_policy'] = report
            if args.command == 'prepare' and 'source' in result:
                task = core.prepare(result) if args.schema_version == '0.1' else core.prepare(result, schema_version=args.schema_version)
                write_new_json(args.output, task)
                context = {k: result[k] for k in ('requested_repository', 'issue_source_repository',
                                                  'proposed_target_repository', 'resolution_provenance', 'reference')}
                result = {**context, 'output': str(args.output), 'complete': result['complete'], 'contract': task,
                          'warning': 'Draft saved; inspect and review before execution', 'repository_policy': report,
                          'tipjar': result['tipjar']}
        else:
            task, evidence = args.task, args.evidence_data
            version = task.get('schema_version') if isinstance(task, dict) else None
            if version == '0.2':
                context = read_host_context_stdin() if args.host_context_stdin else None
                result = core.verify(task, evidence, args.repo_dir, host_context=context)
                stage = args.stage or 'completion'
                ready = {'implementation': result.get('implementation_ready') is True,
                         'draft': (result.get('draft_create_ready') is True or
                                   result.get('publication', {}).get('verified') is True),
                         'completion': result.get('completion_ready') is True}
                code = 0 if result.get('schema_valid') is True and ready[stage] else 1
                if args.stage is not None:
                    stage_gate = (stage, code == 0)
            else:
                result = core.verify(task, evidence, args.repo_dir)
                code = 0 if result['upstream_submission_ready'] or result['fork_completion_ready'] else 1
            if args.observe_ci and result.get('schema_valid') is True:
                result['ci_observation'] = ci.observe(task, evidence)  # report only; code is already decided
            if args.observe_signatures and result.get('schema_valid') is True:
                result['signature_observation'] = signatures.observe(task, evidence, args.repo_dir)  # report only
        if args.report_budget:
            result['api_budget'] = budget.report(before)
    except core.ProtocolError as exc:
        result = getattr(exc, 'payload', None) or {'error': {'code': exc.code, 'message': str(exc)}}
        code = 2 if exc.code == 'usage' else 1
    except (OSError, UnicodeError, ValueError, RecursionError):
        result = {'error': {'code': 'input_error', 'message': 'Input or output could not be processed'}}
        code = 1
    finally:
        cache.configure(False)  # --cache lasts one invocation; library callers never inherit it
    stream = sys.stdout
    if stream is None:
        return 1
    try:
        output = (textfmt.render(args.command, result, stage=stage_gate) if args is not None and args.format == 'text'
                  else json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False) + '\n')
        print(output, end='', file=stream)
        flush = getattr(stream, 'flush', None)
        if flush is not None:
            flush()
    except BrokenPipeError:
        # Close the broken stream so interpreter shutdown cannot flush it again.
        try:
            close = getattr(stream, 'close', None)
            if close is not None:
                close()
        except BrokenPipeError:
            pass
        return 1
    return code
