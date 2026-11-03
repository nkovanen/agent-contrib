"""Opt-in CI gate for schema 0.2 completion (#17): contract rules, raw reads, the decision table and wiring."""
import copy
import datetime as dt
import json
import os
import pathlib
import random
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import cigate, core, lifecycle
from tests.test_authorization import candidate_task, host_context
from tests.test_ci_gate_golden import DATES, GOLDEN, journey, rendered
from tests.test_lifecycle import NOW, absent_publication, own_publication, signoff
from tests.test_protocol import evidence_checkout, refresh_checkout_evidence

HEAD = 'a' * 40
APP, OTHER = 15368, 999


def suite(sid, app=APP, status='completed', head=HEAD):
    return {'id': sid, 'head_sha': head, 'app': {'id': app, 'slug': 'x'}, 'status': status, 'conclusion': None}


def run(rid, name='test', app=APP, status='completed', conclusion='success', suite_id=1, head=HEAD):
    return {'id': rid, 'name': name, 'head_sha': head, 'app': {'id': app, 'slug': 'x'}, 'status': status,
            'conclusion': conclusion, 'check_suite': {'id': suite_id}, 'html_url': f'https://github.com/a/b/runs/{rid}'}


class FakeCI:
    """check-suites and check-runs pages for one head; counts every request."""
    def __init__(self, suites, runs, suite_total=None, run_total=None):
        self.suites, self.runs, self.calls = suites, runs, []
        self.suite_total, self.run_total = suite_total, run_total

    def request(self, endpoint):
        self.calls.append(endpoint)
        page = int(endpoint.rsplit('page=', 1)[1])
        if '/check-suites' in endpoint:
            items, key, total = self.suites, 'check_suites', self.suite_total
        elif '/check-runs?filter=all&' in endpoint:
            items, key, total = self.runs, 'check_runs', self.run_total
        else:
            raise AssertionError(endpoint)
        return {'total_count': len(items) if total is None else total, key: items[(page - 1) * 100:page * 100]}


def gate(suites, runs, items=({'check': 'test', 'app_id': APP},), **totals):
    client = FakeCI(suites, runs, **totals)
    found, observed, errors, complete = cigate.observe(client, 'acme/photos', HEAD)
    return cigate.decide(list(items), found, observed, complete), errors, client


def state(suites, runs, **kwargs):
    return gate(suites, runs, **kwargs)[0][0]['state']


class ContractRuleTests(unittest.TestCase):
    def schema_errors(self, value):
        task, _ = candidate_task()
        task['ci_requirements'] = value
        return core.validate_contract(task)

    def test_schema_shape(self):
        self.assertEqual(self.schema_errors([]), [])
        self.assertEqual(self.schema_errors([{'check': 'test', 'app_id': APP}] * 20), [])
        for bad in ([{'check': 'test', 'app_id': APP}] * 21, [{'check': 'test'}], [{'app_id': APP}],
                    [{'check': '', 'app_id': APP}], [{'check': ' ', 'app_id': APP}], [{'check': 'x' * 201, 'app_id': APP}],
                    [{'check': 'test', 'app_id': 0}], [{'check': 'test', 'app_id': True}], [{'check': 'test', 'app_id': '1'}],
                    [{'check': 'test', 'app_id': 1.0}], [{'check': 'test', 'app_id': APP, 'slug': 'x'}], {'check': 'test'}):
            with self.subTest(bad=str(bad)[:60]):
                self.assertTrue(self.schema_errors(bad))

    def test_reviewed_contract_rules(self):
        task, _ = candidate_task()
        self.assertEqual(cigate.contract_errors(task), [])
        task['ci_requirements'] = []
        self.assertEqual(cigate.contract_errors(task), [])
        for items, error in (([{'check': 'test', 'app_id': APP}] * 2, 'CI requirements must be unique'),
                             ([{'check': 'te​st', 'app_id': APP}], 'control or format characters'),
                             ([{'check': 'te\x1bst', 'app_id': APP}], 'control or format characters')):
            with self.subTest(error=error):
                task['ci_requirements'] = items
                self.assertTrue(any(error in found for found in cigate.contract_errors(task)))
        task['ci_requirements'] = [{'check': 'test', 'app_id': APP}]
        task['execution']['requested_actions'] = ['implement']
        self.assertEqual(cigate.contract_errors(task), ['CI requirements need the create_draft action'])


class DecisionTests(unittest.TestCase):
    """One fixture per row of the design table, first applicable row winning."""
    def test_met_needs_every_run_and_every_app_suite_completed(self):
        self.assertEqual(state([suite(1)], [run(1)]), 'met')
        self.assertEqual(state([suite(1), suite(2)], [run(1), run(2, suite_id=2)]), 'met')

    def test_failed_for_every_failing_conclusion(self):
        for conclusion in sorted(cigate.FAILED):
            with self.subTest(conclusion=conclusion):
                self.assertEqual(state([suite(1)], [run(1, conclusion=conclusion)]), 'failed')

    def test_neutral_and_skipped_are_not_met(self):
        for conclusion in ('neutral', 'skipped'):
            self.assertEqual(state([suite(1)], [run(1), run(2, conclusion=conclusion)]), 'not_met')

    def test_unfinished_runs_and_approval_are_pending(self):
        for status in ('queued', 'in_progress', 'waiting', 'requested', 'pending'):
            with self.subTest(status=status):
                self.assertEqual(state([suite(1, status=status)], [run(1, status=status, conclusion=None)]), 'pending')
        self.assertEqual(state([suite(1)], [run(1, conclusion='action_required')]), 'pending')

    def test_rerequested_suite_with_an_old_success_is_pending(self):
        # CI-02: the rerequest queues the suite; the old run still reads completed/success.
        self.assertEqual(state([suite(1, status='queued')], [run(1)]), 'pending')

    def test_zero_run_suite_of_the_app_is_pending(self):
        self.assertEqual(state([suite(1), suite(2, status='queued')], [run(1)]), 'pending')
        self.assertEqual(state([suite(2, status='requested')], []), 'pending')

    def test_another_apps_unfinished_suite_does_not_block(self):
        self.assertEqual(state([suite(1), suite(2, app=OTHER, status='queued')], [run(1)]), 'met')

    def test_missing_without_a_matching_run(self):
        self.assertEqual(state([], []), 'missing')
        self.assertEqual(state([suite(1)], [run(1, name='lint')]), 'missing')

    def test_distinct_same_name_jobs_all_must_succeed(self):
        # CI-01: matrix legs or two workflows; neither ID order nor suite placement hides the failure.
        for runs in ([run(100, conclusion='failure'), run(101)], [run(100), run(101, conclusion='failure')],
                     [run(100, conclusion='failure', suite_id=2), run(101)]):
            with self.subTest(runs=[(r['id'], r['conclusion']) for r in runs]):
                self.assertEqual(state([suite(1), suite(2)], runs), 'failed')

    def test_a_genuine_retry_does_not_recover_while_the_failed_record_is_retained(self):
        self.assertEqual(state([suite(1)], [run(1, conclusion='failure'), run(2)]), 'failed')

    def test_a_deleted_failed_record_is_not_seen(self):
        # CI-05: the gate observes what GitHub currently retains; only the remaining success is read.
        self.assertEqual(state([suite(1)], [run(2)]), 'met')

    def test_same_name_runs_from_other_apps_are_counted_never_accepted(self):
        result, _, _ = gate([suite(1), suite(2, app=OTHER)], [run(1, app=OTHER, suite_id=2)])
        self.assertEqual((result[0]['state'], result[0]['other_app_runs']), ('missing', 1))
        result, _, _ = gate([suite(1), suite(2, app=OTHER)], [run(1), run(2, app=OTHER, conclusion='failure', suite_id=2)])
        self.assertEqual((result[0]['state'], result[0]['other_app_runs']), ('met', 1))

    def test_raw_names_are_compared_exactly(self):
        # CI-03: no sanitising or truncation before identity.
        for name in ('test​', 'te\x1bst', 'Test', ' test', 'test ', 'tеst', 'test\n'):
            with self.subTest(name=repr(name)):
                self.assertEqual(state([suite(1)], [run(1, name=name)]), 'missing')
        prefix = 'x' * 200
        self.assertEqual(state([suite(1)], [run(1, name=prefix + '-other')],
                               items=({'check': prefix, 'app_id': APP},)), 'missing')

    def test_result_does_not_depend_on_response_order(self):
        runs = [run(i, conclusion='success' if i % 3 else 'failure', suite_id=1 + i % 2) for i in range(1, 9)]
        expected = state([suite(1), suite(2)], runs)
        for seed in range(5):
            shuffled = list(runs)
            random.Random(seed).shuffle(shuffled)
            self.assertEqual(state([suite(2), suite(1)], shuffled), expected)

    def test_several_requirements_are_independent(self):
        result, _, _ = gate([suite(1), suite(2, app=OTHER)], [run(1), run(2, name='lint', app=OTHER, suite_id=2,
                                                                            conclusion='failure')],
                            items=({'check': 'test', 'app_id': APP}, {'check': 'lint', 'app_id': OTHER}))
        self.assertEqual([item['state'] for item in result], ['met', 'failed'])


class ReadTests(unittest.TestCase):
    def test_suite_window_is_unknown_after_one_request(self):
        # CI-04: the runs endpoint only covers a ref's newest 1,000 suites.
        result, errors, client = gate([suite(1)], [run(1)], suite_total=1000)
        self.assertEqual(result[0]['state'], 'unknown')
        self.assertEqual(len(client.calls), 1)
        self.assertIn('1000-suite window', errors[0])
        self.assertEqual(state([suite(1)], [run(1)], suite_total=1), 'met')

    def test_many_suites_and_runs_paginate_completely(self):
        suites = [suite(i) for i in range(1, 151)]
        runs = [run(i, suite_id=1 + i % 150) for i in range(1, 251)]
        result, errors, client = gate(suites, runs)
        self.assertEqual((result[0]['state'], errors, len(client.calls)), ('met', [], 5))
        self.assertTrue(all('per_page=100' in call for call in client.calls))
        self.assertTrue(all('check-runs?filter=all&per_page=100' in call for call in client.calls if 'check-runs' in call))

    def test_inconsistent_or_unreadable_reads_are_unknown(self):
        cases = {
            'run in an unread suite': ([suite(1)], [run(1, suite_id=7)], {}),
            'suite count moves': ([suite(1)], [run(1)], {'suite_total': 2}),
            'run count moves': ([suite(1)], [run(1)], {'run_total': 2}),
            'repeated run': ([suite(1)], [run(1), run(1)], {}),
            'suite for another head': ([suite(1, head='b' * 40)], [run(1)], {}),
            'run for another head': ([suite(1)], [run(1, head='b' * 40)], {}),
        }
        for name, (suites, runs, totals) in cases.items():
            with self.subTest(name=name):
                self.assertEqual(state(suites, runs, **totals), 'unknown')

    def test_malformed_app_and_state_fields_are_unknown(self):
        def broken(change, target='run'):
            suites, runs = [suite(1)], [run(1)]
            item = runs[0] if target == 'run' else suites[0]
            change(item)
            return state(suites, runs)
        changes = {
            'run app missing': lambda r: r.pop('app'), 'run app not an object': lambda r: r.update(app=15368),
            'run app id bool': lambda r: r['app'].update(id=True), 'run app id zero': lambda r: r['app'].update(id=0),
            'run app id string': lambda r: r['app'].update(id='15368'), 'run name missing': lambda r: r.pop('name'),
            'run name not a string': lambda r: r.update(name=['test']), 'run id bool': lambda r: r.update(id=True),
            'run status unknown': lambda r: r.update(status='done'), 'run status unhashable': lambda r: r.update(status=[]),
            'run conclusion unknown': lambda r: r.update(conclusion='passed'),
            'completed without conclusion': lambda r: r.update(conclusion=None),
            'queued with conclusion': lambda r: r.update(status='queued'),
            'run suite missing': lambda r: r.pop('check_suite'), 'run suite id zero': lambda r: r['check_suite'].update(id=0),
        }
        for name, change in changes.items():
            with self.subTest(name=name):
                self.assertEqual(broken(change), 'unknown')
        for name, change in {'suite app missing': lambda s: s.pop('app'), 'suite app id bool': lambda s: s['app'].update(id=False),
                             'suite status unknown': lambda s: s.update(status='done'),
                             'suite id negative': lambda s: s.update(id=-1)}.items():
            with self.subTest(name=name):
                self.assertEqual(broken(change, 'suite'), 'unknown')

    def test_exhausted_read_budget_is_unknown(self):
        suites = [suite(i) for i in range(1, 201)]
        runs = [run(i, suite_id=1 + i % 200) for i in range(1, 401)]
        with patch.object(cigate, 'READ_BUDGET', 4):
            result, errors, client = gate(suites, runs)
        self.assertEqual(result[0]['state'], 'unknown')
        self.assertEqual(len(client.calls), 4)
        self.assertTrue(any('budget' in error for error in errors), errors)
        self.assertEqual(state(suites, runs), 'met')  # the same data within the real budget
        self.assertEqual(cigate.READ_BUDGET, 50)

    def test_github_errors_are_unknown(self):
        class Failing(FakeCI):
            def request(self, endpoint):
                if '/check-runs' in endpoint:
                    raise core.ProtocolError('api_error', 'GitHub GET failed')
                return super().request(endpoint)
        found, runs, errors, complete = cigate.observe(Failing([suite(1)], [run(1)]), 'acme/photos', HEAD)
        self.assertFalse(complete)
        self.assertEqual(cigate.decide([{'check': 'test', 'app_id': APP}], found, runs, complete)[0]['state'], 'unknown')


def git(directory, *args):
    return subprocess.check_output(['git', '-C', directory, '-c', 'user.name=T', '-c', 'user.email=t@example.org', *args],
                                   text=True).strip()


class GithubRuleTests(unittest.TestCase):
    def test_additions_modifications_deletions_and_renames_are_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            git(tmp, 'init', '-q')
            for path in ('src/a.py', '.github/workflows/ci.yml'):
                pathlib.Path(tmp, path).parent.mkdir(parents=True, exist_ok=True)
                pathlib.Path(tmp, path).write_text('x')
            git(tmp, 'add', '.')
            git(tmp, 'commit', '-q', '-m', 'base')
            base = git(tmp, 'rev-parse', 'HEAD')

            def change(*argv, write=None):
                git(tmp, 'checkout', '-q', '--detach', base)
                if write:
                    pathlib.Path(tmp, write).parent.mkdir(parents=True, exist_ok=True)
                    pathlib.Path(tmp, write).write_text('y')
                    git(tmp, 'add', '-A')
                if argv:
                    git(tmp, *argv)
                git(tmp, 'commit', '-q', '--allow-empty', '-m', 'change')
                return cigate._edits_github(tmp, base, git(tmp, 'rev-parse', 'HEAD'))
            self.assertIs(change(write='src/b.py'), False)
            self.assertIs(change(write='.github/workflows/ci.yml'), True)
            self.assertIs(change(write='.github/new.yml'), True)
            self.assertIs(change('rm', '-q', '.github/workflows/ci.yml'), True)
            self.assertIs(change('mv', '.github/workflows/ci.yml', 'src/ci.yml'), True)
            self.assertIs(change(write='.GitHub/x.yml'), True)
            self.assertIsNone(cigate._edits_github(tmp, 'f' * 40, base))


class Clock(dt.datetime):
    offset = dt.timedelta()

    @classmethod
    def now(cls, tz=None):
        return (NOW + cls.offset).astimezone(tz)


def ci_journey(requirements, suites, runs, extra_commit=None, advance_on_runs=None, scope=None):
    """The candidate journey with ci_requirements and a check-suite/check-run fake; returns the final verify."""
    Clock.offset = dt.timedelta()
    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, DATES), patch.object(core.dt, 'datetime', Clock), \
            patch.object(lifecycle, 'check_publication', side_effect=absent_publication, create=True) as boundary:
        task, client = candidate_task()
        legacy, _, evidence, checkout = evidence_checkout(tmp)
        checkout('checkout', '-q', '-b', 'agent/bounds')
        if extra_commit:
            extra_commit(tmp, checkout)
            refresh_checkout_evidence(evidence, checkout)
        task['source']['commit'] = legacy['source']['commit']
        client.commit = legacy['source']['commit']
        if scope:
            task['scope'] = scope
        task['ci_requirements'] = requirements
        context = host_context(task)
        digest = core.canonical_hash(task)
        evidence.update(schema_version='0.2', contract_sha256=digest)
        del evidence['human_signoff']
        evidence['independent_review'].update(contract_sha256=digest, reviewed_at=(NOW - dt.timedelta(minutes=10)).isoformat())
        for validation in evidence['validations']:
            validation.update(started_at=(NOW - dt.timedelta(minutes=20)).isoformat(),
                              finished_at=(NOW - dt.timedelta(minutes=19)).isoformat())
        head = evidence['git_head']
        fake = FakeCI([dict(s, head_sha=head) for s in suites], [dict(r, head_sha=head) for r in runs])
        original = client.request

        def request(endpoint):
            if '/check-suites' in endpoint or '/check-runs' in endpoint:
                if advance_on_runs and '/check-runs' in endpoint:
                    Clock.offset = advance_on_runs
                return fake.request(endpoint)
            return original(endpoint)
        client.request = request
        before = core.verify(task, evidence, tmp, client, host_context=context)  # no published draft yet
        fact = own_publication(task, context, evidence)
        boundary.side_effect = lambda *_: copy.deepcopy(fact)
        client.prs = [{'id': 3001, 'number': 30, 'title': 'Contribution', 'body': 'Fixes #12',
                       'html_url': fact['own_pr']['url'], 'head': {'ref': 'agent/bounds'}}]
        context['final_signoff'] = signoff(task, context, evidence)
        calls_before = len(fake.calls)
        result = core.verify(task, evidence, tmp, client, host_context=context)
        return before, result, calls_before, fake


REQUIRE = [{'check': 'test', 'app_id': APP}]
HASH_KEYS = {'contract_sha256', 'mandate_sha256', 'final_signoff_sha256'}


def without_contract_hashes(value, parent=None):
    if isinstance(value, dict):
        return {key: 'HASH' if key in HASH_KEYS or (parent == 'human_signoff' and key == 'sha256') and item
                else without_contract_hashes(item, key) for key, item in value.items()}
    if isinstance(value, list):
        return [without_contract_hashes(item, parent) for item in value]
    return value


class CompletionWiringTests(unittest.TestCase):
    def test_met_requirements_allow_completion(self):
        before, result, calls_before, fake = ci_journey(REQUIRE, [suite(1)], [run(1)])
        self.assertTrue(result['completion_ready'], result['stage_blockers'])
        self.assertEqual(result['ci_gate']['requirements'][0]['state'], 'met')
        self.assertEqual((calls_before, result['ci_gate']['complete']), (0, True))
        self.assertIs(result['ci_gate']['github_paths_changed'], False)

    def test_unmet_requirements_block_only_completion(self):
        golden = json.loads(GOLDEN.read_text('utf-8'))
        for suites, runs, expected in (([suite(1, status='queued')], [run(1)], 'pending'),
                                       ([suite(1)], [run(1, conclusion='failure')], 'failed'),
                                       ([suite(1)], [], 'missing'), ([suite(1)], [run(1, name='test​')], 'missing')):
            with self.subTest(expected=expected):
                _, result, _, _ = ci_journey(REQUIRE, suites, runs)
                self.assertFalse(result['completion_ready'])
                self.assertIn(f'CI requirement test (app {APP}) is {expected}', result['stage_blockers']['completion'])
                for stage in ('implementation', 'draft'):
                    self.assertEqual(result['stage_blockers'][stage], golden[4]['stage_blockers'][stage])
                self.assertTrue(result['publication']['verified'])
                self.assertEqual(result['next_action'], 'none')
                self.assertFalse(any('CI requirement' in error for error in result['errors']))

    def test_no_reads_before_an_exact_head_draft_is_verified(self):
        before, _, calls_before, _ = ci_journey(REQUIRE, [suite(1)], [run(1)])
        self.assertEqual(calls_before, 0)
        self.assertEqual(before['ci_gate']['requirements'][0]['state'], 'unknown')
        self.assertIn(f'CI requirement test (app {APP}) is unknown', before['stage_blockers']['completion'])
        self.assertTrue(before['draft_create_ready'], before['stage_blockers'])

    def test_github_edit_blocks_completion_even_when_every_check_is_met(self):
        def touch(tmp, checkout):
            pathlib.Path(tmp, '.github', 'workflows').mkdir(parents=True)
            pathlib.Path(tmp, '.github', 'workflows', 'ci.yml').write_text('on: push')
            checkout('add', '.')
            checkout('commit', '-q', '-m', 'ci')
        _, result, _, _ = ci_journey(REQUIRE, [suite(1)], [run(1)], extra_commit=touch,
                                     scope={'allowed_paths': ['src/**', '.github/**'], 'prohibited_paths': ['docs/**']})
        self.assertTrue(result['publication']['verified'], result['stage_blockers'])
        self.assertEqual(result['ci_gate']['requirements'][0]['state'], 'met')
        self.assertIs(result['ci_gate']['github_paths_changed'], True)
        self.assertIn(cigate.GITHUB_EDIT, result['stage_blockers']['completion'])
        self.assertFalse(result['completion_ready'])

    def test_signoff_expiring_during_the_ci_reads_is_rejected(self):
        _, result, _, _ = ci_journey(REQUIRE, [suite(1)], [run(1)], advance_on_runs=dt.timedelta(hours=3))
        self.assertEqual(result['ci_gate']['requirements'][0]['state'], 'met')
        self.assertFalse(result['completion_ready'])
        self.assertFalse(result['human_signoff']['valid'])

    def test_invalid_requirements_block_every_stage(self):
        _, result, _, _ = ci_journey(REQUIRE * 2, [suite(1)], [run(1)])
        self.assertIn('CI requirements must be unique', result['errors'])
        self.assertFalse(result['implementation_ready'])
        self.assertFalse(result['completion_ready'])

    def test_an_empty_list_matches_the_golden_and_reads(self):
        _, calls = journey()
        outputs, empty_calls = journey(lambda task: task.update(ci_requirements=[]))
        golden = json.loads(GOLDEN.read_text('utf-8'))
        # The key is present, so the contract hash, and the mandate and sign-off hashes that bind it, differ;
        # every other byte of every stage is the golden's.
        self.assertEqual(without_contract_hashes(json.loads(rendered(outputs))), without_contract_hashes(golden))
        self.assertEqual(empty_calls, calls)


if __name__ == '__main__':
    unittest.main()
