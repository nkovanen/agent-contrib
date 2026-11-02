# Releasing

A maintainer runbook for a release such as v0.3.0. Each step names its
verification. Steps that publish (merge, push a tag, create a GitHub release,
upload to PyPI) need the maintainer's explicit decision at that step; nothing
here is automatic. PyPI publishing (#26) is optional and stays off until a
maintainer adopts the proposed workflow.

## 0. Preconditions

- **Trunk is ready.** The candidate branch has passed its independent review.
  The acceptance gate in [development status](development-status.md) is met,
  and no Critical or High finding is open.
- **CI is green on the exact commit to release.** That means the unit tests on
  every Python in `.github/workflows/ci.yml` plus the standalone package check.
- **Your local checkout passes:**

  ```sh
  python -m unittest discover -v
  python tools/check_install.py
  python tools/release_check.py
  ```

  `release_check.py` confirms that every statement of the version agrees:
  `pyproject.toml`, `__version__`, the first CHANGELOG heading, the installed
  workflow, `check_install.py` and the version-asserting tests. It reads files
  only.

## 1. Version

The version is already in every source (`release_check.py` passes). To release
a different version, change all of these in one commit, then rerun the check:

- `pyproject.toml` `version`;
- `agent_contribute/__init__.py`;
- the first line and the "CLI/library version" line of
  `agent_contribute/instructions.md`;
- the expectations in `tools/check_install.py`;
- the two version assertions in `tests/test_protocol.py`.

The task, evidence, host-context and output schema versions are independent of
the CLI version; never change them as part of a release.

## 2. Finalise the CHANGELOG and docs

1. Replace `## X.Y.Z — unreleased` with the release date,
   `## X.Y.Z — YYYY-MM-DD`. Check that every user-visible change since the last
   release is listed, including each schema 0.1 compatibility note.
2. Find the remaining "unreleased" and "candidate" wording:

   ```sh
   grep -rn "unreleased\|candidate\|no v[0-9.]* tag" README.md docs/ agent_contribute/*.md
   ```

   Update it: README status and install instructions,
   `docs/installation.md`, `docs/development-status.md`,
   `docs/product-map.md`, and the instructions' install paragraph. Leave
   design-document history alone.
3. Verify: `python tools/release_check.py --release` passes, because it now
   requires the dated heading. Rerun the full suite and `tools/check_install.py`.

## 3. Merge

Open a PR with steps 1 and 2 to `main`. It needs a review and a green CI. Merge
only with the maintainer's explicit approval, then wait for CI on the merge
commit of `main`.

## 4. Tag

Tag the merge commit on `main`, nothing else. Use an annotated tag, signed when
the maintainer has a signing key:

```sh
git fetch origin main
git switch --detach origin/main
python tools/release_check.py --release --tag vX.Y.Z
git tag -s vX.Y.Z -m "agent-contrib X.Y.Z"   # or -a without a key
git tag -v vX.Y.Z                            # signed tags only
git push origin vX.Y.Z                       # needs explicit authorization
```

Verify: `git ls-remote origin refs/tags/vX.Y.Z` names the tag object, and that
object dereferences to the merge commit you tested.

## 5. GitHub release

Create the release from the tag with the CHANGELOG section as its notes. Attach
no locally built files: if PyPI publishing is adopted, the workflow builds the
distributions.

```sh
gh release create vX.Y.Z --verify-tag --title "agent-contrib X.Y.Z" --notes-file notes.md
```

`notes.md` is the dated CHANGELOG section for this release. Verify the release
page names the right tag and commit, then install from the tag in a clean
virtual environment:

```sh
python -m pip install "git+https://github.com/nkovanen/agent-contrib@vX.Y.Z"
agent-contrib --version   # prints X.Y.Z
```

## 6. Optional: PyPI with trusted publishing and provenance (#26)

Publishing to PyPI is a separate maintainer decision. The proposed workflow is
[docs/examples/release-pypi.yml](examples/release-pypi.yml). It is inert until
a maintainer copies it to `.github/workflows/release-pypi.yml` unchanged (a
test keeps an adopted copy identical to the example).

**What it does:**

- It triggers only on a **published** GitHub release.
- **Build job** (`contents: read`):
  - checks that the tag is `vX.Y.Z` for the packaged version and that the
    CHANGELOG heading is dated;
  - runs the test suite;
  - builds the sdist and wheel once, with a pinned `build` frontend.
- **Publish job**, the only job with `id-token: write` and
  `attestations: write`, in the protected `pypi` environment:
  - downloads those exact files;
  - attests their build provenance with `actions/attest-build-provenance`;
  - publishes them with `pypa/gh-action-pypi-publish` using OIDC trusted
    publishing.
- No secret or API token exists anywhere.
- The provenance attestation runs in the publish job so `id-token: write`
  never reaches the job that runs the test suite and the build.

**One-time setup, before the first publishing release:**

1. **PyPI:** add a trusted publisher for project `agent-contrib`, or a
   *pending* publisher while the project does not exist yet. Set owner
   `nkovanen`, repository `agent-contrib`, workflow `release-pypi.yml` and
   environment `pypi`.
2. **GitHub:** create the environment `pypi`. Require a maintainer as
   reviewer, prevent self-review where available, and allow deployments only
   from tags matching `v*`.
3. **Re-check every action pin in the example.** Each `uses:` must be the
   commit that the action's canonical release tag points to:
   `gh api repos/OWNER/ACTION/git/ref/tags/TAG`, and for an annotated tag
   dereference it with `git/tags/SHA`. A SHA that exists only in a fork is not
   acceptable. Update the pins and their version comments in the example, and
   copy the reviewed example in the same PR.
4. Merge that PR with the maintainer's approval. The release workflow then
   needs `tests/test_release_workflow_lint.py` to pass on the release commit.

**Publishing:** publishing the GitHub release in step 5 starts the workflow.
Approve the `pypi` environment deployment only after the build job has passed.

**Verify after publishing:**

```sh
python -m venv /tmp/ac-verify && /tmp/ac-verify/bin/python -m pip install agent-contrib==X.Y.Z
/tmp/ac-verify/bin/agent-contrib --version          # prints X.Y.Z
python -m pip download --no-deps agent-contrib==X.Y.Z -d /tmp/ac-dist
gh attestation verify /tmp/ac-dist/* --repo nkovanen/agent-contrib
```

The PyPI file pages also show the trusted-publisher provenance for each file.

**Residual risk.** The build frontend is pinned by version. Its dependencies and
the isolated build backend (`setuptools>=77`) are resolved from PyPI at build
time without hash pinning. The attestation records which workflow run built
the files, not that those inputs were the expected ones. Hash-pinned build
requirements are a possible follow-up.

## 7. Rollback

- **Before the tag is pushed:** delete the local tag (`git tag -d vX.Y.Z`) and
  fix forward on `main`.
- **Tag pushed, no release yet:** with the maintainer's authorization, delete it
  (`git push origin :refs/tags/vX.Y.Z`). Never move a published tag to another
  commit; tag a new version instead.
- **GitHub release created, PyPI not used:** edit the release back to draft or
  delete it, then delete the tag as above. Anyone who installed from the tag
  keeps that commit, so state the withdrawal in the release notes of the fix.
- **Published to PyPI:** a PyPI version can never be re-uploaded or replaced.
  Yank it on PyPI with a reason. A yanked version is skipped unless pinned
  exactly. Then release a fixed `X.Y.(Z+1)` through the same steps. Never reuse
  a version number. Attestations of the yanked files remain and stay valid for
  those exact files.
- **The workflow failed before publishing:** nothing reached PyPI.
  - If the cause was setup only (trusted publisher or environment), fix it and
    re-run the failed run from the Actions page. It rebuilds the same tagged
    commit.
  - If the release commit itself is wrong, do not move the tag. Mark the GitHub
    release as withdrawn and release `X.Y.(Z+1)` from step 1.
  - A failed run never retries on its own, and the workflow has no manual
    trigger.
