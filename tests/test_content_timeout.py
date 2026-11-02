"""Hashing a large checkout gets a size-scaled timeout and a specific error when it runs out (G-16)."""
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import core, workspace
from tests.test_protocol import evidence_checkout


def slow_content_read(seen):
    """subprocess.run that times out only for the fresh-index status, recording each Git timeout."""
    real = subprocess.run

    def run(argv, **options):
        if '--no-optional-locks' not in argv:  # not a hardened read (e.g. the fixture's own git calls)
            return real(argv, **options)
        seen.append((argv, options['timeout']))
        if 'status' in argv and 'GIT_INDEX_FILE' in options.get('env', {}):
            raise subprocess.TimeoutExpired(argv, options['timeout'])
        return real(argv, **options)
    return run


class ContentTimeoutTests(unittest.TestCase):
    def test_budget_scales_with_tracked_bytes_within_bounds(self):
        self.assertEqual(core.content_timeout(0), core.CONTENT_TIMEOUT_FLOOR)
        self.assertGreater(core.content_timeout(2 * 1024 ** 3), core.content_timeout(1024 ** 3))
        self.assertGreater(core.content_timeout(1024 ** 3), core.CONTENT_TIMEOUT_FLOOR)
        self.assertEqual(core.content_timeout(10 ** 15), core.CONTENT_TIMEOUT_CEILING)

    def test_timeout_names_the_cause_and_tracked_size_in_every_gate(self):
        with tempfile.TemporaryDirectory() as root:
            task, client, evidence, git = evidence_checkout(root)
            tracked = lambda rev: sum(int(line.split()[3]) for line in git('ls-tree', '-r', '-l', rev).splitlines())
            message = lambda size: (f'Hashing {size} tracked bytes did not finish within {core.content_timeout(size)} '
                                    's; the checkout is too large for the content check')
            size = tracked('HEAD')
            expected = message(size)
            seen = []
            with patch.object(core.subprocess, 'run', side_effect=slow_content_read(seen)):
                self.assertIn(expected, core.verify(task, evidence, root, client)['evidence_errors'])
                # scope-check hashes the worktree against the base commit, so it reports the base's size.
                self.assertEqual(workspace.scope_check(task, root)['errors'], [message(tracked(evidence['base_commit']))])
                with self.assertRaises(core.ProtocolError) as caught:
                    workspace.evidence_skeleton(task, root, evidence['base_commit'])
            self.assertEqual((caught.exception.code, str(caught.exception)), ('checkout_too_large_for_timeout', expected))
            content = [timeout for argv, timeout in seen if 'status' in argv and '--untracked-files=no' in argv]
            self.assertEqual(set(content), {core.content_timeout(size), core.content_timeout(tracked(evidence['base_commit']))})
            self.assertTrue(all(timeout == 15 for argv, timeout in seen if 'status' not in argv),
                            'other reads keep the fixed timeout')

    def test_ordinary_timeouts_keep_their_generic_error(self):
        with tempfile.TemporaryDirectory() as root:
            evidence_checkout(root)
            with patch.object(core.subprocess, 'run', side_effect=subprocess.TimeoutExpired(['git'], 15)):
                with self.assertRaises(core.ProtocolError) as caught:
                    core.git_read(root, 'rev-parse', 'HEAD')
            self.assertEqual(str(caught.exception), 'Could not inspect evidence checkout')


if __name__ == '__main__':
    unittest.main()
