"""Receipts are strict observations; editable snapshots cannot inflate impact."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import cli, core


class ReceiptGitHub:
    def __init__(self):
        self.calls = []
        self.repository = {'id': 101, 'full_name': 'acme/photos', 'private': False, 'visibility': 'public'}
        self.pr = {'id': 700, 'number': 30, 'html_url': 'https://github.com/acme/photos/pull/30',
                   'state': 'open', 'draft': True, 'merged': False, 'merged_at': None,
                   'closed_at': None, 'merge_commit_sha': None, 'merged_by': None,
                   'user': {'id': 7, 'login': 'builder', 'type': 'User'},
                   'head': {'sha': 'a' * 40, 'ref': 'agent/work'},
                   'base': {'sha': 'b' * 40, 'ref': 'main', 'repo': copy.deepcopy(self.repository)}}

    def request(self, endpoint):
        self.calls.append(endpoint)
        return copy.deepcopy({'repos/acme/photos': self.repository,
                              'repos/acme/photos/pulls/30': self.pr}[endpoint])


def invoke(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main(list(args))
    return code, json.loads(out.getvalue())


class ReceiptTests(unittest.TestCase):
    def test_capture_observes_fixed_endpoints_and_never_overwrites(self):
        client = ReceiptGitHub()
        with tempfile.TemporaryDirectory() as directory, patch.object(core, 'GitHub', return_value=client):
            path = Path(directory) / 'receipt.json'
            code, result = invoke('receipt', 'acme/photos#30', '--output', str(path))
            self.assertEqual(code, 0, result)
            receipt = json.loads(path.read_text())
            self.assertEqual(receipt['repository'], {'id': 101, 'full_name': 'acme/photos'})
            self.assertEqual((receipt['pull_request']['id'], receipt['pull_request']['state']), (700, 'draft'))
            self.assertEqual(receipt['pull_request']['head'], {'sha': 'a' * 40, 'ref': 'agent/work'})
            self.assertEqual(client.calls, ['repos/acme/photos', 'repos/acme/photos/pulls/30'])
            old = path.read_bytes()
            code, result = invoke('receipt', 'acme/photos#30', '--output', str(path))
            self.assertEqual(code, 1)
            self.assertEqual(path.read_bytes(), old)

    def test_private_or_incomplete_or_mismatching_metadata_never_creates_receipt(self):
        cases = [('repo', 'private', True), ('repo', 'visibility', 'private'),
                 ('repo', 'id', True), ('repo', 'full_name', 'other/photos'),
                 ('pr', 'merged', None), ('pr', 'user', None), ('pr', 'id', 0),
                 ('pr', 'number', 31), ('pr', 'draft', 1),
                 ('pr', 'html_url', 'https://gıthub.com/acme/photos/pull/30'),
                 ('pr', 'html_url', 'https://github.com/acme/photos/pull/30\u202e'),
                 ('pr', 'merged_at', '2026-11-03T00:00:00Z'),
                 ('pr', 'closed_at', '2026-11-03T00:00:00Z')]
        for target, key, value in cases:
            with self.subTest(target=target, key=key, value=value), tempfile.TemporaryDirectory() as directory:
                client = ReceiptGitHub()
                (client.repository if target == 'repo' else client.pr)[key] = value
                path = Path(directory) / 'new.json'
                with patch.object(core, 'GitHub', return_value=client):
                    code, result = invoke('receipt', 'acme/photos#30', '--output', str(path))
                self.assertEqual(code, 1, result)
                self.assertFalse(path.exists())

    def test_inconsistent_base_privacy_and_merged_draft_fail_closed(self):
        for change in ('base_private', 'merged_draft'):
            client = ReceiptGitHub()
            if change == 'base_private':
                client.pr['base']['repo']['private'] = True
            else:
                client.pr.update(state='closed', merged=True, closed_at='2026-11-01T00:00:00Z',
                                 merged_at='2026-11-01T00:00:00Z', merge_commit_sha='c' * 40,
                                 merged_by={'id': 8, 'login': 'maintainer', 'type': 'User'})
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'new.json'
                with patch.object(core, 'GitHub', return_value=client):
                    code, result = invoke('receipt', 'acme/photos#30', '--output', str(path))
                self.assertEqual(code, 1, result)
                self.assertFalse(path.exists())

    def test_second_response_requires_explicit_public_visibility_before_save(self):
        for visibility in ('private', 'internal', None, 'missing'):
            client = ReceiptGitHub()
            base_repo = client.pr['base']['repo']
            if visibility == 'missing':
                del base_repo['visibility']
            else:
                base_repo['visibility'] = visibility
            with self.subTest(visibility=visibility), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'new.json'
                with patch.object(core, 'GitHub', return_value=client):
                    code, result = invoke('receipt', 'acme/photos#30', '--output', str(path))
                self.assertEqual(code, 1, result)
                self.assertIn('error', result)
                self.assertFalse(path.exists())

    def test_api_failure_and_missing_head_base_never_write(self):
        for change in ('api_error', 'head', 'base_sha', 'base_id', 'missing_merged_at'):
            client = ReceiptGitHub()
            if change == 'api_error':
                def fail(endpoint):
                    raise core.ProtocolError('api_error', 'GitHub read failed')
                client.request = fail
            elif change == 'head':
                client.pr['head'] = None
            elif change == 'base_sha':
                del client.pr['base']['sha']
            elif change == 'base_id':
                client.pr['base']['repo']['id'] = 102
            else:
                del client.pr['merged_at']
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'new.json'
                with patch.object(core, 'GitHub', return_value=client):
                    code, result = invoke('receipt', 'acme/photos#30', '--output', str(path))
                self.assertEqual(code, 1, result)
                self.assertFalse(path.exists())

    def test_invalid_reference_fails_before_github(self):
        with patch.object(core, 'GitHub', side_effect=AssertionError('must stay offline')):
            self.assertEqual(invoke('receipt', 'acme/photos#３０', '--output', 'unused')[0], 1)


class ImpactTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def snapshot(self, filename='one.json', *, state='draft', observed='2026-11-02T12:00:00Z'):
        from agent_contribute import receipts
        client = ReceiptGitHub()
        if state in ('closed', 'merged'):
            client.pr.update(state='closed', draft=False, closed_at='2026-11-01T11:00:00Z')
        if state == 'merged':
            client.pr.update(merged=True, merged_at='2026-11-01T11:00:00Z', merge_commit_sha='c' * 40,
                             merged_by={'id': 8, 'login': 'maintainer', 'type': 'User'})
        receipt = receipts.observe('acme/photos#30', client)
        receipt['observed_at'] = observed
        path = self.root / filename
        path.write_text(json.dumps(receipt))
        return path, receipt

    def save(self, name, receipt):
        path = self.root / name
        path.write_text(json.dumps(receipt))
        return path

    def test_latest_snapshot_wins_without_inflation_or_argument_order_dependence(self):
        old, _ = self.snapshot()
        new, _ = self.snapshot('new.json', state='merged', observed='2026-11-03T10:00:00Z')
        for paths in ((old, new, old), (new, old, old)):
            with patch.object(core, 'GitHub', side_effect=AssertionError('offline')):
                code, result = invoke('impact', *map(str, paths))
            self.assertEqual(code, 0, result)
            self.assertEqual(result['unique_prs'], 1)
            self.assertEqual(result['repositories_represented'], 1)
            self.assertEqual(result['counts'], {'open': 0, 'closed': 0, 'merged': 1})
            self.assertEqual(result['receipts'][0]['pull_request']['state'], 'merged')
            self.assertEqual(result['trust'], 'self-reported recorded observations')

    def test_conflicting_older_snapshots_reject_even_when_newest_is_read_first(self):
        old, receipt = self.snapshot()
        new, _ = self.snapshot('new.json', state='merged', observed='2026-11-03T10:00:00Z')
        receipt['pull_request'].update(draft=False, state='open')
        conflict = self.save('conflict.json', receipt)
        for paths in ((new, old, conflict), (old, conflict, new), (conflict, new, old)):
            with self.subTest(paths=paths):
                self.assertEqual(invoke('impact', *map(str, paths))[0], 1)

    def test_counts_unique_repositories_and_includes_drafts_in_open(self):
        one, receipt = self.snapshot()
        two = copy.deepcopy(receipt)
        two['pull_request'].update(id=701, number=31, url='https://github.com/acme/photos/pull/31')
        two['provenance']['endpoints'][1] = 'repos/acme/photos/pulls/31'
        path2 = self.save('two.json', two)
        third_path, third = self.snapshot('third.json', state='closed')
        third['repository'] = {'id': 102, 'full_name': 'acme/other'}
        third['pull_request'].update(id=702, url='https://github.com/acme/other/pull/30')
        third['provenance']['endpoints'] = ['repos/acme/other', 'repos/acme/other/pulls/30']
        third_path = self.save('third.json', third)
        code, result = invoke('impact', str(one), str(path2), str(third_path))
        self.assertEqual(code, 0, result)
        self.assertEqual((result['unique_prs'], result['repositories_represented']), (3, 2))
        self.assertEqual(result['counts'], {'open': 2, 'closed': 1, 'merged': 0})

    def test_closed_unmerged_observation_represents_repository_without_claiming_benefit(self):
        path, _ = self.snapshot(state='closed')
        code, result = invoke('impact', str(path))
        self.assertEqual(code, 0, result)
        self.assertEqual(result.get('repositories_represented'), 1)
        self.assertNotIn('repositories_helped', result)
        self.assertEqual(result['counts'], {'open': 0, 'closed': 1, 'merged': 0})
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli.main(['--format', 'text', 'impact', str(path)])
        self.assertEqual(code, 0)
        self.assertIn('repositories represented: 1', output.getvalue())
        self.assertNotIn('helped', output.getvalue())

    def test_numeric_identity_conflicts_and_equal_time_disagreement_reject_whole_summary(self):
        path, original = self.snapshot()
        for mutation in ('pr_id', 'number', 'repository_id', 'author_id', 'state'):
            receipt = copy.deepcopy(original)
            if mutation == 'pr_id':
                receipt['pull_request']['id'] = 999
            elif mutation == 'number':
                receipt['pull_request'].update(number=31, url='https://github.com/acme/photos/pull/31')
                receipt['provenance']['endpoints'][1] = 'repos/acme/photos/pulls/31'
            elif mutation == 'repository_id':
                receipt['repository']['id'] = 999
            elif mutation == 'author_id':
                receipt['pull_request']['author']['id'] = 999
            else:
                receipt['pull_request'].update(draft=False, state='open')
            other = self.save('conflict.json', receipt)
            with self.subTest(mutation=mutation):
                code, result = invoke('impact', str(path), str(other))
                self.assertEqual(code, 1, result)
                self.assertIn('error', result)
                self.assertNotIn('counts', result)

    def test_malformed_unknown_or_untrusted_fields_fail_closed(self):
        _, original = self.snapshot()
        for key, value in [('schema_version', '9.0'), ('unexpected', True),
                           ('observed_at', '2026-11-02T12:00:00'),
                           ('observed_at', '2026-02-30T00:00:00Z'),
                           ('observed_at', '２０２６-11-02T12:00:00Z'),
                           ('observed_at', '2026-11-02T12:00:00-00:00'),
                           ('observed_at', '9999-11-02T12:00:00Z'),
                           ('observed_at', '2026-11-02T12:00:00.1234567Z')]:
            receipt = copy.deepcopy(original)
            receipt[key] = value
            with self.subTest(key=key, value=value):
                self.assertEqual(invoke('impact', str(self.save('bad.json', receipt)))[0], 1)
        for value in ('https://gıthub.com/acme/photos/pull/30',
                      'https://github.com/acme/photos/pull/30#ok',
                      'https://github.com/acme/photos/pull/30\u202e'):
            receipt = copy.deepcopy(original)
            receipt['pull_request']['url'] = value
            self.assertEqual(invoke('impact', str(self.save('bad.json', receipt)))[0], 1)

    def test_bounded_regular_files_duplicate_keys_and_symlinks(self):
        path, receipt = self.snapshot()
        invalid = self.root / 'invalid.json'
        for contents in ('{"schema_version":"0.1","schema_version":"0.1"}', '[]',
                         '\ufeff' + json.dumps(receipt), '{', ' ' * (65536 + 1)):
            invalid.write_text(contents)
            self.assertEqual(invoke('impact', str(invalid))[0], 1)
        invalid.write_bytes(b'\xff')
        self.assertEqual(invoke('impact', str(invalid))[0], 1)
        link = self.root / 'link.json'
        link.symlink_to(path)
        self.assertEqual(invoke('impact', str(link))[0], 1)
        directory_link = self.root / 'linked-directory'
        directory_link.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(invoke('impact', str(directory_link / path.name))[0], 1)
        self.assertEqual(invoke('impact', str(directory_link / '..' / path.name))[0], 1)
        self.assertEqual(invoke('impact', str(self.root))[0], 1)
        self.assertEqual(invoke('impact', *([str(path)] * 101))[0], 1)
        if hasattr(os, 'mkfifo'):
            fifo = self.root / 'fifo'
            os.mkfifo(fifo)
            self.assertEqual(invoke('impact', str(fifo))[0], 1)

    def test_text_summary_shows_counts_and_snapshot_trust(self):
        path, _ = self.snapshot()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(['--format', 'text', 'impact', str(path)])
        self.assertEqual(code, 0)
        self.assertIn('Open: 1', out.getvalue())
        self.assertIn('self-reported recorded observations', out.getvalue())
        self.assertIn('not signed proof', out.getvalue())

    def test_offline_command_refuses_github_global_options(self):
        path, _ = self.snapshot()
        for option in ('--cache', '--report-budget'):
            with patch.object(core, 'GitHub', side_effect=AssertionError('offline')):
                self.assertEqual(invoke(option, 'impact', str(path))[0], 2)


if __name__ == '__main__':
    unittest.main()
