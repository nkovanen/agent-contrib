"""G-08: a symlink is judged by where it points, not only by its own path, in verify and scope-check."""
import os
import pathlib
import tempfile
import unittest

from agent_contribute import core, workspace
from tests.test_protocol import evidence_checkout, refresh_checkout_evidence


def link(tmp, path, target):
    full = pathlib.Path(tmp, path)
    full.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target, full)


class SymlinkScopeTests(unittest.TestCase):
    def temporary(self):
        directory = tempfile.TemporaryDirectory()  # TestCase.enterContext needs Python 3.11
        self.addCleanup(directory.cleanup)
        return directory.name

    def committed(self, links, extra=()):
        tmp = self.temporary()
        task, client, evidence, git = evidence_checkout(tmp)
        for path, target in links:
            link(tmp, path, target)
        for path in extra:
            pathlib.Path(tmp, path).parent.mkdir(parents=True, exist_ok=True)
            pathlib.Path(tmp, path).write_text('content')
        git('add', '-A')
        git('commit', '-q', '-m', 'links')
        refresh_checkout_evidence(evidence, git)
        return tmp, task, client, evidence

    def violations(self, tmp, task):
        return {item['path']: item['rule'] for item in workspace.scope_check(task, tmp)['violations']}

    def test_links_pointing_outside_the_repository_or_scope_are_violations(self):
        cases = {'src/host': ('/etc/hostname', 'symlink target is absolute: /etc/hostname'),
                 'src/agents': ('../AGENTS.md', 'symlink to AGENTS.md: not in allowed_paths'),
                 'src/up': ('../../outside', 'symlink target escapes the repository: ../../outside'),
                 'src/deep/up': ('../../../x', 'symlink target escapes the repository: ../../../x'),
                 'src/win': ('..\\AGENTS.md', 'symlink target uses a backslash (Windows-style): ..\\AGENTS.md'),
                 'src/drive': ('C:/Windows/x.dll', 'symlink target is absolute: C:/Windows/x.dll'),
                 'src/ci': ('../.github/ci.yml', 'symlink to .github/ci.yml: prohibited_paths: .github/**'),
                 'src/root': ('..', 'symlink to the repository root'),
                 'src/empty-dot': ('.', 'symlink to src: not in allowed_paths')}
        tmp, task, client, evidence = self.committed([(path, target) for path, (target, _) in cases.items()])
        self.assertEqual(self.violations(tmp, task), {path: rule for path, (_, rule) in cases.items()})
        errors = core.verify(task, evidence, tmp, client)['evidence_errors']
        for path, (_, rule) in cases.items():
            with self.subTest(path=path):
                self.assertIn(f'Implementation adds a symlink outside reviewed scope: {path} ({rule})', errors)

    def test_links_to_allowed_files_pass(self):
        tmp, task, client, evidence = self.committed(
            [('src/ok', 'thumb.rs'), ('src/nested/ok', '../thumb.rs'), ('src/hop', 'ok'), ('src/dotted', './thumb.rs')])
        self.assertEqual(self.violations(tmp, task), {})
        result = core.verify(task, evidence, tmp, client)
        self.assertTrue(result['evidence_valid'], result['evidence_errors'])

    def test_chains_and_directory_links_resolve_through_every_hop(self):
        tmp, task, client, evidence = self.committed([
            ('src/a', 'b'), ('src/b', '../AGENTS.md'),           # file chain leaving scope
            ('src/dir', '..'), ('src/through', 'dir/AGENTS.md'),  # through a directory link
            ('src/l1', 'l2'), ('src/l2', 'l1'),                   # loop
            ('src/c1', 'c2'), ('src/c2', 'thumb.rs')])            # chain staying in scope
        found = self.violations(tmp, task)
        self.assertEqual(found['src/a'], 'symlink to AGENTS.md: not in allowed_paths')
        self.assertEqual(found['src/through'], 'symlink to AGENTS.md: not in allowed_paths')
        self.assertEqual(found['src/l1'], 'symlink target has too many levels of links: l2')
        self.assertNotIn('src/c1', found)
        self.assertNotIn('src/c2', found)

    def test_scope_check_also_judges_staged_and_untracked_links(self):
        tmp = self.temporary()
        task, _, _, git = evidence_checkout(tmp)
        link(tmp, 'src/staged', '../AGENTS.md')
        git('add', 'src/staged')
        link(tmp, 'src/untracked', '/etc/passwd')
        link(tmp, 'src/fine', 'thumb.rs')
        found = self.violations(tmp, task)
        self.assertEqual(found, {'src/staged': 'symlink to AGENTS.md: not in allowed_paths',
                                 'src/untracked': 'symlink target is absolute: /etc/passwd'})

    def test_a_file_turned_into_a_link_and_a_deleted_link(self):
        tmp, task, client, evidence = self.committed([('src/gone', 'thumb.rs')])
        base = evidence['git_head']
        task['source']['commit'] = base
        git = lambda *args: core.git_read(tmp, *args)  # noqa: E731 - read-only helper
        pathlib.Path(tmp, 'src/gone').unlink()
        pathlib.Path(tmp, 'src/thumb.rs').unlink()
        link(tmp, 'src/thumb.rs', '../AGENTS.md')
        import subprocess
        subprocess.run(['git', '-C', tmp, 'add', '-A'], check=True)
        subprocess.run(['git', '-C', tmp, '-c', 'user.name=T', '-c', 'user.email=t@e', 'commit', '-q', '-m', 'swap'],
                       check=True)
        self.assertEqual(git('rev-parse', 'HEAD') != base, True)
        self.assertEqual(self.violations(tmp, task), {'src/thumb.rs': 'symlink to AGENTS.md: not in allowed_paths'})

    def test_link_chains_stop_after_40_hops(self):
        chain = [(f'src/k{n}', f'k{n + 1}') for n in range(40)] + [('src/k40', 'thumb.rs')]
        tmp, task, client, evidence = self.committed(chain)
        found = self.violations(tmp, task)
        self.assertEqual(found, {'src/k0': 'symlink target has too many levels of links: k1'})  # 41 links
        self.assertNotIn('src/k1', found)  # 40 links still resolve

    def test_oversized_link_blob_fails_closed(self):
        import subprocess
        tmp = self.temporary()
        task, _, _, git = evidence_checkout(tmp)
        blob = subprocess.run(['git', '-C', tmp, 'hash-object', '-w', '--stdin'], input='a/' * 2500,
                              capture_output=True, text=True, check=True).stdout.strip()
        git('update-index', '--add', '--cacheinfo', f'120000,{blob},src/long')
        git('commit', '-q', '-m', 'long link')
        self.assertEqual(self.violations(tmp, task)['src/long'], 'symlink target is longer than 4096 bytes')

    def test_writing_through_a_linked_directory_is_judged_at_the_real_path(self):
        # Git records no path beyond a symlink, so a file written through src/docs lands at docs/... and is judged there.
        tmp, task, client, evidence = self.committed([('src/docs', '../docs')], extra=['docs/keep.md'])
        pathlib.Path(tmp, 'src/docs/new.md').write_text('written through the link')
        found = self.violations(tmp, task)
        self.assertEqual(found['docs/new.md'], 'not in allowed_paths')
        self.assertEqual(found['src/docs'], 'symlink to docs: not in allowed_paths')
        self.assertNotIn('src/docs/new.md', workspace.scope_check(task, tmp)['changed_paths'])


if __name__ == '__main__':
    unittest.main()
