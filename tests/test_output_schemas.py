"""Output schemas: the bundled validator's output keywords and the packaged command schemas."""
import unittest

from agent_contribute import core


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
        self.assertEqual(core.schema_errors({'a': 1}, schema), ['$: matches no allowed shape'])
        self.assertEqual(core.schema_errors({'a': 'x', 'b': 1}, schema), ['$: matches no allowed shape'])

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

    def test_existing_single_type_messages_are_unchanged(self):
        self.assertEqual(core.schema_errors([], {'type': 'object'}), ['$: expected object'])
        self.assertEqual(core.schema_errors(1, {'type': 'unknown'}), ['$: expected unknown'])
        self.assertEqual(core.schema_errors(True, {'type': 'integer'}), ['$: expected integer'])


if __name__ == '__main__':
    unittest.main()
