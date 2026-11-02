"""Check every command result the suite produces against its packaged output schema.

install() runs once from tests/__init__.py. It wraps the CLI's print() of the
JSON result, its text renderer and the library functions whose results the CLI prints, so any test
that produces output is checked without opting in."""
import builtins
import contextlib
import functools
import json

from agent_contribute import (audit, budget, ci, cli, core, drift, feedback, multi, outputs, ownership, signals, signatures,
                              textfmt, workspace)


class OutputSchemaViolation(BaseException):
    """BaseException, so neither production handlers nor broad test assertions swallow it."""


_state = {'args': None, 'unchecked': 0}
checked = []  # (schema name, definition or None), for coverage assertions


def check(value, name, definition=None):
    try:
        schema = outputs.output_schema(name)
        target = {'$ref': '#/$defs/' + definition} if definition else schema
        errors = core.schema_errors(value, target, root=schema)
    except Exception as exc:  # A broken schema must not look like a handled production error.
        raise OutputSchemaViolation(f'{name} output schema could not be applied: {exc!r}') from exc
    checked.append((name, definition))
    if errors:
        where = name + (f' $defs.{definition}' if definition else '')
        raise OutputSchemaViolation(f'{where} output schema: {errors[:10]}')


@contextlib.contextmanager
def unchecked():
    """Skip CLI output checks for transport/presentation tests whose patched results are deliberately partial fakes."""
    _state['unchecked'] += 1
    try:
        yield
    finally:
        _state['unchecked'] -= 1


def check_cli_result(result):
    args = _state['args']
    if _state['unchecked']:
        return None
    if isinstance(result, dict) and set(result) == {'error'} or args is None:
        return check(result, 'error')
    if args.command == 'schema':
        if result != outputs.output_schema(args.name):
            raise OutputSchemaViolation('schema command printed something other than the packaged schema')
        return checked.append(('schema', None))
    check(result, 'evidence-init' if args.command == 'evidence' else args.command)


def _wrap(module, name, schema, definition=None):
    original = getattr(module, name)

    @functools.wraps(original)
    def wrapper(*args, **kwargs):
        result = original(*args, **kwargs)
        check(result, schema, definition)
        return result
    setattr(module, name, wrapper)


def _print(*args, **kwargs):
    """The CLI's only print() call emits the result; JSON is checked as the exact text printed."""
    namespace = _state['args']
    if args and (namespace is None or namespace.format == 'json'):
        check_cli_result(json.loads(args[0]))
    return builtins.print(*args, **kwargs)


class _Text:
    def __getattr__(self, name):
        return getattr(textfmt, name)

    @staticmethod
    def render(command, result, **kwargs):
        check_cli_result(result)
        return textfmt.render(command, result, **kwargs)


def install():
    parse_args, main = cli.Parser.parse_args, cli.main

    def recording_parse_args(self, *args, **kwargs):
        _state['args'] = parse_args(self, *args, **kwargs)
        return _state['args']

    @functools.wraps(main)
    def recording_main(*args, **kwargs):
        _state['args'] = None
        return main(*args, **kwargs)
    cli.Parser.parse_args, cli.main = recording_parse_args, recording_main
    cli.print, cli.textfmt = _print, _Text()
    for module, name, schema, definition in [
            (core, 'discover', 'discover', None), (multi, 'discover_many', 'discover', None),
            (core, 'inspect_issue', 'inspect', None), (core, 'verify', 'verify', None),
            (drift, 'drift', 'drift', None), (feedback, 'feedback', 'feedback', None),
            (audit, 'audit', 'audit', None), (ownership, 'ownership', 'ownership', None),
            (workspace, 'scope_check', 'scope-check', None),
            (ownership, 'ownership_signals', 'inspect', 'ownership_signals'),
            (signals, 'issue_signals', 'discover', 'issue_signals'),
            (signals, 'responsiveness', 'discover', 'responsiveness'),
            (ci, 'observe', 'verify', 'ci_observation'), (signatures, 'observe', 'verify', 'signature_observation'),
            (budget, 'report', 'discover', 'api_budget')]:
        _wrap(module, name, schema, definition)
