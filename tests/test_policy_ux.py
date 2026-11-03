"""Policy UX follow-ups from external evaluation 2 (N-01, N-02, N-04, N-05)."""
import contextlib
import importlib.resources
import io
import json
import re
import unittest
from unittest.mock import patch

from agent_contribute import cli, core, policy, textfmt
from tests.test_policy import PolicyGitHub, SOURCE_COMMIT, report

STOP_KINDS = {'possible_agent_restriction', 'possible_ai_restriction', 'possible_pr_restriction'}


def installed_workflow():
    return importlib.resources.files('agent_contribute').joinpath('instructions.md').read_text('utf-8')


class HintNoiseTests(unittest.TestCase):
    """N-04: less noise, never fewer stop-class hints."""
    def test_ai_and_agent_hints_rank_above_pr_only_hints(self):
        files = {'README.md': 'Pull requests are only reviewed on Fridays.',
                 'CONTRIBUTING.md': 'Contributions must include tests.\n\nNo AI-generated pull requests.\n\n'
                                    'Autonomous agents are not allowed.',
                 'SECURITY.md': 'Do not open a pull request for vulnerabilities.'}
        result, _ = report(files)
        order = [(h['kind'], result['sources_scanned'][h['source']]['path'], h['line']) for h in result['hints']]
        self.assertEqual(order[0][0], 'possible_agent_restriction')
        self.assertEqual(order[1][0], 'possible_ai_restriction')
        pr = [o for o in order if o[0] == 'possible_pr_restriction']
        self.assertEqual(pr[0][1:], ('CONTRIBUTING.md', 3), 'a PR hint with AI context ranks first among PR hints')
        self.assertEqual(pr[1][1:], ('CONTRIBUTING.md', 1), 'then PR hints from policy files')
        self.assertEqual({p[1] for p in pr[2:]}, {'README.md', 'SECURITY.md'}, 'PR-only hints elsewhere come last')
        self.assertEqual(order[-1][0], 'ai_mention')
        self.assertFalse([h for h in result['hints'] if set(h) - {'id', 'kind', 'line', 'heading', 'untrusted_excerpt',
                                                                  'excerpt_truncated', 'source'}])

    def test_pr_hints_in_policy_files_outrank_earlier_non_policy_sources(self):
        instructions = [{'path': 'README.md', 'sha256': '1' * 64, 'untrusted_text': 'Pull requests are only merged weekly.'}]
        result, _ = report({'README.md': 'x', 'CONTRIBUTING.md': 'Contributions must include tests.'}, {},
                           instructions=instructions)
        pr = [result['sources_scanned'][h['source']]['path'] for h in result['hints']
              if h['kind'] == 'possible_pr_restriction']
        self.assertEqual(pr, ['CONTRIBUTING.md', 'README.md'], 'source order alone would list README first')

    def test_report_size_names_dropped_restriction_hints(self):
        text = '\n\n'.join(('No AI number %d. ' % n) + 'pad ' * 60 for n in range(12))
        with patch.object(policy, 'MAX_REPORT_BYTES', 5000):
            result, _ = report({'CONTRIBUTING.md': text}, {})
        limits = {item['limit']: item for item in result['limits_reached']}
        self.assertTrue(limits['report size: restriction hints']['hides_sources'])
        self.assertFalse(limits['report size: hints']['hides_sources'])
        self.assertTrue(result['limits_hide_sources'])

    def test_stop_class_hints_are_kept_before_mentions(self):
        text = '\n\n'.join('No AI-generated contribution number %d.' % n for n in range(40))
        result, _ = report({'CONTRIBUTING.md': text}, {})
        kinds = [h['kind'] for h in result['hints']]
        self.assertEqual(sum(k in STOP_KINDS for k in kinds), 80, 'every restriction hint is kept')
        limits = {item['limit']: item for item in result['limits_reached']}
        self.assertEqual(limits['hints']['not_reported'], 20)
        self.assertFalse(limits['hints']['hides_sources'])
        self.assertFalse(result['limits_hide_sources'])

    def test_dropping_a_stop_class_hint_is_a_hiding_limit(self):
        text = '\n\n'.join('No AI-generated contribution number %d.' % n for n in range(60))
        result, _ = report({'CONTRIBUTING.md': text}, {})
        self.assertTrue(all(h['kind'] in STOP_KINDS for h in result['hints']))
        limits = {item['limit']: item for item in result['limits_reached']}
        self.assertEqual(limits['restriction hints']['not_reported'], 120 - policy.MAX_HINTS)
        self.assertTrue(limits['restriction hints']['hides_sources'])
        self.assertTrue(result['limits_hide_sources'])

    def test_report_size_drops_mentions_before_restrictions(self):
        text = '\n\n'.join(('No AI number %d. ' % n) + 'pad ' * 60 for n in range(30))
        with patch.object(policy, 'MAX_REPORT_BYTES', 9000):
            result, _ = report({'CONTRIBUTING.md': text}, {})
        limits = {item['limit']: item for item in result['limits_reached']}
        self.assertIn('report size: hints', limits)
        self.assertFalse(limits['report size: hints']['hides_sources'])
        if 'report size: restriction hints' in limits:
            self.assertTrue(limits['report size: restriction hints']['hides_sources'])
            self.assertTrue(result['limits_hide_sources'])
        self.assertNotIn('ai_mention', [h['kind'] for h in result['hints']])


class TextHintTests(unittest.TestCase):
    """N-01: text output shows the sentences that justify a stop."""
    def policy_report(self, files=None, owner=None):
        return report(files or {'CONTRIBUTING.md': 'Thanks!\n\nAI-generated PRs are closed\x1b[2K on sight.\n\n'
                                                  'Autonomous agents are not allowed.\n\n'
                                                  'Pull requests are limited to maintainers.'}, owner or {})[0]

    def test_inspect_text_lists_restriction_hints_with_locations(self):
        text = textfmt.render('inspect', {'reference': 'acme/photos#12', 'repository_policy': self.policy_report()})
        lines = text.splitlines()
        at = next(n for n, line in enumerate(lines) if line.startswith('Policy:'))
        shown = [line for line in lines[at:] if line.startswith('  ! ')]
        self.assertEqual(shown[0], '  ! possible_agent_restriction acme/photos:CONTRIBUTING.md:5 -- '
                                   'Autonomous agents are not allowed.')
        self.assertIn('  ! possible_ai_restriction, possible_pr_restriction acme/photos:CONTRIBUTING.md:3 -- '
                      'AI-generated PRs are closed on sight.', shown)
        self.assertNotIn('\x1b', text)

    def test_text_hint_list_is_bounded_and_counts_the_rest(self):
        files = {'CONTRIBUTING.md': '\n\n'.join('No AI-generated patch %d.' % n for n in range(9))}
        text = textfmt.render('inspect', {'repository_policy': self.policy_report(files)})
        self.assertEqual(sum(line.startswith('  ! ') for line in text.splitlines()), textfmt.POLICY_HINT_LINES)
        self.assertIn(f'(+{9 - textfmt.POLICY_HINT_LINES} more hinted lines with restrictions in JSON '
                      'repository_policy.hinted_lines)', text)

    def test_exactly_one_more_hint_is_counted(self):
        files = {'CONTRIBUTING.md': '\n\n'.join('Autonomous agents are not allowed, case %d.' % n for n in range(6))}
        text = textfmt.render('inspect', {'repository_policy': self.policy_report(files)})
        self.assertEqual(sum(line.startswith('  ! ') for line in text.splitlines()), 5)
        self.assertIn('(+1 more hinted lines with restrictions in JSON repository_policy.hinted_lines)', text)

    def test_the_documented_bound_is_five(self):
        self.assertEqual(textfmt.POLICY_HINT_LINES, 5)
        reference = (__import__('pathlib').Path(__file__).parents[1] / 'docs' / 'cli.md').read_text('utf-8')
        self.assertIn('up to five restriction', ' '.join(reference.split()))

    def test_no_restriction_hints_says_so_without_implying_permission(self):
        text = textfmt.render('inspect', {'repository_policy': self.policy_report({'README.md': 'A library.'})})
        self.assertIn('  No restriction hints; this is not permission.', text)

    def test_discover_and_prepare_text_show_the_hints(self):
        rp = self.policy_report()
        for command, result in (('discover', {'repository': 'acme/photos', 'issues': [], 'repository_policy': rp}),
                                ('prepare', {'output': 'task.json', 'repository_policy': rp})):
            with self.subTest(command):
                self.assertIn('  ! possible_agent_restriction acme/photos:CONTRIBUTING.md:5', textfmt.render(command, result))

    def test_long_excerpts_and_paths_stay_one_bounded_line(self):
        long_path = 'docs/' + 'p' * 400 + '/AI_POLICY.md'
        rp = self.policy_report({long_path: 'Autonomous agents are not allowed. ' + 'x ' * 400})
        line = next(l for l in textfmt.render('inspect', {'repository_policy': rp}).splitlines() if l.startswith('  ! '))
        self.assertLessEqual(len(line), 400)


class QuickPathTests(unittest.TestCase):
    """N-02: the Quick path stop rule and order match the policy section."""
    def quick_path(self):
        text = installed_workflow()
        start = text.index('## Quick path')
        return text[start:text.index('\n## ', start + 1)].rstrip('\n')

    def test_stop_rule_matches_the_policy_section(self):
        quick = ' '.join(self.quick_path().split())
        self.assertIn('the repository policy step finds a relevant rule that is prohibited or unresolved', quick)
        self.assertNotIn('refusal or restriction', quick)
        section = ' '.join(installed_workflow().split())
        self.assertIn('**STOP** upstream work when any relevant rule is prohibited or unresolved.', section)

    def test_policy_step_comes_before_ranking_and_selection(self):
        quick = ' '.join(self.quick_path().split())
        policy_at = quick.index('complete the "Repository policy review" section below')
        self.assertIn('\n## Repository policy review (mandatory; not verifier-enforced)\n', installed_workflow())
        self.assertLess(policy_at, quick.index('Drop excluded or overlapping issues'))
        self.assertLess(policy_at, quick.index("inspect 'owner/repo#N' --ownership"))
        self.assertIn('Before ranking or selecting', quick)

    def test_constrained_mode_needs_the_users_commitment(self):
        quick = ' '.join(self.quick_path().split())
        self.assertIn('first ask the user to commit to that mode', quick)
        section = ' '.join(installed_workflow().split())
        self.assertIn('valid only where the policy permits that mode and after the user commits to it;', section)

    def test_quick_path_stays_short(self):
        self.assertLessEqual(len(self.quick_path().splitlines()), 40)


class FreshDraftMessageTests(unittest.TestCase):
    """N-05: a fresh draft's pending target is 'not yet chosen', not 'invalid'; the ledger covers CLA/DCO."""
    def test_pending_draft_reports_target_not_yet_chosen(self):
        from tests.test_protocol import FakeGitHub
        client = FakeGitHub()
        task = core.prepare(core.inspect_issue('acme/photos#12', client))
        errors = core.verify(task, client=client)['errors']
        self.assertIn('Execution target not yet chosen (execution mode is pending)', errors)
        self.assertNotIn('Execution target repository is invalid', errors)
        self.assertFalse(core.verify(task, client=client)['execution_ready'])

    def test_a_malformed_target_is_still_invalid(self):
        from tests.test_protocol import ready_contract
        task, client = ready_contract()
        task['execution']['target_repository'] = 'not a repository'
        self.assertIn('Execution target repository is invalid', core.verify(task, client=client)['errors'])

    def test_a_malformed_pending_target_is_still_invalid(self):
        from tests.test_protocol import FakeGitHub
        client = FakeGitHub()
        task = core.prepare(core.inspect_issue('acme/photos#12', client))
        task['execution']['target_repository'] = 'not a repository'
        errors = core.verify(task, client=client)['errors']
        self.assertIn('Execution target repository is invalid', errors)
        self.assertNotIn('Execution target not yet chosen (execution mode is pending)', errors)

    def test_requirements_ledger_names_cla_and_dco(self):
        text = ' '.join(installed_workflow().split())
        self.assertIn('contributor agreements such as a CLA or DCO sign-off, which the human submitter must complete',
                      text)


if __name__ == '__main__':
    unittest.main()


class EligibilityTierTests(unittest.TestCase):
    """Maintainers-only / eligibility PR rules rank just below agent restrictions."""
    HONO = ('## AI Usage Policy\n\n'
            + ''.join(f'You may use AI to contribute, but it must never waste a maintainer\'s time, case {n}.\n\n'
                      for n in range(6))
            + 'To enforce this, and regardless of whether AI was actually used, a maintainer may close your issue '
              'without notice and block your account.\n\n'
              '## Issues instead of Pull Requests\n\n'
              'Pull requests are limited to maintainers. If you find a bug or want a change, please create an issue '
              'instead. A clear issue with a minimal reproduction helps us more than a pull request.\n')

    def test_eligibility_rule_is_in_the_text_top_five(self):
        rp, _ = report({'docs/CONTRIBUTING.md': self.HONO}, {})
        shown = [line for line in textfmt.render('inspect', {'repository_policy': rp}).splitlines()
                 if line.startswith('  ! ')]
        self.assertEqual(len(shown), 5)
        self.assertTrue(any('Pull requests are limited to maintainers' in line for line in shown), shown)

    def test_tier_is_below_agent_and_above_ai_hints(self):
        rp, _ = report({'docs/CONTRIBUTING.md': self.HONO + '\nAutonomous agents are not allowed.\n'}, {})
        kinds = [(h['kind'], h['untrusted_excerpt'][:30]) for h in rp['hints']]
        self.assertEqual(kinds[0][0], 'possible_agent_restriction')
        self.assertEqual(kinds[1][0], 'possible_pr_restriction')
        self.assertTrue(kinds[1][1].startswith(('## Issues instead of Pull', 'Pull requests are limited to')), kinds[1])
        self.assertEqual(kinds[3][0], 'possible_ai_restriction')

    def test_each_eligibility_word_lifts_a_pr_rule(self):
        for rule in ('Pull requests are limited to the core team.', 'Pull requests are restricted to the core team.',
                     'Pull requests are by invitation from the core team.', 'Open issues instead of pull requests.',
                     'Pull requests come only from project members.'):
            with self.subTest(rule):
                text = ''.join(f'You may use AI to contribute, but never waste time, case {n}.\n\n' for n in range(6)) + rule
                rp, _ = report({'CONTRIBUTING.md': text}, {})
                self.assertEqual(rp['hints'][0]['kind'], 'possible_pr_restriction')
                self.assertIn(rule[:20], rp['hints'][0]['untrusted_excerpt'])

    def test_a_singular_maintainer_mention_is_not_an_eligibility_rule(self):
        rp, _ = report({'CONTRIBUTING.md': "You may contribute, but never waste a maintainer's time.\n\n"
                                           'Pull requests are limited to maintainers.'}, {})
        pr = [h['untrusted_excerpt'] for h in rp['hints'] if h['kind'] == 'possible_pr_restriction']
        self.assertTrue(pr[0].startswith('Pull requests are limited to maintainers'), pr)


class CommentExcerptTests(unittest.TestCase):
    def test_text_excerpts_drop_html_comment_markers(self):
        rp, _ = report({'.github/pull_request_template.md': '<!--\nAI-generated pull requests are closed.\n-->'}, {})
        line = next(l for l in textfmt.render('inspect', {'repository_policy': rp}).splitlines() if l.startswith('  ! '))
        self.assertTrue(line.endswith('-- AI-generated pull requests are closed.'), line)
        self.assertNotIn('<!--', line)
        self.assertEqual(rp['hints'][0]['untrusted_excerpt'][:4], '<!--', 'JSON keeps the sanitized excerpt as is')


class NestedCommunityTests(unittest.TestCase):
    """RP-25: nested security/governance files are lower priority, never invisible."""
    def test_a_nested_governance_ban_is_scanned_and_shown(self):
        rp, _ = report({'docs/dev/GOVERNANCE.md': 'AI-generated contributions are forbidden.'}, {})
        self.assertEqual([s['path'] for s in rp['sources_scanned']], ['docs/dev/GOVERNANCE.md'])
        self.assertIn('possible_ai_restriction', {h['kind'] for h in rp['hints']})
        text = textfmt.render('inspect', {'repository_policy': rp})
        self.assertIn('acme/photos:docs/dev/GOVERNANCE.md:1 -- AI-generated contributions are forbidden.', text)
        self.assertNotIn('No restriction hints', text)

    def test_nested_community_hints_rank_after_top_level_policy(self):
        rp, _ = report({'doc/source/reference/security.rst': 'AI tools must not be used for vulnerability reports.',
                        'CONTRIBUTING.md': 'Pull requests must include tests.'}, {})
        paths = [rp['sources_scanned'][h['source']]['path'] for h in rp['hints'] if h['kind'] in STOP_KINDS]
        self.assertEqual(paths[-1], 'doc/source/reference/security.rst')

    def test_owner_nested_community_files_are_scanned(self):
        rp, _ = report({}, {'docs/x/SECURITY.md': 'No AI reports.', 'docs/SUPPORT.md': 'x'})
        self.assertEqual({s['path'] for s in rp['sources_scanned']}, {'docs/x/SECURITY.md', 'docs/SUPPORT.md'})


class RetainedHintTextTests(unittest.TestCase):
    """RP-26: the text view never implies that dropped restriction hints did not exist."""
    def base(self, **extra):
        return dict({'sources_scanned': [], 'unassessed': [], 'omitted_sources': [], 'hints': [], 'limits_reached': [],
                     'limits_hide_sources': False}, **extra)

    def test_no_retained_restriction_hints_after_losses(self):
        rp = self.base(limits_reached=[{'limit': 'report size: restriction hints', 'not_reported': 3,
                                        'hides_sources': True}], limits_hide_sources=True)
        text = textfmt.render('inspect', {'repository_policy': rp})
        self.assertIn('No restriction hints retained', text)
        self.assertIn('3 restriction hints not retained because of limits', text)
        self.assertNotIn('No restriction hints; this is not permission.', text)

    def test_dropped_restriction_hints_are_counted_next_to_the_shown_ones(self):
        text = '\n\n'.join('No AI-generated contribution number %d.' % n for n in range(60))
        rp, _ = report({'CONTRIBUTING.md': text}, {})
        view = textfmt.render('inspect', {'repository_policy': rp})
        self.assertIn('(+55 more hinted lines with restrictions in JSON repository_policy.hinted_lines)', view)
        self.assertIn('20 restriction hints not retained because of limits', view)

    def test_excerpts_keep_the_restriction_predicate_and_are_marked_when_cut(self):
        filler = ' '.join('x' * 24 for _ in range(10))
        paragraph = 'w ' * 200 + f'AI {filler} forbidden here. ' + 'tail ' * 200
        hint = [h for h in policy.scan(paragraph, 'CONTRIBUTING.md')['hints'] if h['kind'] == 'possible_ai_restriction'][0]
        self.assertIn('forbidden', hint['untrusted_excerpt'])
        self.assertTrue(hint['excerpt_truncated'])
        rp, _ = report({'CONTRIBUTING.md': paragraph}, {})
        line = next(l for l in textfmt.render('inspect', {'repository_policy': rp}).splitlines() if l.startswith('  ! '))
        self.assertTrue(line.endswith('...'), line)
        self.assertIn('forbidden', line)

    def test_short_excerpts_are_not_marked(self):
        hint = policy.scan('No AI-generated code.', 'CONTRIBUTING.md')['hints'][0]
        self.assertFalse(hint['excerpt_truncated'])


class SubmitterEligibilityTests(unittest.TestCase):
    """RP-27: only rules about who may submit pull requests get the eligibility tier."""
    def first_kind(self, rule):
        rp, _ = report({'CONTRIBUTING.md': 'No AI-generated code.\n\n' + rule}, {})
        return [(h['kind'], h['untrusted_excerpt'][:25]) for h in rp['hints'] if h['kind'] != 'ai_mention']

    def test_review_requirements_are_not_eligibility_rules(self):
        for rule in ('PRs must be reviewed by maintainers.', 'Pull requests need approval from two members.'):
            with self.subTest(rule):
                self.assertEqual(self.first_kind(rule)[0][0], 'possible_ai_restriction', 'not promoted above AI rules')

    def test_singular_and_only_phrasings_are_eligibility_rules(self):
        for rule in ('Only a maintainer may submit pull requests.', 'Pull requests are limited to maintainers.',
                     'Only collaborators can open pull requests.'):
            with self.subTest(rule):
                self.assertEqual(self.first_kind(rule)[0], ('possible_pr_restriction', rule[:25]))

    def test_docs_make_no_text_view_guarantee(self):
        root = __import__('pathlib').Path(__file__).parents[1]
        for name in ('CHANGELOG.md', 'docs/cli.md'):
            with self.subTest(name):
                self.assertNotIn('always reaches the text view', ' '.join((root / name).read_text('utf-8').split()))


class GroupedHintTests(unittest.TestCase):
    """N2: one reading entry per hinted line; project-name vocabulary mentions are summarized, never restrictions."""
    def agent_repo(self, files):
        client = PolicyGitHub(files, {})
        client.repos['acme/agent-kit'] = client.repos.pop('acme/photos')
        return policy.report('acme/agent-kit', SOURCE_COMMIT, [], client, default_branch='main')

    def test_hints_on_one_line_are_grouped(self):
        rp, _ = report({'CONTRIBUTING.md': 'AI-generated PRs are closed on sight.\n\nUse AI responsibly.'}, {})
        lines = rp['hinted_lines']
        self.assertEqual([(l['line'], l['kinds']) for l in lines],
                         [(1, ['possible_ai_restriction', 'possible_pr_restriction', 'ai_mention']), (3, ['ai_mention'])])
        self.assertEqual(lines[0]['untrusted_excerpt'], 'AI-generated PRs are closed on sight.')
        self.assertEqual(len(rp['hints']), 4, 'the per-kind hints are unchanged')

    def test_project_vocabulary_mentions_are_collapsed_but_restrictions_never(self):
        rp = self.agent_repo({'README.md': 'The agent kit runs an agent per task.\n\nAgents are fast.\n\n'
                                           'Agents must not open pull requests.\n\nUse ChatGPT for drafts.'})
        vocab = rp['project_vocabulary']
        self.assertEqual(vocab['terms'], ['agent'])
        self.assertEqual(vocab['mentions_collapsed'], 2)
        self.assertEqual([l['line'] for l in vocab['lines']], [1, 3])
        lines = {l['line']: l['kinds'] for l in rp['hinted_lines']}
        self.assertEqual(set(lines), {5, 7})
        self.assertIn('possible_agent_restriction', lines[5])
        self.assertIn('ai_mention', lines[7])
        self.assertEqual(sum(h['kind'] == 'ai_mention' for h in rp['hints']), 4, 'hints keep every mention')

    def test_no_project_vocabulary_without_name_terms(self):
        rp, _ = report({'README.md': 'An agent helps.'}, {})
        self.assertEqual(rp['project_vocabulary'], {'terms': [], 'mentions_collapsed': 0, 'lines': [],
                                                    'lines_not_listed': 0})
        self.assertEqual(rp['hinted_lines'][0]['kinds'], ['ai_mention'])

    def test_text_view_groups_lines_and_reports_collapsed_vocabulary(self):
        rp = self.agent_repo({'CONTRIBUTING.md': 'AI-generated PRs are closed on sight.\n\nThe agent kit is an agent.'})
        text = textfmt.render('inspect', {'repository_policy': rp})
        self.assertIn('  ! possible_ai_restriction, possible_pr_restriction acme/agent-kit:CONTRIBUTING.md:1 -- '
                      'AI-generated PRs are closed on sight.', text)
        self.assertIn("  1 mention of project-name vocabulary ('agent') summarized in JSON project_vocabulary", text)

    def test_obligation_says_read_every_hinted_line(self):
        self.assertIn('every hinted line', policy.OBLIGATION)
        self.assertIn('every hinted line in context', ' '.join(installed_workflow().split()))
