"""A pull request whose creation time is still in the future is not an already published draft (FR1-03)."""
import datetime as dt
import unittest

from tests import test_lifecycle
from tests.test_authorization import NOW

FUTURE = 'Pull request creation time is in the future'


class PublicationTimeTests(unittest.TestCase):
    setUp = test_lifecycle.IntegratedLifecycleTests.setUp
    verify = test_lifecycle.IntegratedLifecycleTests.verify
    publish = test_lifecycle.IntegratedLifecycleTests.publish

    def test_future_creation_inside_the_mandate_interval_is_not_recognized(self):
        self.publish()
        self.assertTrue(self.verify()['publication']['verified'])
        created = (NOW + dt.timedelta(minutes=30)).isoformat()
        for record in [self.client.history[0], self.client.details[30]] + self.client.prs:
            record['created_at'] = created
        result = self.verify()
        self.assertFalse(result['publication']['verified'])
        self.assertIn(FUTURE, result['publication']['errors'])
        self.assertTrue(result['stage_blockers']['draft'])

    def test_creation_exactly_now_is_accepted(self):
        self.publish()
        for record in [self.client.history[0], self.client.details[30]] + self.client.prs:
            record['created_at'] = NOW.isoformat()
        self.assertTrue(self.verify()['publication']['verified'])


if __name__ == '__main__':
    unittest.main()
