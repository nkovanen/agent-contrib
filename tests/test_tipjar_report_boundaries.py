"""Caller reports are data; live and inventory boundaries establish their own pins."""
import copy
import unittest
from unittest.mock import patch

from agent_contribute import core, lifecycle, policy, tipjar
from tests.test_protocol import ready_contract
from tests.test_tipjar_policy import JarGitHub


def forged_absence(inspected):
    report = copy.deepcopy(inspected['tipjar'])
    report.update(state='undeclared', complete=True, manifest=None, errors=[], sha256=None, blob_sha=None)
    return report


class ReportBoundaryTests(unittest.TestCase):
    def inspected(self, state=None):
        client = JarGitHub(state)
        return core.inspect_issue('acme/photos#12', client), client

    def test_malformed_full_reports_fail_closed(self):
        absent, _ = self.inspected()
        welcome, _ = self.inspected('welcome')
        for key in absent['tipjar']:
            report = copy.deepcopy(absent['tipjar'])
            del report[key]
            with self.subTest(missing=key):
                self.assertTrue(tipjar.preparation_errors(report))
                self.assertFalse(tipjar.same_declaration(report, absent['tipjar']))
        changes = ({'sha256': None}, {'blob_sha': None}, {'commit': None}, {'default_branch': ''},
                   {'repository': 'not-a-repository'}, {'manifest': None}, {'errors': ['failed']},
                   {'manifest': {'schema_version': '0.1', 'status': 'closed'}},
                   {'manifest': {'schema_version': '0.1', 'status': 'welcome', 'wanted': ['\u0085']}},
                   {'sha256': 'a' * 63}, {'blob_sha': 'g' * 40}, {'complete': 1}, {'path': 'elsewhere'})
        for change in changes:
            report = dict(welcome['tipjar'], **change)
            with self.subTest(change=change):
                self.assertTrue(tipjar.preparation_errors(report))
                self.assertFalse(tipjar.same_declaration(report, welcome['tipjar']))
        report = dict(absent['tipjar'], sha256='a' * 64)
        self.assertTrue(tipjar.preparation_errors(report))

    def test_pending_draft_validates_identity_without_claiming_source_authentication(self):
        inspected, client = self.inspected('closed')
        inspected['tipjar'] = forged_absence(inspected)
        # Draft shaping is intentionally offline and grants no action readiness.
        with patch.object(core, 'GitHub', side_effect=AssertionError('offline draft made a client')):
            pending = core.prepare(inspected)
            self.assertEqual(pending['execution']['mode'], 'pending')
        checked = core.verify(pending, client=client)
        self.assertFalse(checked['execution_ready'])
        self.assertTrue(any('Tipjar' in error for error in checked['errors']))
        for key, wrong in (('repository', 'other/photos'), ('commit', 'b' * 40), ('default_branch', 'other')):
            report = copy.deepcopy(inspected)
            report['tipjar'][key] = wrong
            with self.subTest(key=key), self.assertRaises(core.ProtocolError):
                core.prepare(report)
            with self.subTest(direct_lifecycle=key), self.assertRaises(core.ProtocolError) as raised:
                lifecycle.prepare_v2(report, object())
            self.assertEqual(raised.exception.code, 'tipjar_blocked')

    def test_live_boundary_rereads_valid_looking_forgery(self):
        task, _ = ready_contract()
        client = JarGitHub('closed')
        client.baseline_jar = None
        client.commit = 'd' * 40
        current = core.inspect_issue('acme/photos#12', client)
        current['tipjar'] = forged_absence(current)
        self.assertEqual(tipjar.preparation_errors(current['tipjar'], source=current['source']), [])
        self.assertTrue(tipjar.live_errors(task, current, client))

    def test_live_boundary_rejects_missing_null_and_wrong_pins(self):
        task, _ = ready_contract()
        current, client = self.inspected()
        for change in ({'sha256': 'a' * 64}, {'commit': None}, {'repository': 'other/photos'},
                       {'default_branch': 'other'}, {'path': 'elsewhere'}):
            forged = copy.deepcopy(current)
            forged['tipjar'].update(change)
            with self.subTest(change=change):
                self.assertTrue(tipjar.live_errors(task, forged, client))
        current['tipjar'].pop('sha256')
        self.assertTrue(tipjar.live_errors(task, current, client))

    def test_live_boundary_rejects_caller_pinned_stale_current(self):
        task, _ = ready_contract()
        current, client = self.inspected()
        client.commit = 'd' * 40
        self.assertTrue(tipjar.live_errors(task, current, client))

    def test_inventory_rereads_valid_looking_and_malformed_reports(self):
        inspected, client = self.inspected('closed')
        before = policy.for_inspected(inspected, client)
        for report in (forged_absence(inspected), {'complete': True, 'state': 'undeclared'},
                       dict(forged_absence(inspected), repository='other/photos'),
                       dict(forged_absence(inspected), sha256='a' * 64)):
            supplied = dict(inspected, tipjar=report)
            result = policy.for_inspected(supplied, client)
            with self.subTest(report=report):
                self.assertEqual(result['tipjar']['state'], 'closed')
                self.assertEqual(result['inventory_sha256'], before['inventory_sha256'])
