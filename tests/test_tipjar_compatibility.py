"""Published schemas and historical inventory digests remain recognizable."""
import hashlib
import importlib.resources
import json
import pathlib
import unittest
from unittest.mock import patch

from agent_contribute import core, outputs, policy
from tests.test_tipjar_policy import JarGitHub


class TipjarCompatibilityTests(unittest.TestCase):
    def test_old_inventory_hash_does_not_attest_jar_review(self):
        from agent_contribute import drift
        from tests.test_policy_drift import VersionedGitHub, reviewed
        client = VersionedGitHub()
        with patch.object(policy, 'INVENTORY_FORMAT', 2):
            task, old = reviewed(client)
        result = drift.drift(task, client, policy_sha256=old)['repository_policy_drift']
        self.assertEqual((result['recorded_inventory_format'], result['current_inventory_format']), (2, 3))
        self.assertTrue(result['policy_drifted'])
        self.assertIn('Re-review', result['note'])

    def test_historical_digest_survives_reserved_jar_report_size(self):
        client = JarGitHub()
        before = core.inspect_issue('acme/photos#12', client)
        hashes = {}
        baseline = policy.report('acme/photos', before['source']['commit'], before['instructions'], client,
                                 tipjar_report=before['tipjar'], hashes=hashes)
        old_hash = hashes[2]
        client.jar = client.baseline_jar = json.dumps({'schema_version': '0.1', 'status': 'welcome',
            'wanted': [str(n) + 'x' * 490 for n in range(16)]}).encode()
        after = core.inspect_issue('acme/photos#12', client)
        with patch.object(policy, 'MAX_REPORT_BYTES', len(json.dumps(baseline, ensure_ascii=True).encode()) + 100):
            result = policy.report('acme/photos', after['source']['commit'], after['instructions'], client,
                                   tipjar_report=after['tipjar'], hashes=hashes)
        self.assertEqual(result['tipjar'], after['tipjar'])
        self.assertEqual(hashes[2], old_hash, 'jar output must not change historical prose-only hash computation')

    def test_welcomed_output_matches_published_task3_schema(self):
        from agent_contribute import multi
        from tests.test_tipjar_discovery import SourcesGitHub
        fixture = json.loads((pathlib.Path(__file__).parent / 'fixtures/tipjar-output-compatibility.json').read_text())
        resources = importlib.resources.files('agent_contribute')
        for name, digest in fixture['output1_sha256'].items():
            self.assertEqual(hashlib.sha256(resources.joinpath('schemas/output/1/' + name).read_bytes()).hexdigest(), digest)
        self.assertEqual(hashlib.sha256(resources.joinpath('schemas/output/2/discover.schema.json').read_bytes()).hexdigest(),
                         fixture['discover_output2_sha256'])
        schema = outputs.output_schema('discover')
        for found in (core.discover('acme/photos', SourcesGitHub({'acme/photos': 'welcome'}), welcomed_only=True),
                      multi.discover_many(['acme/photos', 'person/photos'], SourcesGitHub({}), welcomed_only=True)):
            self.assertEqual(core.schema_errors(found, schema), [])
