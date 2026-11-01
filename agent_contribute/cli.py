"""JSON command-line interface. Remote text never becomes executable argv."""
import argparse
import json
import hashlib
import importlib.resources
from pathlib import Path

from . import core, __version__


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
        if command == 'prepare':
            sub.add_argument('--output', required=True)
    commands.add_parser('instructions')
    sub = commands.add_parser('skill')
    sub.add_argument('--output', required=True)
    sub = commands.add_parser('verify')
    sub.add_argument('contract')
    sub.add_argument('--evidence')
    sub.add_argument('--repo-dir')
    try:
        args = parser.parse_args(argv)
        if args.command == 'instructions':
            result = {'cli_version': __version__, 'supported_schema_versions': [core.VERSION],
                      'workflow_markdown': importlib.resources.files('agent_contribute').joinpath('instructions.md').read_text('utf-8'),
                      'resources': {'task_schema': 'agent_contribute/task.schema.json',
                                    'evidence_schema': 'agent_contribute/evidence.schema.json'},
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
        elif args.command == 'discover':
            result = core.discover(args.reference)
            code = 0 if result['complete'] else 1
        elif args.command in ('inspect', 'prepare'):
            result = core.inspect_issue(args.reference)
            code = 0 if result['complete'] else 1
            if args.command == 'prepare' and 'source' in result:
                task = core.prepare(result)
                write_new_json(args.output, task)
                context = {k: result[k] for k in ('requested_repository', 'issue_source_repository',
                                                  'proposed_target_repository', 'resolution_provenance', 'reference')}
                result = {**context, 'output': str(args.output), 'complete': result['complete'], 'contract': task,
                          'warning': 'Draft saved; inspect and review before execution'}
        else:
            result = core.verify(core.read_json(args.contract),
                                 core.read_json(args.evidence) if args.evidence else None, args.repo_dir)
            code = 0 if result['upstream_submission_ready'] or result['fork_completion_ready'] else 1
    except core.ProtocolError as exc:
        result = {'error': {'code': exc.code, 'message': str(exc)}}
        code = 2 if exc.code == 'usage' else 1
    except (OSError, UnicodeError, ValueError, RecursionError):
        result = {'error': {'code': 'input_error', 'message': 'Input or output could not be processed'}}
        code = 1
    print(json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False))
    return code
