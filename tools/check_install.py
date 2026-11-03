"""Build both distributions and smoke-test clean installs outside the checkout.

Run with a Python >=3.10 environment containing pip and build:
    python tools/check_install.py
Only build dependency installation uses the network. Wheel installs and smoke
checks use no index, GitHub credentials, git, or gh.
"""
import argparse
import hashlib
import importlib.metadata
import importlib.resources
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import venv


RESOURCE_PATHS = (
    "task.schema.json",
    "receipt.schema.json",
    "tipjar.schema.json",
    "evidence.schema.json",
    "schemas/0.2/task.schema.json",
    "schemas/0.2/evidence.schema.json",
    "schemas/host-context/0.1.schema.json",
    "schemas/host-context/0.2.schema.json",
    "instructions.md",
    "adapters/agent-contribute/SKILL.md",
    "schemas/output/1/audit.schema.json",
    "schemas/output/1/authorization-request.schema.json",
    "schemas/output/1/dependencies.schema.json",
    "schemas/output/1/discover.schema.json",
    "schemas/output/1/drift.schema.json",
    "schemas/output/1/error.schema.json",
    "schemas/output/1/evidence-init.schema.json",
    "schemas/output/1/feedback.schema.json",
    "schemas/output/1/find.schema.json",
    "schemas/output/1/impact.schema.json",
    "schemas/output/1/init.schema.json",
    "schemas/output/1/inspect.schema.json",
    "schemas/output/1/instructions.schema.json",
    "schemas/output/1/jar-check.schema.json",
    "schemas/output/1/jar.schema.json",
    "schemas/output/1/lint.schema.json",
    "schemas/output/1/ownership.schema.json",
    "schemas/output/1/pr-body.schema.json",
    "schemas/output/1/prepare.schema.json",
    "schemas/output/1/receipt.schema.json",
    "schemas/output/1/scope-check.schema.json",
    "schemas/output/1/session.schema.json",
    "schemas/output/1/skill.schema.json",
    "schemas/output/1/verify.schema.json",
    "schemas/output/2/card.schema.json",
    "schemas/output/2/audit.schema.json",
    "schemas/output/2/authorization-request.schema.json",
    "schemas/output/2/dependencies.schema.json",
    "schemas/output/2/discover.schema.json",
    "schemas/output/2/drift.schema.json",
    "schemas/output/2/error.schema.json",
    "schemas/output/2/evidence-init.schema.json",
    "schemas/output/2/feedback.schema.json",
    "schemas/output/2/find.schema.json",
    "schemas/output/2/impact.schema.json",
    "schemas/output/2/init.schema.json",
    "schemas/output/2/inspect.schema.json",
    "schemas/output/2/instructions.schema.json",
    "schemas/output/2/jar-check.schema.json",
    "schemas/output/2/jar.schema.json",
    "schemas/output/2/lint.schema.json",
    "schemas/output/2/ownership.schema.json",
    "schemas/output/2/pr-body.schema.json",
    "schemas/output/2/prepare.schema.json",
    "schemas/output/2/receipt.schema.json",
    "schemas/output/2/scope-check.schema.json",
    "schemas/output/2/session.schema.json",
    "schemas/output/2/skill.schema.json",
    "schemas/output/2/verify.schema.json",
)


def run(argv, *, cwd, env, expected=0):
    result = subprocess.run([str(arg) for arg in argv], cwd=cwd, env=env,
                            capture_output=True, text=True, timeout=300)
    if result.returncode != expected:
        raise RuntimeError(f"{argv!r} exited {result.returncode}, expected {expected}\n"
                           f"{result.stdout}\n{result.stderr}")
    return result.stdout


def installed_check(source):
    from agent_contribute import __version__, core
    import agent_contribute

    assert sys.prefix != sys.base_prefix, "Smoke checks require a clean virtualenv"
    assert Path(agent_contribute.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
    assert not Path.cwd().is_relative_to(source), "Smoke checks must run outside the checkout"
    assert __version__ == importlib.metadata.version("agent-contrib") == "0.3.0"
    assert core.VERSION == "0.1"
    dist = importlib.metadata.distribution("agent-contrib")
    assert dist.metadata["Requires-Python"] == ">=3.10"
    assert not dist.requires, "Runtime dependencies must remain empty"
    assert dist.metadata["License-Expression"] == "MIT"
    assert dist.metadata.get_payload().strip() == (source / "README.md").read_text("utf-8").strip()
    urls = dict(value.split(", ", 1) for value in dist.metadata.get_all("Project-URL"))
    assert urls == {
        "Homepage": "https://github.com/nkovanen/agent-contrib",
        "Repository": "https://github.com/nkovanen/agent-contrib",
        "Issues": "https://github.com/nkovanen/agent-contrib/issues",
    }
    for name in ("LICENSE", "NOTICE"):
        matches = [file for file in dist.files if str(file).endswith("/licenses/" + name)]
        assert len(matches) == 1, f"Missing or duplicate license file: {name}"
        assert dist.locate_file(matches[0]).read_bytes() == (source / name).read_bytes()

    resources = importlib.resources.files("agent_contribute")
    for name in RESOURCE_PATHS:
        assert resources.joinpath(name).read_bytes() == (source / "agent_contribute" / name).read_bytes(), name
    assert not resources.joinpath("schemas/output/1/card.schema.json").is_file(), "Card starts at output2"
    # Development tools such as the task-selection benchmark never ship in the wheel.
    assert not [str(file) for file in dist.files if str(file).startswith("web/") or str(file).startswith("tests/web/")]
    assert not [str(file) for file in dist.files if str(file).startswith("tools/") or "benchmark" in str(file)]
    assert [str(file) for file in dist.files if file.name == "SKILL.md"] == [
        "agent_contribute/adapters/agent-contribute/SKILL.md"]
    for name in ("task", "evidence"):
        schema = core.bundled_schema(name)
        assert schema["properties"]["schema_version"]["const"] == "0.1"
        errors = core.schema_errors({"schema_version": "999"}, schema)
        assert "$.schema_version: wrong constant or version" in errors
    for name in ("task", "evidence"):
        schema = core.bundled_schema(name, version="0.2")
        assert schema["properties"]["schema_version"]["const"] == "0.2"
        assert core.schema_errors({"schema_version": "999"}, schema)
    host_schema = json.loads(resources.joinpath("schemas/host-context/0.1.schema.json").read_text("utf-8"))
    assert host_schema["properties"]["schema_version"]["const"] == "0.1"
    assert core.schema_errors({"schema_version": "999"}, host_schema)
    host_schema_02 = core.bundled_schema("host-context", "0.2")
    assert host_schema_02["properties"]["schema_version"]["const"] == "0.2"
    assert "overlap_dispositions" in host_schema_02["properties"]
    assert "overlap_dispositions" not in host_schema["properties"]
    assert core.check_evidence({}, {"schema_version": "999"}, None, "")

    # Restrict PATH so accidental GitHub or git calls cannot make smoke checks pass.
    scripts = Path(sys.executable).parent
    env = {**os.environ, "PATH": str(scripts)}
    console = scripts / ("agent-contrib.exe" if os.name == "nt" else "agent-contrib")
    tipjar = scripts / ("tipjar.exe" if os.name == "nt" else "tipjar")
    def cli(*args, expected=0):
        return run([console, *args], cwd=Path.cwd(), env=env, expected=expected)

    assert cli("--version").strip() == "0.3.0"
    assert run([sys.executable, "-I", "-m", "agent_contribute", "--version"],
               cwd=Path.cwd(), env=env).strip() == "0.3.0"
    instructions = json.loads(cli("instructions"))
    assert instructions["cli_version"] == "0.3.0"
    assert instructions["supported_schema_versions"] == ["0.1", "0.2"]
    assert instructions["supported_host_context_versions"] == ["0.1", "0.2"]
    assert instructions["automatic_updates"] is False
    assert instructions["output_schema_version"] == "2"
    assert json.loads(cli("schema", "verify"))["$id"] == "urn:agent-contrib:output:2:verify"
    assert instructions["workflow_markdown"] == resources.joinpath("instructions.md").read_text("utf-8")
    session_schema = json.loads(cli("schema", "session"))
    discovery_path = Path.cwd() / "discovery.json"
    discovery_path.write_text(json.dumps(json.loads(
        (source / "tests/fixtures/discover/plain.json").read_text("utf-8"))["result"]), encoding="utf-8")
    session_path = Path.cwd() / "session.json"
    proposal = json.loads(cli("session", discovery_path, "--max-tasks", "3", "--minutes", "60",
                              "--output", session_path))
    assert proposal["status"] == "proposed" and proposal["actions_authorized"] is False
    assert not core.schema_errors(proposal, session_schema)
    assert json.loads(session_path.read_text("utf-8")) == proposal
    original_session = session_path.read_bytes()
    cli("session", discovery_path, "--max-tasks", "3", "--minutes", "60", "--output", session_path, expected=1)
    assert session_path.read_bytes() == original_session
    manifest_schema = json.loads(resources.joinpath("tipjar.schema.json").read_text("utf-8"))
    assert manifest_schema["properties"]["schema_version"]["const"] == "0.1"
    assert not core.schema_errors({"schema_version": "0.1", "status": "welcome"}, manifest_schema)
    assert core.schema_errors({"schema_version": "999", "status": "welcome"}, manifest_schema)
    jar_schema = json.loads(cli("schema", "jar"))
    assert jar_schema["$id"] == "urn:agent-contrib:output:2:jar"
    assert "inspection only" in " ".join(cli("jar", "--help").split())
    failed_jar = json.loads(cli("jar", "acme/project", expected=1))
    assert failed_jar["state"] == "unknown" and failed_jar["complete"] is False
    assert failed_jar["manifest"] is None and failed_jar["commit"] is None
    assert not core.schema_errors(failed_jar, jar_schema)

    # Offline maintainer onboarding works without GitHub authentication or tools.
    for state in ('welcome', 'closed'):
        manifest_path = Path.cwd() / ('onboarding-' + state + '.json')
        created = json.loads(run([tipjar, 'init', '--status', state, '--output', manifest_path],
                                 cwd=Path.cwd(), env=env))
        assert created['state'] == state
        assert created['sha256'] == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        assert not core.schema_errors(created, json.loads(cli('schema', 'init')))
        checked = json.loads(run([tipjar, 'jar-check', manifest_path], cwd=Path.cwd(), env=env))
        assert checked['valid'] is True and checked['state'] == state
        assert checked['sha256'] == created['sha256']
        assert not core.schema_errors(checked, json.loads(cli('schema', 'jar-check')))
        assert json.loads(cli('init', '--status', state, '--output', manifest_path,
                              expected=1))['error']['code'] == 'file_error'
    invalid_manifest = Path.cwd() / 'onboarding-invalid.json'
    invalid_manifest.write_bytes(b'\xffPRIVATE')
    invalid = cli('jar-check', invalid_manifest, expected=1)
    assert json.loads(invalid)['error']['code'] == 'invalid_tipjar'
    assert 'PRIVATE' not in invalid
    find_schema = json.loads(cli("schema", "find"))
    assert find_schema["properties"]["format"]["const"] == "find-jars-report/1"
    assert "--owner" in cli("find", "--help")
    failed_find = json.loads(cli("find", expected=1))
    assert failed_find["complete"] is False and failed_find["observations"] == []
    assert failed_find["search"]["total_count"] is None
    assert not core.schema_errors(failed_find, find_schema)

    # The additive alias must use the same workflow and fail-closed gates.
    assert run([tipjar, "--version"], cwd=Path.cwd(), env=env).strip() == "0.3.0"
    assert json.loads(run([tipjar, "instructions"], cwd=Path.cwd(), env=env)) == instructions
    assert "COMMAND" in run([tipjar, "--help"], cwd=Path.cwd(), env=env)
    assert "--owner" in run([tipjar, "find", "--help"], cwd=Path.cwd(), env=env)
    assert json.loads(run([tipjar, "schema", "find"], cwd=Path.cwd(), env=env)) == find_schema
    invalid_find = json.loads(run([tipjar, "--report-budget", "find", "--owner", "a user:bad"],
                                 cwd=Path.cwd(), env=env, expected=2))
    assert invalid_find["error"]["code"] == "usage"

    # Offline dependency discovery must work without git, gh or a package resolver.
    manifest = Path.cwd() / "package.json"
    manifest.write_text('{"dependencies":{"example":"git+https://github.com/example/library.git#v1"}}',
                        encoding="utf-8")
    if hasattr(os, "O_NOFOLLOW") and os.open in os.supports_dir_fd:
        dependency_report = json.loads(run([tipjar, "dependencies", manifest], cwd=Path.cwd(), env=env))
        assert dependency_report["repositories"] == ["example/library"]
        assert dependency_report["dependencies"][0]["revision"] == "v1"
        assert dependency_report["resolution_complete"] is True
        manifest.write_text('{"dependencies":{"ordinary":"^1"}}', encoding="utf-8")
        metadata = Path.cwd() / "node_modules" / "ordinary" / "package.json"
        metadata.parent.mkdir(parents=True)
        metadata.write_text('{"name":"ordinary","version":"1.2.3",'
                            '"repository":{"url":"https://github.com/example/library.git"}}', encoding="utf-8")
        installed_report = json.loads(run([tipjar, "dependencies", manifest, "--installed"],
                                          cwd=Path.cwd(), env=env))
        assert installed_report["repositories"] == ["example/library"]
        observed = installed_report["dependencies"][0]["installed"]
        assert (observed["name"], observed["version"]) == ("ordinary", "1.2.3")
    else:
        refused = json.loads(run([tipjar, "dependencies", manifest], cwd=Path.cwd(), env=env, expected=1))
        assert refused["error"]["code"] == "dependency_input"
    # Exercise the installed receipt parser offline with explicit synthetic public metadata.
    from agent_contribute import receipts
    class ReceiptFixture:
        def request(self, endpoint):
            repo = {"id": 101, "full_name": "acme/photos", "private": False, "visibility": "public"}
            if endpoint == "repos/acme/photos":
                return repo
            assert endpoint == "repos/acme/photos/pulls/30"
            return {"id": 700, "number": 30, "html_url": "https://github.com/acme/photos/pull/30",
                    "state": "open", "draft": True, "merged": False, "merged_at": None,
                    "closed_at": None, "merge_commit_sha": None, "merged_by": None,
                    "user": {"id": 7, "login": "builder", "type": "User"},
                    "head": {"sha": "a" * 40, "ref": "agent/work"},
                    "base": {"sha": "b" * 40, "ref": "main", "repo": repo}}
    recorded = Path.cwd() / "synthetic-receipt.json"
    recorded.write_text(json.dumps(receipts.observe("acme/photos#30", ReceiptFixture())), encoding="utf-8")
    impact = json.loads(run([tipjar, "impact", recorded, recorded], cwd=Path.cwd(), env=env))
    assert impact["unique_prs"] == 1 and impact["counts"] == {"open": 1, "closed": 0, "merged": 0}
    assert impact["repositories_represented"] == 1 and "repositories_helped" not in impact
    assert impact["trust"] == "self-reported recorded observations"
    assert json.loads(cli("schema", "receipt"))["$id"] == "urn:agent-contrib:output:2:receipt"
    assert json.loads(cli("schema", "impact"))["$id"] == "urn:agent-contrib:output:2:impact"

    card = Path.cwd() / "synthetic-card.svg"
    saved = json.loads(run([tipjar, "card", recorded, "--output", card,
                            "--caption", "A personal gift of agent work"], cwd=Path.cwd(), env=env))
    assert saved["sha256"] == hashlib.sha256(card.read_bytes()).hexdigest()
    assert "Personal caption" in card.read_text(encoding="utf-8")
    run([tipjar, "card", recorded, "--output", card], cwd=Path.cwd(), env=env, expected=1)
    assert json.loads(cli("schema", "card"))["$id"] == "urn:agent-contrib:output:2:card"

    # Exercise real installed entry points, including small buffered JSON errors.
    for name, entrypoint in (
            ("console", [console]),
            ("tipjar", [tipjar]),
            ("module", [sys.executable, "-I", "-m", "agent_contribute"])):
        # Every installed spelling exercises the complete new command surface offline.
        def entry(*args, expected=0):
            return json.loads(run([*entrypoint, *args], cwd=Path.cwd(), env=env, expected=expected))
        local_jar = Path.cwd() / f"{name}-jar.json"
        created = entry("init", "--status", "welcome", "--output", local_jar)
        assert entry("jar-check", local_jar)["sha256"] == created["sha256"]
        dependency_args = ("dependencies", manifest)
        if hasattr(os, "O_NOFOLLOW") and os.open in os.supports_dir_fd:
            assert entry(*dependency_args)["resolution_complete"] is False
            assert entry(*dependency_args, "--installed")["repositories"] == ["example/library"]
        else:
            assert entry(*dependency_args, expected=1)["error"]["code"] == "dependency_input"
        assert entry("impact", recorded, recorded)["unique_prs"] == 1
        failed_receipt = Path.cwd() / f"{name}-missing-receipt.json"
        assert "error" in entry("receipt", "acme/photos#30", "--output", failed_receipt, expected=1)
        assert not failed_receipt.exists()
        assert entry("find", expected=1)["complete"] is False
        session_output = Path.cwd() / f"{name}-proposal.json"
        proposal = entry("session", discovery_path, "--max-tasks", "1", "--minutes", "30",
                         "--output", session_output)
        assert proposal["actions_authorized"] is False
        assert not core.schema_errors(proposal, session_schema)
        for args in (("instructions",), ("unknown-command",)):
            reader, writer = os.pipe()
            os.close(reader)
            try:
                result = subprocess.run([str(arg) for arg in [*entrypoint, *args]],
                                        cwd=Path.cwd(), env=env, stdout=writer,
                                        stderr=subprocess.PIPE, timeout=15)
            finally:
                os.close(writer)
            assert result.returncode == 1, (name, args, result.returncode, result.stderr)
            assert result.stderr == b"", (name, args, result.stderr)
            bootstrap = ("import os, sys; os.close(1); "
                         "os.execv(sys.argv[1], sys.argv[1:])")
            result = subprocess.run(
                [sys.executable, "-I", "-c", bootstrap,
                 *[str(arg) for arg in [*entrypoint, *args]]],
                cwd=Path.cwd(), env=env, capture_output=True, timeout=15)
            assert result.returncode == 1, (name, args, result.returncode, result.stderr)
            assert result.stdout == b"", (name, args, result.stdout)
            assert result.stderr == b"", (name, args, result.stderr)
        redirected = Path.cwd() / f"{name}-instructions.json"
        with redirected.open("wb") as output:
            result = subprocess.run([str(arg) for arg in [*entrypoint, "instructions"]],
                                    cwd=Path.cwd(), env=env, stdout=output,
                                    stderr=subprocess.PIPE, timeout=15)
        assert result.returncode == 0, (name, result.returncode, result.stderr)
        assert result.stderr == b"", (name, result.stderr)
        expected = json.dumps(instructions, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
        assert redirected.read_bytes() == expected.encode("ascii"), name

    text_result = cli("--format", "text", "instructions")
    assert text_result.startswith(f"agent-contrib {__version__} workflow ")
    assert "JSON output is canonical" in text_result
    assert "## Quick path" in text_result
    assert json.loads(cli("--format", "json", "instructions")) == instructions

    exported = Path.cwd() / "SKILL.md"
    skill = resources.joinpath("adapters/agent-contribute/SKILL.md").read_bytes()
    result = json.loads(cli("skill", "--output", exported))
    assert exported.read_bytes() == skill
    assert result["sha256"] == hashlib.sha256(skill).hexdigest()
    exported.write_bytes(b"Keep this user-owned file.\n")
    result = json.loads(cli("skill", "--output", exported, expected=1))
    assert result["error"]["code"] == "file_error"
    assert exported.read_bytes() == b"Keep this user-owned file.\n"

    alias_exported = Path.cwd() / "tipjar-SKILL.md"
    alias_result = json.loads(run([tipjar, "skill", "--output", alias_exported],
                                 cwd=Path.cwd(), env=env))
    assert alias_exported.read_bytes() == skill
    assert alias_result["sha256"] == hashlib.sha256(skill).hexdigest()

    contract = Path.cwd() / "unknown-schema.json"
    contract.write_text('{"schema_version": "999"}', encoding="utf-8")
    result = json.loads(cli("verify", contract, expected=1))
    for field in ("schema_valid", "execution_ready", "evidence_valid",
                  "upstream_submission_ready", "fork_completion_ready"):
        assert result[field] is False, field
    assert "$.schema_version: wrong constant or version" in result["errors"]
    assert json.loads(run([tipjar, "verify", contract], cwd=Path.cwd(), env=env,
                          expected=1)) == result
    # A new-schema draft with no actual host mandate cannot become ready, even
    # when installed outside the source and no GitHub executable is available.
    new_task = Path.cwd() / "new-schema-invalid.json"
    new_task.write_text('{"schema_version": "0.2"}', encoding="utf-8")
    for stage in ("implementation", "draft", "completion"):
        result = json.loads(cli("verify", new_task, "--stage", stage, expected=1))
        assert result["schema_valid"] is False
        assert result["implementation_ready"] is False
        assert result["draft_create_ready"] is False
        assert result["publication"]["verified"] is False
        assert result["completion_ready"] is False
    legacy = Path.cwd() / "legacy-schema-invalid.json"
    legacy.write_text('{"schema_version": "0.1"}', encoding="utf-8")
    result = json.loads(cli("verify", legacy, "--stage", "draft", expected=1))
    assert result["error"]["code"] == "schema_options"
    print("Installed metadata, resources, entrypoints, Skill and schema checks passed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installed", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.installed is not None:
        installed_check(args.installed.resolve())
        return

    source = Path(__file__).resolve().parents[1]
    env = {key: value for key, value in os.environ.items()
           if key not in ("PYTHONPATH", "PYTHONHOME", "GH_TOKEN", "GITHUB_TOKEN",
                          "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")}
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    with tempfile.TemporaryDirectory(prefix="agent-contrib-install-") as tmp:
        scratch = Path(tmp).resolve()
        assert not scratch.is_relative_to(source), "Set TMPDIR to a directory outside the checkout"
        direct = scratch / "direct"
        rebuilt = scratch / "from-sdist"
        print("Building sdist and direct wheel...", flush=True)
        run([sys.executable, "-m", "build", "--sdist", "--wheel", "--outdir", direct, source],
            cwd=scratch, env=env)
        sdist, = direct.glob("*.tar.gz")
        with tarfile.open(sdist) as archive:
            names = {name.split("/", 1)[1] for name in archive.getnames() if "/" in name}
        expected = {"pyproject.toml", "MANIFEST.in", "README.md", "NOTICE",
                    "LICENSE", "CONTRIBUTING.md", "SECURITY.md",
                    "CHANGELOG.md", "AGENTS.md", "tools/check_install.py", "tools/output_reference.py", "tools/release_check.py",
                    "tools/benchmark/benchlib.py", "tools/benchmark/collect.py", "tools/benchmark/score.py",
                    "tools/benchmark/experiment.py",
                    "tools/benchmark/README.md",
                    "actions/verify/action.yml", "actions/verify/report.py", "docs/examples/agent-contrib-verify.yml",
                    "docs/examples/release-pypi.yml", "docs/output-reference.md",
                    "tests/fixtures/dependencies/requirements.txt",
                    ".github/workflows/ci.yml"}
        expected.update(str(file.relative_to(source)) for file in (source / "tests").rglob("*")
                        if file.is_file() and file.suffix in (".py", ".json") and "__pycache__" not in file.parts)
        expected.update("web/" + name for name in ("index.html", "style.css", "app.js", "model.js", "jar.svg", "README.md"))
        expected.update("tests/web/" + name for name in ("model.test.cjs", "browser.html", "browser.test.js"))
        expected.update("agent_contribute/" + name for name in RESOURCE_PATHS)
        assert expected <= names, f"Missing sdist files: {sorted(expected - names)}"
        print("Rebuilding wheel from the sdist...", flush=True)
        run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", rebuilt, sdist],
            cwd=scratch, env=env)
        for label, directory in (("direct", direct), ("from-sdist", rebuilt)):
            wheel, = directory.glob("*.whl")
            root = scratch / label / "env"
            venv.EnvBuilder(with_pip=True, symlinks=os.name != "nt").create(root)
            python = root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            offline_env = {**env, "PIP_NO_INDEX": "1"}
            run([python, "-I", "-m", "pip", "install", "--no-index", "--no-deps", wheel],
                cwd=scratch, env=offline_env)
            cwd = scratch / label / "smoke"
            cwd.mkdir()
            print(f"Checking {label} wheel in a clean environment...", flush=True)
            print(run([python, "-I", Path(__file__).resolve(), "--installed", source],
                      cwd=cwd, env=offline_env), end="")
    print("Standalone build/install checks passed.")


if __name__ == "__main__":
    main()
