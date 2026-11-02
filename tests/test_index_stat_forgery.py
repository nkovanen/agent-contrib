"""A forged stat cache in the checkout's index cannot hide an edit (G-14): worktree content is judged
against a commit with a fresh temporary index outside the checkout."""
import hashlib
import os
import pathlib
import struct
import tempfile
import time
import unittest
from unittest.mock import patch

from agent_contribute import core, workspace
from tests.test_protocol import evidence_checkout

DIRTY = 'Current checkout is dirty or differs from evidence HEAD/tree'


def forge_stat(index_path, name, worktree_file):
    """Copy the worktree file's stat fields into its index v2/v3 entry, keep the old blob ID, fix the checksum."""
    data = bytearray(pathlib.Path(index_path).read_bytes())
    version, count = struct.unpack('>II', data[4:12])
    offset = 12
    for _ in range(count):
        flags = struct.unpack('>H', data[offset + 60:offset + 62])[0]
        start = offset + 62 + (2 if version >= 3 and flags & 0x4000 else 0)
        end = data.index(b'\0', start)
        if bytes(data[start:end]) == name.encode():
            st = os.lstat(worktree_file)
            mode = struct.unpack('>I', data[offset + 24:offset + 28])[0]
            struct.pack_into('>IIIIIIIIII', data, offset, int(st.st_ctime), st.st_ctime_ns % 10**9, int(st.st_mtime),
                             st.st_mtime_ns % 10**9, st.st_dev & 0xffffffff, st.st_ino & 0xffffffff, mode,
                             st.st_uid, st.st_gid, st.st_size)
        offset += (end - offset + 1 + 7) // 8 * 8
    data[-20:] = hashlib.sha1(bytes(data[:-20])).digest()
    pathlib.Path(index_path).write_bytes(bytes(data))


class IndexStatForgeryTests(unittest.TestCase):
    def test_forged_index_stat_cannot_hide_an_edit(self):
        with tempfile.TemporaryDirectory() as root:
            task, client, evidence, git = evidence_checkout(root)
            agents = pathlib.Path(root, 'AGENTS.md')
            agents.write_text('EVIL instructions of a different size')
            index = pathlib.Path(root, '.git', 'index')
            forge_stat(index, 'AGENTS.md', agents)
            time.sleep(1.2)
            os.utime(index)  # newer than the file, so Git trusts the forged entry
            self.assertEqual(git('status', '--porcelain'), '', 'precondition: the forged cache hides the edit')
            result = core.verify(task, evidence, root, client)
            self.assertIn(DIRTY, result['evidence_errors'])
            self.assertFalse(result['upstream_submission_ready'])
            scope = workspace.scope_check(task, root)
            self.assertIn('AGENTS.md', [v['path'] for v in scope['violations']])
            self.assertIs(workspace.evidence_skeleton(task, root, evidence['base_commit'])['worktree_clean'], False)
            self.assertEqual(git('status', '--porcelain'), '', 'the checkout index is never rewritten')

    def test_clean_checkout_stays_clean_and_leaves_nothing_behind(self):
        with tempfile.TemporaryDirectory() as root:
            task, client, evidence, git = evidence_checkout(root)
            with tempfile.TemporaryDirectory() as scratch, patch.object(tempfile, 'tempdir', scratch):
                self.assertTrue(core.verify(task, evidence, root, client)['evidence_valid'])
                self.assertTrue(workspace.scope_check(task, root)['within_scope'])
                self.assertEqual(core.worktree_changes(root, evidence['git_head']), set())
                self.assertEqual(os.listdir(scratch), [], 'temporary index not cleaned up')
            self.assertEqual(sorted(p.name for p in pathlib.Path(root, '.git').iterdir() if p.name.startswith('index')),
                             ['index'])


if __name__ == '__main__':
    unittest.main()
