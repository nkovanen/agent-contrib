"""Checkout config can never make a hardened read run a program or fetch (G-01, R6-01).

Every attack writes a marker if its program runs; the marker must never appear.
"""
import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from agent_contribute import core, workspace
from tests import test_lifecycle
from tests.test_protocol import evidence_checkout


def marker_script(directory, name):
    marker = pathlib.Path(directory, name + '_RAN')
    script = pathlib.Path(directory, name + '.sh')
    script.write_text(f'#!/bin/sh\ntouch {marker}\ncat\n')
    script.chmod(0o755)
    return script, marker


def filter_attack(root, git, outside):
    script, marker = marker_script(outside, 'filter')
    pathlib.Path(root, '.git', 'info').mkdir(exist_ok=True)
    pathlib.Path(root, '.git', 'info', 'attributes').write_text('* filter=x\n')
    git('config', 'filter.x.clean', str(script))
    os.utime(pathlib.Path(root, 'AGENTS.md'), (978307200, 978307200))  # stat-dirty: status would run the filter
    return marker, 'filter.x.clean'


def included_filter_attack(root, git, outside):
    script, marker = marker_script(outside, 'included')
    pathlib.Path(root, '.git', 'info').mkdir(exist_ok=True)
    pathlib.Path(root, '.git', 'info', 'attributes').write_text('* filter=y\n')
    included = pathlib.Path(outside, 'included.cfg')
    included.write_text(f'[filter "y"]\n\tclean = {script}\n')
    git('config', f'includeIf.gitdir:{pathlib.Path(root).resolve()}/.git.path', str(included))
    os.utime(pathlib.Path(root, 'AGENTS.md'), (978307200, 978307200))
    return marker, 'filter.y.clean'


def gpg_attack(root, git, outside):
    script, marker = marker_script(outside, 'gpg')
    git('config', 'log.showSignature', 'true')
    git('config', 'gpg.program', str(script))
    return marker, 'gpg.program'


def promisor_attack(root, git, outside):
    script, marker = marker_script(outside, 'transport')
    git('config', 'core.repositoryformatversion', '1')
    git('config', 'extensions.partialClone', 'trap')
    git('config', 'remote.trap.promisor', 'true')
    git('config', 'remote.trap.url', 'ext::' + str(script))
    git('config', 'protocol.ext.allow', 'always')
    return marker, 'extensions.partialclone'


ATTACKS = {'filter': filter_attack, 'includeIf filter': included_filter_attack, 'gpg': gpg_attack,
           'promisor': promisor_attack}


def refusal(key):
    return (f'Checkout Git config sets {key}, which a read could run as a program or use to hide changes; '
            'remove it or use a fresh clone')


class LegacyConfigSafetyTests(unittest.TestCase):
    def test_no_configured_program_runs_and_every_gate_refuses(self):
        for name, attack in ATTACKS.items():
            with self.subTest(attack=name), tempfile.TemporaryDirectory() as root, \
                    tempfile.TemporaryDirectory() as outside:
                task, client, evidence, git = evidence_checkout(root)
                marker, key = attack(root, git, outside)
                absent = dict(evidence, base_commit='f' * 40)  # an absent object would trigger a lazy fetch
                result = core.verify(task, absent, root, client)
                self.assertIn(refusal(key), result['evidence_errors'])
                self.assertFalse(result['upstream_submission_ready'])
                scope = workspace.scope_check(task, root, 'f' * 40)
                self.assertEqual(scope['errors'], [refusal(key)])
                with self.assertRaises(core.ProtocolError) as caught:
                    workspace.evidence_skeleton(task, root, evidence['base_commit'])
                self.assertEqual((caught.exception.code, str(caught.exception)), ('unsafe_git_config', refusal(key)))
                self.assertFalse(marker.exists(), name + ' program ran')

    def test_signature_display_is_disabled_for_every_read(self):
        # log.showSignature alone (no program key to refuse) must not run the gpg found on PATH.
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            task, client, evidence, git = evidence_checkout(root)
            script, marker = marker_script(outside, 'gpg')
            pathlib.Path(outside, 'gpg').symlink_to(script)
            raw = git('cat-file', 'commit', 'HEAD').split('\n')
            at = next(i for i, line in enumerate(raw) if line.startswith('committer ')) + 1
            raw[at:at] = ['gpgsig -----BEGIN PGP SIGNATURE-----', ' AAAA', ' -----END PGP SIGNATURE-----']
            signed = subprocess.run(['git', '-C', root, 'hash-object', '-t', 'commit', '-w', '--stdin'],
                                    input='\n'.join(raw) + '\n', capture_output=True, text=True, check=True).stdout.strip()
            git('update-ref', git('symbolic-ref', 'HEAD'), signed)
            git('config', 'log.showSignature', 'true')
            with patch.dict(os.environ, {'PATH': outside + os.pathsep + os.environ['PATH']}):
                core.verify(task, evidence, root, client)
                workspace.scope_check(task, root)
                workspace.evidence_skeleton(task, root, evidence['base_commit'])
            self.assertFalse(marker.exists(), 'gpg ran for a signed HEAD')

    def test_hardened_read_never_lazy_fetches_a_missing_object(self):
        # Direct git_read boundary check: a promisor remote that has the object is never contacted.
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as root:
            _, _, _, git_source = evidence_checkout(source)
            missing = git_source('rev-parse', 'HEAD')
            subprocess.run(['git', 'init', '-q', root], check=True)
            for key, value in [('core.repositoryformatversion', '1'), ('extensions.partialClone', 'origin'),
                               ('remote.origin.promisor', 'true'), ('remote.origin.url', 'file://' + source)]:
                subprocess.run(['git', '-C', root, 'config', key, value], check=True)
            with self.assertRaises(core.ProtocolError):
                core.git_read(root, 'cat-file', '-t', missing)

    def test_ordinary_local_config_is_accepted(self):
        with tempfile.TemporaryDirectory() as root:
            task, client, evidence, git = evidence_checkout(root)
            git('config', 'user.name', 'Someone')
            git('config', 'diff.renames', 'false')
            git('config', 'remote.origin.fetch', '+refs/heads/*:refs/remotes/origin/*')
            self.assertTrue(core.verify(task, evidence, root, client)['evidence_valid'])
            self.assertTrue(workspace.scope_check(task, root)['within_scope'])


class EnvironmentTests(unittest.TestCase):
    def test_every_read_ignores_system_attributes_and_cannot_fetch(self):
        # G-19: /etc/gitattributes (or $(prefix)/etc/gitattributes) must not shape any read.
        with tempfile.TemporaryDirectory() as root:
            evidence_checkout(root)
            with patch.object(core.subprocess, 'run', wraps=core.subprocess.run) as run:
                core.git_read(root, 'rev-parse', 'HEAD')
            env = run.call_args.kwargs['env']
            self.assertEqual((env['GIT_ATTR_NOSYSTEM'], env['GIT_NO_LAZY_FETCH'], env['GIT_CONFIG_NOSYSTEM']),
                             ('1', '1', '1'))


class SubmoduleConfigTests(unittest.TestCase):
    # G-12: a populated submodule's own config must never run, whatever the superproject config says.
    def populated_submodule(self, root, git, outside):
        script, marker = marker_script(outside, 'submodule_filter')
        sub = pathlib.Path(root, 'src', 'sub')
        sub.mkdir()
        inner = lambda *argv: subprocess.run(['git', '-C', str(sub), '-c', 'user.name=T', '-c', 'user.email=t@e',
                                              *argv], check=True, capture_output=True)
        inner('init', '-q')
        pathlib.Path(sub, 'a').write_text('a')
        inner('add', 'a')
        inner('commit', '-q', '-m', 'sub')
        pathlib.Path(sub, '.git', 'info').mkdir(exist_ok=True)
        pathlib.Path(sub, '.git', 'info', 'attributes').write_text('* filter=x\n')
        inner('config', 'filter.x.clean', str(script))
        os.utime(pathlib.Path(sub, 'a'), (978307200, 978307200))
        git('add', 'src/sub')
        return marker

    def test_no_gate_runs_a_submodule_program(self):
        gitlink = 'Submodule/gitlink evidence is unsupported; no submodule commands were run'
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            task, client, evidence, git = evidence_checkout(root)
            marker = self.populated_submodule(root, git, outside)
            self.assertEqual(workspace.scope_check(task, root)['errors'], [gitlink])
            self.assertFalse(marker.exists(), 'scope-check ran the submodule filter')
            self.assertIn(gitlink, core.verify(task, evidence, root, client)['evidence_errors'])
            with self.assertRaises(core.ProtocolError):
                workspace.evidence_skeleton(task, root, evidence['base_commit'])
            self.assertFalse(marker.exists(), 'a gate ran the submodule filter')


class CandidateConfigSafetyTests(unittest.TestCase):
    setUp = test_lifecycle.LifecycleTests.setUp
    verify = test_lifecycle.LifecycleTests.verify

    def test_schema_02_refuses_unsafe_config_without_running_it(self):
        self.assertTrue(self.verify()['draft_create_ready'])
        with tempfile.TemporaryDirectory() as outside:
            marker, key = filter_attack(self.directory.name, self.git, outside)
            result = self.verify()
            self.assertIn(refusal(key), result['evidence_errors'])
            self.assertFalse(result['technical_evidence_valid'])
            self.assertFalse(marker.exists())


if __name__ == '__main__':
    unittest.main()
