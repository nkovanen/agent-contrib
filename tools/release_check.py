"""Pre-release checklist: every statement of the package version agrees (docs/releasing.md).

    python tools/release_check.py                 # versions agree (also a unit test)
    python tools/release_check.py --release       # and the CHANGELOG heading is dated
    python tools/release_check.py --tag vX.Y.Z    # and the release tag names that version

Prints one line per problem and exits 1 if there is any. It reads files only.
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = r'([0-9]+\.[0-9]+\.[0-9]+)'
# Each source and the statements of the version it must contain; every pattern must match at least once.
SOURCES = {
    'pyproject.toml': [rf'(?m)^version = "{VERSION}"$'],
    'agent_contribute/__init__.py': [rf"(?m)^__version__ = '{VERSION}'$"],
    'CHANGELOG.md': [rf'(?m)\A# Changelog\n\n## {VERSION} — (?:unreleased|[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}})$'],
    'agent_contribute/instructions.md': [rf'(?m)\A# Installed contribution protocol {VERSION}$',
                                         rf'CLI/library version is {VERSION};'],
    'tools/check_install.py': [rf'== "{VERSION}"'],
    'tests/test_protocol.py': [rf"assertEqual\((?:output\.strip\(\)|result\['cli_version'\]), '{VERSION}'\)"],
}


def version(root=ROOT):
    match = re.search(SOURCES['pyproject.toml'][0], (Path(root) / 'pyproject.toml').read_text('utf-8'))
    return match.group(1) if match else None


def changelog_state(root=ROOT):
    match = re.search(r'(?m)\A# Changelog\n\n## \S+ — (\S+)$', (Path(root) / 'CHANGELOG.md').read_text('utf-8'))
    return match and match.group(1)


def problems(root=ROOT, release=False, tag=None):
    root, expected, found = Path(root), version(root), []
    if expected is None:
        return ['pyproject.toml: no version = "X.Y.Z" line']
    for relative, patterns in SOURCES.items():
        text = (root / relative).read_text('utf-8')
        for pattern in patterns:
            values = re.findall(pattern, text)
            if not values:
                found.append(f'{relative}: no version statement matching {pattern!r}; update the file or this checker')
            found += [f'{relative}: states {value}, pyproject.toml states {expected}' for value in values if value != expected]
    if release and changelog_state(root) == 'unreleased':
        found.append('CHANGELOG.md: the release heading must be dated (## X.Y.Z — YYYY-MM-DD), not unreleased')
    if tag is not None and tag != 'v' + expected:
        found.append(f'release tag must be v{expected}')
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description='Check that every statement of the package version agrees.')
    parser.add_argument('--root', default=str(ROOT), help='Repository root (default: this checkout)')
    parser.add_argument('--release', action='store_true', help='Also require a dated CHANGELOG heading')
    parser.add_argument('--tag', help='Also require this release tag to be vX.Y.Z for the package version')
    args = parser.parse_args(argv)
    found = problems(args.root, release=args.release, tag=args.tag)
    for problem in found:
        print(problem)
    if not found:
        print(f'Version statements agree: {version(args.root)}')
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main())
