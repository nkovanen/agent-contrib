"""JSON command-line interface. Remote text never becomes executable argv."""
import argparse
import json
import hashlib
import importlib.resources
import os
import select
import sys
import time
from pathlib import Path

from . import aipolicy, audit, core, drift, feedback, ownership, prbody, workspace, __version__


HOST_INPUT_TIMEOUT = 5.0


def read_host_context_stdin():
    """Bounded explicit input. The transport never authenticates a human mandate."""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            raise OSError('An explicit piped host context is required')
        descriptor = sys.stdin.fileno()
        deadline = time.monotonic() + HOST_INPUT_TIMEOUT
        chunks, size = [], 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([descriptor], [], [], remaining)[0]:
                raise OSError('Host context input timed out')
            chunk = os.read(descriptor, min(65536, core.MAX_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > core.MAX_BYTES:
                raise OSError('Host context exceeds the input bound')
        return core.strict_json(b''.join(chunks).decode('utf-8'))
    except (OSError, ValueError, UnicodeError) as exc:
        raise core.ProtocolError('host_context_input',
                                 'Cannot read explicit bounded UTF-8 host context from stdin') from exc


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise core.ProtocolError('usage', message)


def write_new_json(path, value):
    """Exclusive creation avoids clobbering a hand-reviewed contract or symlink."""
    try:
        with Path(path).open('x', encoding='utf-8') as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write('\n')
    except OSError as exc:
        raise core.ProtocolError('file_error', 'Cannot create output; choose a new writable path') from exc


def main(argv=None):
    parser = Parser(prog='agent-contrib', description='Read-only GitHub agent contribution protocol (JSON output)')
    parser.add_argument('--version', action='version', version=__version__)
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('discover', 'inspect', 'prepare'):
        sub = commands.add_parser(command)
        sub.add_argument('reference')
        if command == 'discover':
            sub.add_argument('--signals', action='store_true')
        if command == 'inspect':
            sub.add_argument('--ownership', action='store_true')
            sub.add_argument('--ai-policy', action='store_true')
        if command == 'prepare':
            sub.add_argument('--output', required=True)
            sub.add_argument('--schema-version', choices=('0.1', '0.2'), default='0.1')
    commands.add_parser('instructions')
    sub = commands.add_parser('skill')
    sub.add_argument('--output', required=True)
    sub = commands.add_parser('verify')
    sub.add_argument('contract')
    sub.add_argument('--evidence')
    sub.add_argument('--repo-dir')
    sub.add_argument('--stage', choices=('implementation', 'draft', 'completion'))
    sub.add_argument('--host-context-stdin', action='store_true')
    sub = commands.add_parser('scope-check')
    sub.add_argument('contract')
    sub.add_argument('--repo-dir', required=True)
    sub.add_argument('--base')
    sub = commands.add_parser('evidence').add_subparsers(dest='evidence_command', required=True).add_parser('init')
    sub.add_argument('contract')
    sub.add_argument('--repo-dir', required=True)
    sub.add_argument('--base', required=True)
    sub.add_argument('--output', required=True)
    sub = commands.add_parser('audit')
    sub.add_argument('repository')
    sub.add_argument('--print-policy', action='store_true')
    sub = commands.add_parser('ownership')
    sub.add_argument('reference')
    sub = commands.add_parser('drift')
    sub.add_argument('contract')
    sub = commands.add_parser('feedback')
    sub.add_argument('reference')
    sub.add_argument('--expected-head')
    sub = commands.add_parser('pr-body')
    sub.add_argument('contract')
    sub.add_argument('--evidence')
    sub.add_argument('--repo-dir')
    sub.add_argument('--closes', action='store_true')
    sub.add_argument('--assistant')
    sub.add_argument('--output', required=True)
    try:
        args = parser.parse_args(argv)
        if args.command == 'instructions':
            result = {'cli_version': __version__, 'supported_schema_versions': list(core.SUPPORTED_SCHEMA_VERSIONS),
                      'supported_host_context_versions': ['0.1'],
                      'host_authorization': 'host-asserted; actual human event must be retained outside worker control',
                      'workflow_markdown': importlib.resources.files('agent_contribute').joinpath('instructions.md').read_text('utf-8'),
                      'resources': {'task_schema': 'agent_contribute/task.schema.json',
                                    'evidence_schema': 'agent_contribute/evidence.schema.json',
                                    'task_schema_0.2': 'agent_contribute/schemas/0.2/task.schema.json',
                                    'evidence_schema_0.2': 'agent_contribute/schemas/0.2/evidence.schema.json',
                                    'host_context_schema': 'agent_contribute/schemas/host-context/0.1.schema.json'},
                      'automatic_updates': False}
            code = 0
        elif args.command == 'skill':
            adapter = importlib.resources.files('agent_contribute').joinpath('adapters/agent-contribute/SKILL.md').read_text('utf-8')
            try:
                with Path(args.output).open('x', encoding='utf-8', newline='') as handle:
                    handle.write(adapter)
            except OSError as exc:
                raise core.ProtocolError('file_error', 'Cannot create adapter; choose a new writable path') from exc
            result = {'output': str(args.output), 'cli_version': __version__,
                      'sha256': hashlib.sha256(adapter.encode()).hexdigest()}
            code = 0
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
            evidence = core.read_json(args.evidence) if args.evidence else None
            body, verification = prbody.pr_body(core.read_json(args.contract), evidence, args.repo_dir,
                                                closes=args.closes, assistant=args.assistant)
            try:
                with Path(args.output).open('x', encoding='utf-8', newline='') as handle:
                    handle.write(body)
            except OSError as exc:
                raise core.ProtocolError('file_error', 'Cannot create PR body; choose a new writable path') from exc
            result = {'output': str(args.output), 'sha256': hashlib.sha256(body.encode()).hexdigest(),
                      'contract_sha256': verification.get('contract_sha256'),
                      'warning': 'Rendered text only; it grants no publication authority and the CLI never writes to GitHub'}
            code = 0
        elif args.command == 'audit':
            result = audit.audit(args.repository, print_policy=args.print_policy)
            code = 0 if result['complete'] else 1
        elif args.command == 'inspect' and (args.ownership or args.ai_policy):
            client = core.GitHub()
            result = core.inspect_issue(args.reference, client)
            code = 0 if result['complete'] and 'source' in result else 1
            if 'source' in result and args.ownership:
                result['ownership_signals'] = ownership.ownership_signals(
                    result['issue_source_repository'], result['source']['issue'], client)
                code = code or (0 if result['ownership_signals']['complete'] else 1)
            if 'source' in result and args.ai_policy:
                result['ai_policy'] = aipolicy.ai_policy_excerpts(result)
        elif args.command == 'ownership':
            result = ownership.ownership(args.reference)
            code = 0 if result['complete'] else 1
        elif args.command == 'drift':
            result = drift.drift(core.read_json(args.contract))
            code = 0 if result['complete'] and result['drifted'] is False else 1
        elif args.command == 'feedback':
            result = feedback.feedback(args.reference, expected_head=args.expected_head)
            code = 0 if result['complete'] else 1
        elif args.command == 'discover':
            result = core.discover(args.reference, signals=True) if args.signals else core.discover(args.reference)
            code = 0 if result['complete'] else 1
        elif args.command in ('inspect', 'prepare'):
            result = core.inspect_issue(args.reference)
            code = 0 if result['complete'] else 1
            if args.command == 'prepare' and 'source' in result:
                task = core.prepare(result) if args.schema_version == '0.1' else core.prepare(result, schema_version=args.schema_version)
                write_new_json(args.output, task)
                context = {k: result[k] for k in ('requested_repository', 'issue_source_repository',
                                                  'proposed_target_repository', 'resolution_provenance', 'reference')}
                result = {**context, 'output': str(args.output), 'complete': result['complete'], 'contract': task,
                          'warning': 'Draft saved; inspect and review before execution'}
        else:
            task = core.read_json(args.contract)
            version = task.get('schema_version') if isinstance(task, dict) else None
            if version != '0.2' and (args.stage is not None or args.host_context_stdin):
                raise core.ProtocolError('schema_options', 'Lifecycle options require an explicit schema 0.2 task')
            evidence = core.read_json(args.evidence) if args.evidence else None
            if version == '0.2':
                context = read_host_context_stdin() if args.host_context_stdin else None
                result = core.verify(task, evidence, args.repo_dir, host_context=context)
                stage = args.stage or 'completion'
                ready = {'implementation': result.get('implementation_ready') is True,
                         'draft': (result.get('draft_create_ready') is True or
                                   result.get('publication', {}).get('verified') is True),
                         'completion': result.get('completion_ready') is True}
                code = 0 if result.get('schema_valid') is True and ready[stage] else 1
            else:
                result = core.verify(task, evidence, args.repo_dir)
                code = 0 if result['upstream_submission_ready'] or result['fork_completion_ready'] else 1
    except core.ProtocolError as exc:
        result = {'error': {'code': exc.code, 'message': str(exc)}}
        code = 2 if exc.code == 'usage' else 1
    except (OSError, UnicodeError, ValueError, RecursionError):
        result = {'error': {'code': 'input_error', 'message': 'Input or output could not be processed'}}
        code = 1
    print(json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False))
    return code
