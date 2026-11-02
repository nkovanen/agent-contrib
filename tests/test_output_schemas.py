"""Output schemas: the bundled validator's output keywords and the packaged command schemas."""
import argparse
import contextlib
import io
import copy
import importlib.util
import json
import pathlib
import unittest
from unittest.mock import patch

from agent_contribute import cli, core, outputs, ownership
from tests import output_contract
from tests.test_cli_help import built_parser
from tests.test_discover_golden import GOLDEN
from tests.test_protocol import FakeGitHub


def obj(properties, required=(), **extra):
    return {'type': 'object', 'properties': properties, 'required': list(required), **extra}


class ValidatorKeywordTests(unittest.TestCase):
    def test_nullable_and_number_types(self):
        schema = {'type': ['number', 'null']}
        for value in (1, 1.5, None):
            self.assertEqual(core.schema_errors(value, schema), [])
        for value in (True, '1', [], {}):
            self.assertEqual(core.schema_errors(value, schema), ['$: expected number or null'])
        self.assertEqual(core.schema_errors(None, {'type': 'null'}), [])
        self.assertEqual(core.schema_errors(0, {'type': 'null'}), ['$: expected null'])
        self.assertEqual(core.schema_errors(0.5, {'type': 'integer'}), ['$: expected integer'])
        self.assertEqual(core.schema_errors(-0.5, {'type': 'number', 'minimum': 0}), ['$: below minimum'])

    def test_list_type_applies_the_matched_type_keywords(self):
        schema = {'type': ['string', 'null'], 'pattern': '[a-z]+'}
        self.assertEqual(core.schema_errors('abc', schema), [])
        self.assertEqual(core.schema_errors('ABC', schema), ['$: invalid format'])
        self.assertEqual(core.schema_errors(None, schema), [])
        nested = {'type': ['object', 'null'], 'properties': {'a': {'type': 'integer'}}, 'required': ['a']}
        self.assertEqual(core.schema_errors({}, nested), ['$.a: missing'])
        self.assertEqual(core.schema_errors({'a': 1, 'b': 2}, nested), ['$: unknown properties'])

    def test_any_of_needs_one_matching_option(self):
        schema = {'anyOf': [obj({'a': {'type': 'string'}}, ['a']), obj({'b': {'type': 'integer'}}, ['b'])]}
        self.assertEqual(core.schema_errors({'a': 'x'}, schema), [])
        self.assertEqual(core.schema_errors({'b': 1}, schema), [])
        self.assertEqual(core.schema_errors({'a': 1}, schema),
                         ['$: matches no allowed shape', '$.a: expected string'])
        self.assertEqual(core.schema_errors({'a': 'x', 'b': 1}, schema),
                         ['$: matches no allowed shape', '$: unknown properties'])
        self.assertEqual(core.schema_errors({'b': 'x'}, schema), ['$: matches no allowed shape', '$.b: expected integer'])

    def test_local_references_resolve_against_the_root(self):
        schema = {'$defs': {'item': obj({'n': {'type': 'integer'}}, ['n'])},
                  'type': 'array', 'items': {'$ref': '#/$defs/item'}}
        self.assertEqual(core.schema_errors([{'n': 1}], schema), [])
        self.assertEqual(core.schema_errors([{'n': 'x'}], schema), ['$[0].n: expected integer'])
        loop = {'$defs': {'loop': {'$ref': '#/$defs/loop'}}, '$ref': '#/$defs/loop'}
        self.assertEqual(core.schema_errors(1, loop), ['$: excessive nesting'])
        for ref in ('other.json#/$defs/item', '#/properties/item', '#/$defs/missing'):
            with self.assertRaises((KeyError, ValueError)):
                core.schema_errors(1, {'$defs': {'item': {}}, '$ref': ref})

    def test_additional_properties_schema_and_true(self):
        mapping = obj({}, additionalProperties={'type': 'integer'})
        self.assertEqual(core.schema_errors({'x': 1, 'y': 2}, mapping), [])
        self.assertEqual(core.schema_errors({'x': 'no'}, mapping), ['$.x: expected integer'])
        known = obj({'a': {'type': 'string'}}, ['a'], additionalProperties={'type': 'integer'})
        self.assertEqual(core.schema_errors({'a': 1}, known), ['$.a: expected string'])
        self.assertEqual(core.schema_errors({'a': 'x', 'b': {}}, obj({'a': {}}, additionalProperties=True)), [])
        closed = obj({'a': {}}, additionalProperties=False)
        self.assertEqual(core.schema_errors({'a': 1, 'b': 2}, closed), ['$: unknown properties'])
        self.assertEqual(core.schema_errors({'a': 1, 'b': 2}, obj({'a': {}})), ['$: unknown properties'])

    def test_every_item_of_an_allowed_list_is_checked(self):
        schema = {'type': 'array', 'items': {'type': 'integer'}, 'maxItems': 2000}
        self.assertEqual(core.schema_errors([1] * 1001, schema), [])
        self.assertEqual(core.schema_errors([1] * 1000 + ['x'], schema), ['$[1000]: expected integer'])
        self.assertEqual(core.schema_errors([1] * 1999 + ['x'], schema), ['$[1999]: expected integer'])
        default = {'type': 'array', 'items': {'type': 'integer'}}
        self.assertEqual(core.schema_errors([1] * 1000, default), [])
        self.assertEqual(core.schema_errors([1] * 1001, default), ['$: invalid list length'])
        # An over-long list fails on its length; item checks stay bounded to the first 1000 as before.
        errors = core.schema_errors(['x'] * 5000, schema)
        self.assertEqual(errors[0], '$: invalid list length')
        self.assertEqual(len(errors), 1001)

    def test_numbers_must_be_finite(self):
        for value in (float('nan'), float('inf'), float('-inf')):
            self.assertEqual(core.schema_errors(value, {'type': ['number', 'null']}), ['$: expected number or null'])

    def test_existing_single_type_messages_are_unchanged(self):
        self.assertEqual(core.schema_errors([], {'type': 'object'}), ['$: expected object'])
        self.assertEqual(core.schema_errors(1, {'type': 'unknown'}), ['$: expected unknown'])
        self.assertEqual(core.schema_errors(True, {'type': 'integer'}), ['$: expected integer'])


def invoke(*argv):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = cli.main(list(argv))
    return code, json.loads(output.getvalue())


class SchemaCommandTests(unittest.TestCase):
    def test_schema_command_prints_each_packaged_schema(self):
        for name in outputs.SCHEMAS:
            with self.subTest(name=name):
                self.assertEqual(invoke('schema', name), (0, outputs.output_schema(name)))

    def test_unknown_schema_is_a_usage_error(self):
        code, result = invoke('schema', 'nope')
        self.assertEqual((code, result['error']['code']), (2, 'usage'))
        with self.assertRaises(core.ProtocolError):
            outputs.output_schema('../task')
        code, result = invoke('--report-budget', 'schema', 'verify')
        self.assertEqual((code, result['error']['code']), (2, 'usage'))

    def test_instructions_name_the_output_schemas(self):
        code, result = invoke('instructions')
        self.assertEqual(code, 0)
        self.assertEqual(result['output_schema_version'], outputs.VERSION)
        self.assertEqual(result['resources']['output_schemas'], 'agent_contribute/schemas/output/1')
        self.assertIn('agent-contrib schema', result['workflow_markdown'])

    def test_every_command_has_a_schema(self):
        commands = set()
        subparsers = next(a for a in built_parser()._actions if isinstance(a, argparse._SubParsersAction))
        for name, sub in subparsers.choices.items():
            nested = [a for a in sub._actions if isinstance(a, argparse._SubParsersAction)]
            commands.update([f'{name}-{child}' for a in nested for child in a.choices] or [name])
        self.assertEqual(commands - {'schema'}, set(outputs.SCHEMAS) - {'error'})


KEYWORDS = {'$schema', '$id', '$defs', '$ref', 'title', 'description', 'type', 'properties', 'required',
            'additionalProperties', 'items', 'anyOf', 'enum', 'const', 'pattern', 'minimum', 'minItems',
            'maxItems', 'minLength', 'maxLength'}


def subschemas(schema, path='$'):
    yield path, schema
    for key, value in schema.get('properties', {}).items():
        yield from subschemas(value, f'{path}.{key}')
    for key, value in schema.get('$defs', {}).items():
        yield from subschemas(value, f'{path}.$defs.{key}')
    for i, value in enumerate(schema.get('anyOf', [])):
        yield from subschemas(value, f'{path}.anyOf[{i}]')
    for key in ('items', 'additionalProperties'):
        if isinstance(schema.get(key), dict):
            yield from subschemas(schema[key], f'{path}.{key}')


class SchemaFileTests(unittest.TestCase):
    def test_schema_files_use_only_validated_keywords_and_explicit_objects(self):
        for name in outputs.SCHEMAS:
            schema = outputs.output_schema(name)
            self.assertEqual(schema['$id'], f'urn:agent-contrib:output:{outputs.VERSION}:{name}')
            self.assertEqual(schema['$schema'], 'https://json-schema.org/draft/2020-12/schema')
            for path, item in subschemas(schema):
                with self.subTest(name=name, path=path):
                    self.assertLessEqual(set(item) - KEYWORDS, set())
                    kinds = item.get('type') if isinstance(item.get('type'), list) else [item.get('type')]
                    if 'object' in kinds:
                        self.assertIn('additionalProperties', item)
                        self.assertLessEqual(set(item['required']), set(item['properties']))
                    if 'array' in kinds:
                        self.assertIn('items', item)
                    if '$ref' in item:
                        self.assertEqual(set(item) - {'description'}, {'$ref'})
                        self.assertIn(item['$ref'].removeprefix('#/$defs/'), schema['$defs'])

    def test_every_schema_file_is_packaged_and_install_checked(self):
        root = pathlib.Path(outputs.__file__).parent
        files = {path.name for path in (root / outputs.DIRECTORY).iterdir()}
        self.assertEqual(files, {name + '.schema.json' for name in outputs.SCHEMAS})
        self.assertIn(f'"{outputs.DIRECTORY}/*.schema.json"', (root.parent / 'pyproject.toml').read_text('utf-8'))
        install = (root.parent / 'tools' / 'check_install.py').read_text('utf-8')
        for name in outputs.SCHEMAS:
            self.assertIn(f'    "{outputs.DIRECTORY}/{name}.schema.json",\n', install)

    def test_skill_points_to_the_schema_command(self):
        skill = (pathlib.Path(outputs.__file__).parent / 'adapters' / 'agent-contribute' / 'SKILL.md').read_text('utf-8')
        self.assertIn('`agent-contrib schema COMMAND`', skill)

    def test_shared_definitions_are_identical_across_files(self):
        seen = {}
        for name in outputs.SCHEMAS:
            for key, value in outputs.output_schema(name).get('$defs', {}).items():
                first = seen.setdefault(key, (name, value))
                self.assertEqual(value, first[1], f'$defs.{key} differs between {first[0]} and {name}')


class ContractHookTests(unittest.TestCase):
    def golden(self, name):
        return json.loads((GOLDEN / (name + '.json')).read_text('utf-8'))['result']

    def test_frozen_discover_goldens_match_the_schema(self):
        for path in sorted(GOLDEN.glob('*.json')):
            with self.subTest(golden=path.name):
                output_contract.check(json.loads(path.read_text('utf-8'))['result'], 'discover')

    def test_renamed_or_removed_fields_fail_through_the_cli(self):
        result = self.golden('policy_overlap')
        renamed = copy.deepcopy(result)
        renamed['issues'][0]['overlaps'] = renamed['issues'][0].pop('duplicates')
        removed = copy.deepcopy(result)
        del removed['issues'][0]['approval']['matched_labels']
        retyped = copy.deepcopy(result)
        retyped['complete'] = 'true'
        for mutant in (renamed, removed, retyped):
            with self.subTest(mutant=mutant['issues'][0].keys() ^ result['issues'][0].keys() or mutant['complete']), \
                    patch.object(core, 'discover', return_value=mutant), self.assertRaises(output_contract.OutputSchemaViolation):
                invoke('discover', 'acme/photos')
        with patch.object(core, 'discover', return_value=result):
            self.assertEqual(invoke('discover', 'acme/photos')[1], result)

    def test_library_results_and_error_envelopes_are_checked(self):
        with self.assertRaises(output_contract.OutputSchemaViolation):
            output_contract.check({'error': {'code': 'usage'}}, 'error')
        with self.assertRaises(output_contract.OutputSchemaViolation):
            output_contract.check({'error': {'code': 'usage', 'message': 'x'}, 'extra': 1}, 'error')
        with self.assertRaises(output_contract.OutputSchemaViolation), \
                patch.object(ownership, 'ownership_signals', return_value={'complete': True}):
            ownership.ownership('acme/photos#12', FakeGitHub())

    def test_unresolved_variants_are_exercised(self):
        client = FakeGitHub()
        client.failed.add('repos/acme/photos')
        result = ownership.ownership('acme/photos#12', client)
        self.assertEqual(result['complete'], False)
        self.assertEqual(core.schema_errors(result, {'$ref': '#/$defs/issue_unresolved'}, root=outputs.output_schema('ownership')), [])
        result = core.verify({'schema_version': '0.2'})
        verify = outputs.output_schema('verify')
        self.assertEqual(core.schema_errors(result, {'$ref': '#/$defs/verify_0_2_rejected'}, root=verify), [])
        self.assertTrue(core.schema_errors(result, {'$ref': '#/$defs/verify_0_2'}, root=verify))


def reference_tool():
    path = pathlib.Path(__file__).resolve().parents[1] / 'tools' / 'output_reference.py'
    spec = importlib.util.spec_from_file_location('output_reference', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DocsReferenceTests(unittest.TestCase):
    def test_cli_docs_reference_matches_the_schemas(self):
        tool = reference_tool()
        self.assertEqual(tool.current()[1], tool.render(),
                         'docs/cli.md output reference is stale; run python tools/output_reference.py --write')
        self.assertEqual(tool.main([]), 0)

    def test_reference_changes_when_a_field_is_renamed(self):
        tool = reference_tool()
        original = outputs.output_schema

        def renamed(name):
            schema = original(name)
            if name == 'inspect':
                fields = schema['$defs']['inspect_result']['properties']
                fields['issue'] = fields.pop('untrusted_issue')
            return schema
        with patch.object(outputs, 'output_schema', renamed):
            self.assertNotEqual(tool.current()[1], tool.render())
            self.assertEqual(tool.main([]), 1)


if __name__ == '__main__':
    unittest.main()
