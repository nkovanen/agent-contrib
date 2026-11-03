"""route_errors extraction must leave authorization.check output byte-identical."""
import copy
import json
import pathlib
import unittest
from unittest.mock import patch

from agent_contribute import authorization, core
from tests.test_authorization import NOW, candidate_task, host_context
from tests.test_lifecycle import Clock

GOLDEN = pathlib.Path(__file__).resolve().parent / 'fixtures' / 'route' / 'check_golden.json'


def cases():
    """Each case binds the mandate to its own task, so only route checks differ."""
    changes = {
        'valid': {},
        'mode_pending': {'mode': 'pending'},
        'invalid_head_ref': {'head_ref': 'HEAD'},
        'invalid_base_ref': {'base_ref': 'bad..ref'},
        'base_not_default': {'base_ref': 'develop'},
        'head_equals_base': {'head_ref': 'main'},
        'other_target': {'target_repository': 'other/photos'},
        'other_head_id': {'head_repository_id': 999},
        'duplicate_requested': {'requested_actions': ['implement', 'implement']},
        'combined': {'mode': 'pending', 'head_ref': 'main', 'target_repository_id': 5},
    }
    for name, change in changes.items():
        task, client = candidate_task()
        task['execution'].update(change)
        yield name, task, client, host_context(task)
    task, client = candidate_task()
    yield 'no_mandate', task, client, None
    task, client = candidate_task()
    yield 'invalid_host_context', task, client, {'schema_version': '0.1'}


def outputs():
    # Preparation timestamps feed the contract hash, so freeze the clock for a stable golden.
    with patch.object(core.dt, 'datetime', Clock):
        return {name: authorization.check(task, context, client, NOW) for name, task, client, context in cases()}


class RouteErrorsTests(unittest.TestCase):
    def test_check_output_matches_pre_refactor_golden(self):
        self.assertEqual(json.loads(json.dumps(outputs())), json.loads(GOLDEN.read_text('utf-8')))

    def test_route_errors_are_exactly_the_contract_only_errors_of_check(self):
        for name, task, client, context in cases():
            if context is None or 'mandate' not in context:
                continue
            with self.subTest(case=name):
                route = authorization.route_errors(task)
                errors = authorization.check(task, context, client, NOW)['errors']
                self.assertEqual([error for error in errors if error in route], route)
                self.assertEqual(route == [], name in ('valid', 'duplicate_requested'))

    def test_route_errors_read_only_the_task(self):
        task, _ = candidate_task()
        before = copy.deepcopy(task)
        self.assertEqual(authorization.route_errors(task), [])
        self.assertEqual(task, before)



class VerifyRouteTests(unittest.TestCase):
    """A2-02: verify lists contract route errors with or without a mandate, once each, and never fewer blockers."""
    ROUTE = ['Execution mode is pending', 'Invalid reviewed Git ref: head_ref']

    def verify(self, with_context):
        task, client = candidate_task()
        task['execution'].update(mode='pending', head_ref='bad..ref')
        context = host_context(task) if with_context else None
        with patch.object(core.dt, 'datetime', Clock):
            return core.verify(task, client=client, host_context=context)

    def test_route_errors_without_a_mandate(self):
        result = self.verify(False)
        for stage in ('implementation', 'draft', 'completion'):
            for error in self.ROUTE:
                self.assertEqual(result['stage_blockers'][stage].count(error), 1, (stage, error))
        self.assertIn('Missing human/host mandate', result['stage_blockers']['implementation'])
        self.assertFalse(result['implementation_ready'])

    def test_route_errors_with_a_mandate_are_listed_once(self):
        result = self.verify(True)
        for error in self.ROUTE:
            self.assertEqual(result['stage_blockers']['implementation'].count(error), 1, error)
            self.assertIn(error, result['user_authorization']['errors'])  # the authorization result is unchanged
        self.assertFalse(result['user_authorization']['historical_valid'])

    def test_valid_route_adds_nothing(self):
        task, client = candidate_task()
        with patch.object(core.dt, 'datetime', Clock):
            result = core.verify(task, client=client)
        self.assertEqual(authorization.route_errors(task), [])
        self.assertFalse(any(error in self.ROUTE for error in result['errors']))


if __name__ == '__main__':
    unittest.main()
