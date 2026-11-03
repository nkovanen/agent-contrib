"""Packaged JSON Schemas (draft 2020-12 subset) for each command's JSON output.

Every object states additionalProperties, so standard validators and the bundled
validator agree. A shape change bumps VERSION; output values never carry it."""
import importlib.resources
import json

from . import core

VERSION = '2'
SCHEMAS = ('audit', 'authorization-request', 'discover', 'drift', 'error', 'evidence-init', 'feedback', 'inspect', 'instructions', 'jar',
           'lint', 'ownership', 'pr-body', 'prepare', 'scope-check', 'skill', 'verify')
DIRECTORY = f'schemas/output/{VERSION}'


def output_schema(name):
    if name not in SCHEMAS:
        raise core.ProtocolError('unsupported_schema', 'Unsupported output schema')
    path = f'{DIRECTORY}/{name}.schema.json'
    return json.loads(importlib.resources.files('agent_contribute').joinpath(path).read_text('utf-8'))
