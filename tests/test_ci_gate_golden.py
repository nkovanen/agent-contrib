"""Schema 0.2 contracts without ci_requirements verify byte-identically to the pre-#17 code (golden at 33c25ea)."""
import copy
import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import core, lifecycle
from tests.test_authorization import candidate_task, host_context
from tests.test_lifecycle import Clock, NOW, absent_publication, own_publication, signoff
from tests.test_protocol import evidence_checkout

GOLDEN = pathlib.Path(__file__).resolve().parent / 'fixtures' / 'ci_gate' / 'verify_0_2_without_requirements.json'
DATES = {'GIT_AUTHOR_DATE': '2026-11-01T00:00:00+00:00', 'GIT_COMMITTER_DATE': '2026-11-01T00:00:00+00:00'}


def journey(task_change=None):
    """The candidate journey of LifecycleTests: no context, no evidence, evidence, published draft, signed off."""
    import datetime as dt
    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, DATES), \
            patch.object(core.dt, 'datetime', Clock), \
            patch.object(lifecycle, 'check_publication', side_effect=absent_publication, create=True) as boundary:
        task, client = candidate_task()
        legacy, _, evidence, git = evidence_checkout(tmp)
        git('checkout', '-q', '-b', 'agent/bounds')
        task['source']['commit'] = legacy['source']['commit']
        client.commit = legacy['source']['commit']
        if task_change:
            task_change(task)
        context = host_context(task)
        digest = core.canonical_hash(task)
        evidence.update(schema_version='0.2', contract_sha256=digest)
        del evidence['human_signoff']
        evidence['independent_review'].update(contract_sha256=digest, reviewed_at=(NOW - dt.timedelta(minutes=10)).isoformat())
        for validation in evidence['validations']:
            validation.update(started_at=(NOW - dt.timedelta(minutes=20)).isoformat(),
                              finished_at=(NOW - dt.timedelta(minutes=19)).isoformat())
        outputs = [core.verify(task, None, tmp, client, host_context=None),
                   core.verify(task, None, tmp, client, host_context=context),
                   core.verify(task, evidence, tmp, client, host_context=context)]
        fact = own_publication(task, context, evidence)
        boundary.side_effect = lambda *_: copy.deepcopy(fact)
        client.prs = [{'id': 3001, 'number': 30, 'title': 'Contribution', 'body': 'Fixes #12',
                       'html_url': fact['own_pr']['url'], 'head': {'ref': 'agent/bounds'}}]
        outputs.append(core.verify(task, evidence, tmp, client, host_context=context))
        context['final_signoff'] = signoff(task, context, evidence)
        outputs.append(core.verify(task, evidence, tmp, client, host_context=context))
        return outputs, client.calls


def rendered(outputs):
    return json.dumps(outputs, indent=1, sort_keys=True, ensure_ascii=True) + '\n'


class WithoutRequirementsGoldenTests(unittest.TestCase):
    def test_journey_matches_the_pre_change_golden(self):
        outputs, _ = journey()
        self.assertTrue(outputs[-1]['completion_ready'], outputs[-1])
        text = rendered(outputs)
        if os.environ.get('UPDATE_CI_GATE_GOLDEN'):
            GOLDEN.parent.mkdir(parents=True, exist_ok=True)
            GOLDEN.write_text(text, 'utf-8')
        self.assertEqual(text, GOLDEN.read_text('utf-8'))

if __name__ == '__main__':
    unittest.main()
