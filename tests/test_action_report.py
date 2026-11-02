"""Passive maintainer Action, slice 1: offline report from the event payload and the PR-head checkout (#11)."""
import contextlib
import copy
import importlib.util
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import core
from tests.test_authorization import candidate_task
from tests.test_protocol import evidence_checkout

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_report():
    spec = importlib.util.spec_from_file_location('agent_contrib_action_report', ROOT / 'actions' / 'verify' / 'report.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


report = load_report()
FENCE = '```'


def body(task=None, evidence=None, extra=''):
    parts = ['Agent PR', '']
    if task is not None:
        parts += [FENCE + 'agent-contrib-task', json.dumps(task), FENCE, '']
    if evidence is not None:
        parts += [FENCE + 'agent-contrib-evidence', json.dumps(evidence), FENCE, '']
    return '\n'.join(parts) + extra


def payload(text, head_sha='a' * 40, head_ref='agent/bounds', head_repo=('acme/photos', 101),
            base_ref='main', base_repo=('acme/photos', 101), number=30):
    def repo(value):
        return None if value is None else {'full_name': value[0], 'id': value[1]}
    return {'pull_request': {'number': number, 'body': text, 'html_url': f'https://github.com/acme/photos/pull/{number}',
                             'head': {'sha': head_sha, 'ref': head_ref, 'repo': repo(head_repo)},
                             'base': {'ref': base_ref, 'repo': repo(base_repo)}}}


class ParserTests(unittest.TestCase):
    def test_one_task_and_one_evidence_block(self):
        task, evidence = report.parse_blocks(body({'schema_version': '0.1'}, {'schema_version': '0.1'}))
        self.assertEqual((task, evidence), ({'schema_version': '0.1'}, {'schema_version': '0.1'}))
        self.assertEqual(report.parse_blocks(body({'a': 1}).replace('\n', '\r\n')), ({'a': 1}, None))
        trailing = body({'a': 1}).replace(FENCE + 'agent-contrib-task', FENCE + 'agent-contrib-task \t')
        self.assertEqual(report.parse_blocks(trailing), ({'a': 1}, None))

    def test_missing_ambiguous_and_misplaced_blocks_are_not_checked(self):
        cases = {
            'none': 'Plain PR description',
            'null body': None,
            'duplicate task': body({'a': 1}) + body({'a': 2}),
            'duplicate evidence': body({'a': 1}, {'e': 1}) + body(evidence={'e': 2}),
            'hidden in an HTML comment': body({'a': 1}) + '\n<!--\n' + body({'a': 2}) + '\n-->',
            'inside a longer fence': '````\n' + body({'a': 2}) + '\n````\n' + body({'a': 1}),
            'indented only': '   ' + FENCE + 'agent-contrib-task\n{}\n' + FENCE,
            'quoted copy': body({'a': 1}) + '\n> ' + FENCE + 'agent-contrib-task',
            'inline mention': 'see ' + FENCE + 'agent-contrib-task here\n' + body({'a': 1}),
            'unterminated': FENCE + 'agent-contrib-task\n{"a": 1}\n',
            'near-miss info string': FENCE + 'agent-contrib-tasks\n{}\n' + FENCE,
            'evidence only': body(evidence={'e': 1}),
        }
        for name, text in cases.items():
            with self.subTest(name=name), self.assertRaises(report.NotChecked):
                report.parse_blocks(text)

    def test_bounds_and_strict_json(self):
        filler = 'x' * (32 * 1024 - len('{"a":""}'))
        self.assertEqual(report.parse_blocks(body({'a': filler}).replace(': ', ':'))[0], {'a': filler})
        for text in (body({'a': filler + 'x'}).replace(': ', ':'), 'x' * 65537,
                     FENCE + 'agent-contrib-task\n{"a": 1, "a": 2}\n' + FENCE,
                     FENCE + 'agent-contrib-task\n{"a": NaN}\n' + FENCE,
                     FENCE + 'agent-contrib-task\n{"a": "\\ud800"}\n' + FENCE,
                     FENCE + 'agent-contrib-task\nnot json\n' + FENCE):
            with self.subTest(text=text[:60]), self.assertRaises(report.NotChecked):
                report.parse_blocks(text)


class PayloadTests(unittest.TestCase):
    def test_complete_payload(self):
        facts = report.pr_facts(payload('x'))
        self.assertEqual(facts['head_repo'], ('acme/photos', 101))
        self.assertIsNone(report.pr_facts(payload('x', head_repo=None))['head_repo'])

    def test_missing_or_mistyped_facts_are_not_checked(self):
        bad = []
        for path, value in [(('number',), True), (('number',), 0), (('head', 'sha'), 'A' * 40), (('head', 'sha'), None),
                            (('head', 'ref'), 5), (('base', 'ref'), None), (('base', 'repo'), None),
                            (('base', 'repo', 'id'), '101'), (('head', 'repo', 'full_name'), None), (('body',), 7)]:
            event = payload('x')
            target = event['pull_request']
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            bad.append(event)
        bad += [{}, {'pull_request': None}, {'pull_request': {'number': 1}}, []]
        for event in bad:
            with self.subTest(event=str(event)[:80]), self.assertRaises(report.NotChecked):
                report.pr_facts(event)


def states(checks):
    return {check['name']: check['state'] for check in checks}


class RouteTests(unittest.TestCase):
    def test_schema_02_binds_base_and_head_repositories_ids_and_refs(self):
        task, _ = candidate_task()
        execution = task['execution']
        facts = report.pr_facts(payload('x', head_ref=execution['head_ref'], base_ref=execution['base_ref'],
                                        head_repo=(execution['head_repository'], execution['head_repository_id']),
                                        base_repo=(execution['target_repository'], execution['target_repository_id'])))
        good = report.route_checks(task, facts, 'acme/photos')
        self.assertTrue(good and all(check['state'] == 'match' for check in good), good)
        counterexamples = {
            'head repository': dict(head_repo=('outsider/photos', execution['head_repository_id'])),
            'head repository id': dict(head_repo=(execution['head_repository'], 999)),
            'head ref': dict(head_ref='other'),
            'base ref': dict(base_ref='release'),
            'target repository id': dict(base_repo=(execution['target_repository'], 999)),
        }
        for name, change in counterexamples.items():
            values = dict(head_ref=execution['head_ref'], base_ref=execution['base_ref'],
                          head_repo=(execution['head_repository'], execution['head_repository_id']),
                          base_repo=(execution['target_repository'], execution['target_repository_id']))
            values.update(change)
            with self.subTest(name=name):
                checks = report.route_checks(task, report.pr_facts(payload('x', **values)), 'acme/photos')
                self.assertEqual(sum(check['state'] == 'mismatch' for check in checks), 1, checks)
        moved = copy.deepcopy(task)
        moved['source']['repository'] = 'other/photos'
        self.assertIn('mismatch', states(report.route_checks(moved, facts, 'acme/photos')).values())
        self.assertIn('mismatch', states(report.route_checks(task, facts, 'other/repo')).values())
        deleted = report.pr_facts(payload('x', head_repo=None, base_ref=execution['base_ref'],
                                          base_repo=(execution['target_repository'], execution['target_repository_id'])))
        checks = report.route_checks(task, deleted, 'acme/photos')
        self.assertEqual([c['state'] for c in checks if c['name'].startswith('Head')], ['not-evaluated'] * 4)

    def test_schema_01_route_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            task, _, _, _ = evidence_checkout(tmp)
        facts = report.pr_facts(payload('x'))
        checks = report.route_checks(task, facts, 'acme/photos')
        self.assertTrue(all(check['state'] == 'match' for check in checks), checks)
        self.assertEqual([check['name'] for check in checks if check['name'].startswith('Head')], ['Head repository is known'])
        fork = copy.deepcopy(task)
        fork['execution'].update(mode='fork-experiment', target_repository='human/photos')
        self.assertEqual(sorted(states(report.route_checks(fork, facts, 'acme/photos')).values()).count('mismatch'), 2)
        self.assertIn('not bound by schema 0.1', ' '.join(report.SCHEMA_01_NOTE))


class CheckoutCase(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.repo = pathlib.Path(self.workspace.name, 'pr-head')
        self.repo.mkdir()
        self.task, _, self.evidence, self.git = evidence_checkout(str(self.repo))
        self.head = self.git('rev-parse', 'HEAD')

    def environ(self, text, **changes):
        event = pathlib.Path(self.workspace.name, 'event.json')
        event.write_text(json.dumps(payload(text, head_sha=self.head, **changes)))
        return {'GITHUB_EVENT_NAME': 'pull_request', 'GITHUB_EVENT_PATH': str(event), 'GITHUB_REPOSITORY': 'acme/photos',
                'GITHUB_WORKSPACE': self.workspace.name, 'AGENT_CONTRIB_CHECKOUT': 'pr-head'}

    def build(self, task=None, evidence=None, **changes):
        task = self.task if task is None else task
        evidence = self.evidence if evidence is None else evidence
        return report.build(self.environ(body(task, evidence), **changes))


class CheckoutTests(CheckoutCase):
    def test_consistent_schema_01_evidence(self):
        model = self.build()
        self.assertEqual(model['result'], 'no-inconsistency', model)
        names = [check['name'] for _, checks in model['sections'] for check in checks]
        for expected in ('Evidence git_head is the PR head', 'Evidence git_tree is the head tree',
                         'Evidence contract_sha256 is the contract hash', 'Changes stay within the contract scope'):
            self.assertIn(expected, names)

    def test_each_evidence_mismatch_is_counted(self):
        mutations = {'git_head': 'b' * 40, 'git_tree': 'c' * 40, 'contract_sha256': 'd' * 64, 'worktree_clean': False}
        for key, value in mutations.items():
            with self.subTest(key=key):
                model = self.build(evidence=dict(self.evidence, **{key: value}))
                self.assertEqual((model['result'], model['mismatches']), ('inconsistent', 1), model)

    def test_base_ancestry_and_missing_history(self):
        other = self.git('commit-tree', '-m', 'unrelated', self.git('rev-parse', 'HEAD^{tree}'))
        model = self.build(evidence=dict(self.evidence, base_commit=other))
        self.assertEqual(model['result'], 'inconsistent')
        model = self.build(evidence=dict(self.evidence, base_commit='e' * 40))
        self.assertEqual(model['result'], 'not-checked')
        self.assertIn('could not be evaluated', model['reason'])

    def test_operational_ancestry_failure_is_not_a_mismatch(self):
        real = core.git_read

        def failing(directory, *args, **kwargs):
            if args[:1] == ('rev-list',):
                raise core.ProtocolError('git_error', 'Git evidence checkout read failed')
            return real(directory, *args, **kwargs)
        with patch.object(core, 'git_read', side_effect=failing):
            model = self.build()
        rows = {c['name']: c['state'] for _, checks in model['sections'] for c in checks}
        self.assertEqual(rows['Evidence base_commit is an ancestor of the PR head'], 'not-evaluated')
        self.assertEqual(rows['source.commit is an ancestor of evidence base_commit'], 'not-evaluated')
        self.assertEqual((model['result'], model['mismatches']), ('not-checked', 0))

    def test_shallow_history_is_not_evaluated(self):
        shallow = pathlib.Path(self.workspace.name, 'shallow')
        # Depth 2 still contains the base commit, so only the shallow-history rule makes this not evaluated.
        subprocess.run(['git', 'clone', '-q', '--depth', '2', 'file://' + str(self.repo), str(shallow)], check=True)
        environ = dict(self.environ(body(self.task, self.evidence)), AGENT_CONTRIB_CHECKOUT='shallow')
        model = report.build(environ)
        rows = {c['name']: c['state'] for _, checks in model['sections'] for c in checks}
        self.assertEqual(rows['Evidence base_commit is an ancestor of the PR head'], 'not-evaluated')
        self.assertEqual(model['result'], 'not-checked')

    def test_scope_violation(self):
        (self.repo / '.github').mkdir()
        (self.repo / '.github' / 'ci.yml').write_text('x')
        self.git('add', '.')
        self.git('commit', '-q', '-m', 'ci change')
        self.head = self.git('rev-parse', 'HEAD')
        evidence = dict(self.evidence, git_head=self.head, git_tree=self.git('rev-parse', 'HEAD^{tree}'))
        model = self.build(evidence=evidence)
        self.assertEqual(model['result'], 'inconsistent')
        self.assertIn('.github/ci.yml', report.render(model))

    def test_invalid_documents_and_missing_evidence(self):
        model = self.build(task=dict(self.task, status='bogus'))
        self.assertEqual(model['result'], 'inconsistent')
        model = self.build(evidence=dict(self.evidence, validations='x'))
        self.assertEqual(model['result'], 'inconsistent')
        model = self.build(evidence=dict(self.evidence, schema_version='0.2'))
        self.assertEqual(model['result'], 'inconsistent')
        model = report.build(self.environ(body(self.task)))
        self.assertEqual(model['result'], 'not-checked')
        self.assertIn('No evidence block', model['reason'])

    def test_evidence_row_reflects_its_own_validation(self):
        def rows(model):
            return {c['name']: c['state'] for _, checks in model['sections'] for c in checks}
        evidence_row = 'Evidence matches the evidence schema of the contract version'
        model = self.build(task=dict(self.task, status='invalid'), evidence={'schema_version': '0.1'})
        self.assertEqual(rows(model)[evidence_row], 'mismatch')
        self.assertGreaterEqual(len(model['sections'][0][1][1]['details']), 10)
        model = self.build(task=dict(self.task, status='invalid'))
        self.assertEqual(rows(model)[evidence_row], 'match')
        model = self.build(task=dict(self.task, schema_version='0.9'))
        self.assertEqual(rows(model)[evidence_row], 'not-evaluated')
        model = self.build(task={'schema_version': '0.1'}, evidence=dict(self.evidence, schema_version='0.2'))
        self.assertEqual(rows(model)[evidence_row], 'mismatch')

    def test_checkout_must_be_the_payload_head_inside_the_workspace(self):
        self.assertEqual(self.build(head_ref='agent/bounds')['result'], 'no-inconsistency')
        environ = self.environ(body(self.task, self.evidence))
        for checkout in ('../elsewhere', '/tmp', 'pr-head/src', 'missing'):
            with self.subTest(checkout=checkout):
                self.assertEqual(report.build(dict(environ, AGENT_CONTRIB_CHECKOUT=checkout))['result'], 'not-checked')
        with tempfile.TemporaryDirectory() as outside:
            # A symlink inside the workspace must not lead the check to a checkout elsewhere.
            evidence_checkout(outside)
            pathlib.Path(self.workspace.name, 'link').symlink_to(outside, target_is_directory=True)
            self.assertEqual(report.build(dict(environ, AGENT_CONTRIB_CHECKOUT='link'))['result'], 'not-checked')
        self.head = 'f' * 40
        self.assertEqual(report.build(self.environ(body(self.task, self.evidence)))['result'], 'not-checked')

    def test_event_and_environment_failures_are_not_checked(self):
        environ = self.environ(body(self.task, self.evidence))
        for change in ({'GITHUB_EVENT_NAME': 'pull_request_target'}, {'GITHUB_EVENT_PATH': '/nonexistent'},
                       {'GITHUB_REPOSITORY': ''}, {'GITHUB_WORKSPACE': ''}):
            with self.subTest(change=change):
                self.assertEqual(report.build(dict(environ, **change))['result'], 'not-checked')

    def test_internal_errors_never_report_consistency(self):
        environ = self.environ(body(self.task, self.evidence))
        with patch.object(report, 'evidence_checks', side_effect=RuntimeError('boom ::add-mask::x')):
            code, out, summary = run_main(environ)
        self.assertEqual(code, 0)
        self.assertIn('Not checked', summary)
        self.assertNotIn('boom', out + summary)


class IsolationTests(CheckoutCase):
    def test_script_run_ignores_modules_planted_in_the_checkout_and_working_directory(self):
        marker = pathlib.Path(self.workspace.name, 'planted-code-ran')
        planted = f'open({str(marker)!r}, "w").close()\n'
        for directory in (self.repo, pathlib.Path(self.workspace.name)):
            (directory / 'json.py').write_text(planted)
            (directory / 'agent_contribute').mkdir()
            (directory / 'agent_contribute' / '__init__.py').write_text(planted)
        summary = pathlib.Path(self.workspace.name, 'summary.md')
        environ = dict(self.environ(body(self.task, self.evidence)), GITHUB_STEP_SUMMARY=str(summary),
                       PATH=os.environ.get('PATH', ''), PYTHONPATH=str(self.repo), RUNNER_TEMP=self.workspace.name)
        result = subprocess.run([sys.executable, '-I', str(ROOT / 'actions' / 'verify' / 'report.py')], cwd=self.repo,
                                env=environ, capture_output=True, text=True, timeout=60)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertFalse(marker.exists())
        # The planted files are untracked changes, so the scope check reports them; the run itself stays isolated.
        self.assertRegex(result.stdout, r'\AAgent Contrib report written to the job summary: [a-z-]+\n\Z')
        self.assertIn('## Agent Contrib report (report-only)', summary.read_text('utf-8'))


class HeadRepositoryTests(CheckoutCase):
    def test_null_head_repository_is_never_a_complete_schema_01_result(self):
        model = self.build(head_repo=None)
        self.assertEqual(model['result'], 'not-checked', model)
        rows = {c['name']: c['state'] for _, checks in model['sections'] for c in checks}
        self.assertEqual(rows['Head repository is known'], 'not-evaluated')
        code, _, summary = run_main(self.environ(body(self.task, self.evidence), head_repo=None))
        self.assertNotIn('No inconsistency found', summary)
        self.assertIn('- not evaluated: Head repository is known', summary)

    def test_absent_head_repository_key_is_a_malformed_payload(self):
        event = payload(body(self.task, self.evidence), head_sha=self.head)
        del event['pull_request']['head']['repo']
        with self.assertRaises(report.NotChecked):
            report.pr_facts(event)
        path = pathlib.Path(self.workspace.name, 'event.json')
        environ = self.environ('x')
        path.write_text(json.dumps(event))
        model = report.build(environ)
        self.assertEqual((model['result'], model['reason']), ('not-checked', 'the event payload lacks pull request facts'))


class SchemaTwoCheckoutTests(CheckoutCase):
    def test_consistent_schema_02_route_and_evidence(self):
        task, _ = candidate_task()
        self.git('checkout', '-q', '-b', task['execution']['head_ref'])
        task['source']['commit'] = self.task['source']['commit']
        digest = core.canonical_hash(task)
        evidence = dict(copy.deepcopy(self.evidence), schema_version='0.2', contract_sha256=digest)
        del evidence['human_signoff']
        evidence['independent_review'].update(contract_sha256=digest, reviewed_at='2026-11-02T00:00:00+00:00')
        execution = task['execution']
        route = dict(head_ref=execution['head_ref'], base_ref=execution['base_ref'],
                     head_repo=(execution['head_repository'], execution['head_repository_id']),
                     base_repo=(execution['target_repository'], execution['target_repository_id']))
        model = self.build(task=task, evidence=evidence, **route)
        self.assertEqual(model['result'], 'no-inconsistency', model)
        model = self.build(task=task, evidence=evidence, **dict(route, head_repo=('outsider/photos', 555)))
        self.assertEqual((model['result'], model['mismatches']), ('inconsistent', 2))


def run_main(environ):
    with tempfile.TemporaryDirectory() as tmp:
        summary = pathlib.Path(tmp, 'summary.md')
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = report.main(dict(environ, GITHUB_STEP_SUMMARY=str(summary)))
        return code, out.getvalue() + err.getvalue(), summary.read_text('utf-8') if summary.exists() else ''


HOSTILE = ['[link](https://example.invalid)', '![img](https://example.invalid/x.png)', '<img src=x onerror=alert(1)>',
           '# All gates passed', '| a | b |', '`code` ```fence```', '@maintainer', 'evil\u202egnp.exe', 'zero\u200bwidth',
           'line1\nline2\r\n- injected bullet', '::add-mask::secret', 'x ##[error]fake', '::stop-commands::t', 'A' * 10000]
LINE_SHAPES = [re.compile(pattern) for pattern in (
    r'', r'## Agent Contrib report \(report-only\)', r'\*\*Result: [A-Za-z0-9 ,.:;()/-]+\*\*', r'### [A-Za-z0-9 ,.()/-]+',
    r'- [A-Za-z0-9 ,.;:()\'/_-]+', r'- (match|mismatch|not evaluated): [A-Za-z0-9 ,.;()/_-]+',
    r'- PR [0-9]+ at head `[0-9a-f]{40}`',
    r'  - [A-Za-z0-9 ,.()_-]*(`[^`\n]+`[A-Za-z0-9 ,.()_-]*)+', r'  - [0-9]+ more not shown')]


class RenderingTests(CheckoutCase):
    def hostile_environ(self, value):
        # Attacker-controlled slots: the PR's repository names and refs, and a committed file name.
        evidence = self.evidence
        name = value.replace('/', '_')[:200]
        if '\0' not in name and name not in ('.', '..'):
            (self.repo / name).write_text('x')
            self.git('add', '-A')
            self.git('commit', '-q', '-m', 'hostile path')
            self.head = self.git('rev-parse', 'HEAD')
            evidence = dict(evidence, git_head=self.head, git_tree=self.git('rev-parse', 'HEAD^{tree}'))
        return self.environ(body(self.task, evidence), head_ref=value, base_ref=value,
                            head_repo=(value, 1), base_repo=(value, 2))

    def test_untrusted_values_render_only_inside_single_code_spans(self):
        for value in HOSTILE:
            with self.subTest(value=value[:40]):
                code, out, summary = run_main(self.hostile_environ(value))
                self.assertEqual(code, 0)
                self.assertLessEqual(len(summary.encode()), 64 * 1024)
                for line in summary.split('\n'):
                    self.assertTrue(any(shape.fullmatch(line) for shape in LINE_SHAPES), line)
                outside = re.sub(r'`[^`\n]*`', '', summary)
                for marker in ('](', '<img', '@maintainer', '\u202e', '\u200b', '::', '##[', 'injected'):
                    self.assertNotIn(marker, outside)
                for marker in ('\u202e', '\u200b', '\r'):
                    self.assertNotIn(marker, summary)
                self.assertNotIn('Reject out-of-bounds thumbnails', summary)  # contract prose

    def test_logs_carry_only_fixed_lines(self):
        for value in HOSTILE:
            with self.subTest(value=value[:40]):
                code, out, _ = run_main(self.hostile_environ(value))
                self.assertRegex(out, r'\AAgent Contrib report written to the job summary: '
                                      r'(no-inconsistency|inconsistent|not-checked)\n\Z')

    def test_summary_cap_and_item_cap(self):
        model = {'result': 'inconsistent', 'mismatches': 1, 'reason': '', 'pr': 30, 'head': 'a' * 40,
                 'sections': [('Documents', [{'name': 'Contract matches the task schema', 'state': 'mismatch',
                                              'details': ['x' * 500] * 500}])]}
        text = report.render(model)
        self.assertIn('450 more not shown', text)
        self.assertLessEqual(len(text.encode()), 64 * 1024)
        big = dict(model, sections=[('Documents', [dict(model['sections'][0][1][0], name=f'Check {n}')
                                                   for n in range(400)])])
        self.assertLessEqual(len(report.render(big).encode()), 64 * 1024)

    def test_fixed_disclaimers_and_result_wording(self):
        code, _, summary = run_main(self.environ(body(self.task, self.evidence)))
        self.assertIn('**Result: No inconsistency found in the checks below**', summary)
        for statement in ('Evidence is self-attested', 'Verification is not review', 'Job status carries no meaning'):
            self.assertIn(statement, summary)
        for word in ('passed', 'approved', 'verified', 'safe'):
            self.assertNotRegex(summary.split('### Not evaluated')[0].lower(), rf'\b{word}\b')


if __name__ == '__main__':
    unittest.main()
