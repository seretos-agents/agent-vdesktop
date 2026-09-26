"""Driving tests for the release-changelog scripts (#78, plan R1-R3).

These exercise the two new bash scripts under `.github/scripts/` as
subprocesses, exactly the way `release.yml`/`dispatch.yml` will call them:

- `prev-release-tag.sh <plugin> <version>` reads newline-separated tag names
  on stdin and prints the greatest strict-semver `<plugin>--v*` tag strictly
  below `<version>` (or nothing), exit 0 -- or, if `<version>` itself is not
  strict semver, prints an `::error::` line on stderr and exits 2 (R1, R2).
- `marketplace-payload.sh` reads `NAME DESC REPO VERSION TAG` (required) and
  `CHANGELOG` (optional) from the environment and prints the marketplace
  dispatch JSON payload built with `jq -n --arg ...`, omitting the
  `changelog` key entirely when `CHANGELOG` is empty/unset (R3).

Neither script exists yet at this round, so every test here is expected to
be RED: bash exits 127 ("No such file or directory") instead of the
contractual exit code, which fails the assertions below for that reason.

Harness notes (plan `Test / verification strategy`):
- Bash is invoked via its absolute path, never a PATH lookup, because a bare
  `bash` on a Windows CI runner resolves to a WSL stub that cannot see the
  Windows filesystem the way Git bash does.
- I/O is bytes throughout: stdin carries the tag list, `env=` carries the
  payload vars, stdout is compared as bytes (or parsed as JSON bytes).
- If bash or jq is missing: skip locally, but fail hard under CI so CI can
  never silently skip this coverage.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / ".github" / "scripts"
PREV_RELEASE_TAG_SCRIPT = (SCRIPTS_DIR / "prev-release-tag.sh").as_posix()
MARKETPLACE_PAYLOAD_SCRIPT = (SCRIPTS_DIR / "marketplace-payload.sh").as_posix()

PLUGIN = "agent-vdesktop"

if os.name == "nt":
    BASH_EXE = r"C:\Program Files\Git\bin\bash.exe"
else:
    BASH_EXE = shutil.which("bash")


def _skip_or_fail(reason: str) -> None:
    if os.environ.get("CI"):
        pytest.fail(reason)
    pytest.skip(reason)


def _require_bash() -> None:
    if not BASH_EXE or (os.name == "nt" and not Path(BASH_EXE).exists()):
        _skip_or_fail(f"Git bash not found at {BASH_EXE!r}")


def _require_jq() -> None:
    _require_bash()
    probe = subprocess.run([BASH_EXE, "-c", "command -v jq"], capture_output=True)
    if probe.returncode != 0:
        _skip_or_fail("jq not found in the bash environment")


def _run_prev_release_tag(plugin: str, version: str, tags: list[str]) -> subprocess.CompletedProcess:
    _require_bash()
    stdin = ("\n".join(tags) + "\n").encode() if tags else b""
    return subprocess.run(
        [BASH_EXE, PREV_RELEASE_TAG_SCRIPT, plugin, version],
        input=stdin,
        capture_output=True,
    )


def _run_marketplace_payload(env_vars: dict) -> subprocess.CompletedProcess:
    _require_jq()
    env = dict(os.environ)
    for key in ("NAME", "DESC", "REPO", "VERSION", "TAG", "CHANGELOG"):
        env.pop(key, None)
    env.update(env_vars)
    return subprocess.run(
        [BASH_EXE, MARKETPLACE_PAYLOAD_SCRIPT],
        input=b"",
        capture_output=True,
        env=env,
    )


# ---------------------------------------------------------------------------
# R1 -- prev-release-tag.sh resolution (driving-test)
# ---------------------------------------------------------------------------

R1_CASES = [
    (
        "numeric-ordering",
        ["agent-vdesktop--v0.1.9", "agent-vdesktop--v0.1.10", "agent-vdesktop--v0.1.2"],
        "0.1.11",
        "agent-vdesktop--v0.1.10",
    ),
    (
        "prerelease-numeric-rc2-lt-rc10",
        ["agent-vdesktop--v0.2.0-rc.2", "agent-vdesktop--v0.2.0-rc.10"],
        "0.2.0-rc.11",
        "agent-vdesktop--v0.2.0-rc.10",
    ),
    (
        "release-sorts-above-its-own-prereleases",
        ["agent-vdesktop--v0.2.0-rc.10", "agent-vdesktop--v0.1.10"],
        "0.2.0",
        "agent-vdesktop--v0.2.0-rc.10",
    ),
    (
        "alpha-lt-alpha.1-fewer-fields-lower-precedence",
        ["agent-vdesktop--v1.0.0-alpha", "agent-vdesktop--v1.0.0-alpha.1"],
        "1.0.0-beta",
        "agent-vdesktop--v1.0.0-alpha.1",
    ),
    (
        "alpha.1-lt-beta-alphanumeric-lexical-order",
        [
            "agent-vdesktop--v1.0.0-alpha",
            "agent-vdesktop--v1.0.0-alpha.1",
            "agent-vdesktop--v1.0.0-beta",
        ],
        "1.0.0-rc.1",
        "agent-vdesktop--v1.0.0-beta",
    ),
    (
        "numeric-identifier-lt-alphanumeric-identifier",
        ["agent-vdesktop--v1.0.0-1", "agent-vdesktop--v1.0.0-alpha"],
        "1.0.0",
        "agent-vdesktop--v1.0.0-alpha",
    ),
    (
        "excludes-the-tag-being-created",
        ["agent-vdesktop--v0.1.9", "agent-vdesktop--v0.1.10"],
        "0.1.10",
        "agent-vdesktop--v0.1.9",
    ),
    (
        "excludes-a-higher-hotfix-tag",
        ["agent-vdesktop--v0.1.9", "agent-vdesktop--v0.1.12"],
        "0.1.10",
        "agent-vdesktop--v0.1.9",
    ),
    (
        "ignores-legacy-src-foreign-and-non-strict-tags",
        [
            "v0.0.3",
            "src/agent-vdesktop--v0.1.12",
            "other--v9.9.9",
            "agent-vdesktop--v01.2.3",
            # Below the new version too, so the ignore-filtering is exercised
            # independently of "excludes higher tags" -- these would win on
            # value alone if the prefix/grammar filter did not drop them.
            "other--v0.1.1",
            "agent-vdesktop--v00.1.1",
            "agent-vdesktop--v0.1.5",
        ],
        "0.2.0",
        "agent-vdesktop--v0.1.5",
    ),
    (
        "first-release-empty-input",
        [],
        "0.1.0",
        "",
    ),
    (
        "first-release-legacy-tags-only",
        ["v0.0.1", "v0.0.2", "v0.0.3"],
        "0.1.0",
        "",
    ),
]


@pytest.mark.parametrize(
    "tags,version,expected", [c[1:] for c in R1_CASES], ids=[c[0] for c in R1_CASES]
)
def test_prev_release_tag(tags, version, expected):
    result = _run_prev_release_tag(PLUGIN, version, tags)
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode} "
        f"(127 means the script is still missing); "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    actual = result.stdout.decode().strip("\n")
    assert actual == expected, (
        f"expected stdout {expected!r}, got {result.stdout!r} (stderr={result.stderr!r})"
    )


def test_prev_release_tag_output_exact_bytes_no_crlf():
    """Additional coverage: stdout is exactly '<tag>\\n' -- no CR, matching
    the repo's `*.sh text eol=lf` contract and the `PREV_TAG=$(...)` capture
    in release.yml, which would otherwise pick up a stray \\r."""
    result = _run_prev_release_tag(
        PLUGIN,
        "0.1.11",
        ["agent-vdesktop--v0.1.9", "agent-vdesktop--v0.1.10", "agent-vdesktop--v0.1.2"],
    )
    assert result.stdout == b"agent-vdesktop--v0.1.10\n"


# ---------------------------------------------------------------------------
# R2 -- strict version grammar (driving-test)
# ---------------------------------------------------------------------------

INVALID_VERSIONS = [
    "1.2",
    "01.2.3",
    "1.2.3-rc.01",
    "1.2.3+b1",
    "v1.2.3",
    "1.2.3-",
]


@pytest.mark.parametrize("version", INVALID_VERSIONS)
def test_prev_release_tag_rejects_invalid_version(version):
    result = _run_prev_release_tag(PLUGIN, version, [])
    assert result.returncode == 2, (
        f"expected exit 2 for invalid version {version!r}, got {result.returncode} "
        f"(127 means the script is still missing, not rejected); stderr={result.stderr!r}"
    )
    assert b"::error::" in result.stderr, (
        f"expected an '::error::' line on stderr for invalid version {version!r}, "
        f"got stderr={result.stderr!r}"
    )


VALID_VERSIONS = ["1.2.3-rc.1", "0.0.0"]


@pytest.mark.parametrize("version", VALID_VERSIONS)
def test_prev_release_tag_accepts_valid_version(version):
    """Additional edge-case coverage: these versions must NOT be rejected."""
    result = _run_prev_release_tag(PLUGIN, version, [])
    assert result.returncode == 0, (
        f"expected exit 0 (accepted) for valid version {version!r}, got {result.returncode}; "
        f"stderr={result.stderr!r}"
    )
    assert result.stdout == b""


# ---------------------------------------------------------------------------
# R3 -- marketplace-payload.sh: jq-built payload, changelog verbatim/omitted
# ---------------------------------------------------------------------------

BASE_ENV = {
    "NAME": "agent-vdesktop",
    "DESC": 'A "vdesktop" MCP server, with \'quotes\' inside the description',
    "REPO": "seretos-agents/agent-vdesktop",
    "VERSION": "0.1.10",
    "TAG": "agent-vdesktop--v0.1.10",
}

# Hostile multi-line changelog: leading '/', backticks, double and single
# quotes, a command-substitution attempt, a variable-expansion attempt, a
# backslash, a tab, a blank line and trailing spaces, ending with a newline.
HOSTILE_CHANGELOG = (
    "/tmp/should-not-be-rewritten-by-msys-pathconv\n"
    "\n"
    "Line with `backticks`, \"double quotes\", 'single quotes',\n"
    "a command substitution attempt $(whoami) and a variable ${HOME}.\n"
    "A backslash: \\ and a tab:\tend.\n"
    "   \n"
    "Trailing spaces on this line   \n"
)


def test_payload_roundtrips_hostile_changelog():
    env = dict(BASE_ENV)
    env["CHANGELOG"] = HOSTILE_CHANGELOG
    result = _run_marketplace_payload(env)
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}; stderr={result.stderr!r}"
    )
    payload = json.loads(result.stdout)
    assert payload["client_payload"]["changelog"] == HOSTILE_CHANGELOG


@pytest.mark.parametrize("changelog_env", [None, ""], ids=["unset", "empty-string"])
def test_payload_omits_empty_changelog(changelog_env):
    env = dict(BASE_ENV)
    if changelog_env is not None:
        env["CHANGELOG"] = changelog_env
    result = _run_marketplace_payload(env)
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}; stderr={result.stderr!r}"
    )
    payload = json.loads(result.stdout)
    assert "changelog" not in payload["client_payload"], (
        "changelog key must be omitted entirely when CHANGELOG is empty/unset, "
        f"got client_payload={payload['client_payload']!r}"
    )


def test_payload_shape():
    """Additional coverage: every other field matches today's release.yml
    contract exactly (event_type, name, description with an embedded double
    quote, repo, category, version, ref, icon, description_url, tags)."""
    result = _run_marketplace_payload(dict(BASE_ENV))
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}; stderr={result.stderr!r}"
    )
    payload = json.loads(result.stdout)
    assert payload["event_type"] == "plugin-release"
    cp = payload["client_payload"]
    assert cp["name"] == BASE_ENV["NAME"]
    assert cp["description"] == BASE_ENV["DESC"]
    assert cp["repo"] == BASE_ENV["REPO"]
    assert cp["category"] == "mcp"
    assert cp["version"] == BASE_ENV["VERSION"]
    assert cp["ref"] == BASE_ENV["TAG"]
    assert cp["icon"] == (
        f"https://raw.githubusercontent.com/{BASE_ENV['REPO']}/{BASE_ENV['TAG']}/assets/icon.png"
    )
    assert cp["description_url"] == (
        f"https://raw.githubusercontent.com/{BASE_ENV['REPO']}/{BASE_ENV['TAG']}/description.md"
    )
    assert cp["tags"] == ["visual", "environment"]
    assert "changelog" not in cp
