"""counted_pages composes its pagination parameters onto an endpoint that already has a query (#17 slice 1)."""
import unittest

from agent_contribute import remote


class Recorder:
    def __init__(self):
        self.calls = []

    def request(self, endpoint):
        self.calls.append(endpoint)
        return {'total_count': 1, 'check_runs': [{'id': 1}]}


def read(endpoint):
    client = Recorder()
    records, errors, finished = remote.counted_pages(
        client, endpoint, 'check_runs', lambda item: (item['id'], item), page='page', count='Count', noun='run',
        oversize='too many')
    return client.calls, records, errors, finished


class QueryCompositionTests(unittest.TestCase):
    def test_existing_query_gets_ampersand_parameters(self):
        calls, records, errors, finished = read('repos/a/b/commits/c/check-runs?filter=all')
        self.assertEqual(calls, ['repos/a/b/commits/c/check-runs?filter=all&per_page=100&page=1'])
        self.assertEqual((len(records), errors, finished), (1, [], True))

    def test_plain_endpoint_is_unchanged(self):
        self.assertEqual(read('repos/a/b/commits/c/check-runs')[0], ['repos/a/b/commits/c/check-runs?per_page=100&page=1'])


if __name__ == '__main__':
    unittest.main()
