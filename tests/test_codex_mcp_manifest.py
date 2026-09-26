"""Driving tests for the extensionless vdesktop launcher (#81, plan R1-R5).

Codex marks the `vdesktop` MCP failed because `.codex-plugin/plugin.json`
declares the server inline with a hard-coded `${PLUGIN_ROOT}/bin/vdesktop.exe`
path. The fix (per plan):

- `.codex-plugin/plugin.json` points `mcpServers` at `"./.mcp.json"` instead
  (R1).
- The new root `.mcp.json` declares the extensionless `./bin/vdesktop`
  command (R2).
- `bin/vdesktop` is a committed `#!/bin/sh` shim that `exec`s the sibling
  `vdesktop.exe` -- the WSL/Linux resolution path (R3, R5).
- `scripts/package-lib.ps1` provides `Copy-PluginStage` (the build's staging
  copy, extracted so tests can reuse the real code path) and
  `Resolve-McpCommand` (applies Windows's append-`.exe`-if-missing rule and
  throws, naming the path, if the resolved file is missing from the staged
  package) (R4).

None of `.mcp.json`, `bin/vdesktop`, or `scripts/package-lib.ps1` exist yet at
this round, and `.codex-plugin/plugin.json` still holds the old inline dict,
so every driving test below is expected to be RED for that reason.

Harness notes (plan `Test / verification strategy`):
- PowerShell tests (R4) run `powershell.exe -NoProfile -ExecutionPolicy
  Bypass -Command ...`, dot-sourcing `scripts/package-lib.ps1` and calling
  its functions -- the same code `build.ps1` calls. When `os.name != "nt"`
  they skip locally but fail hard under CI (mirrors `test_release_scripts.py`).
- The shim test (R5) shells out to Git bash by absolute path, never a PATH
  lookup, for the same reason `test_release_scripts.py` does: a bare `bash`
  on a Windows CI runner resolves to a WSL stub that can't see the Windows
  filesystem the way Git bash does.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path, PurePosixPath

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CODEX_MANIFEST = REPO_ROOT / ".codex-plugin" / "plugin.json"
CLAUDE_MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"
MCP_JSON = REPO_ROOT / ".mcp.json"
LAUNCHER = REPO_ROOT / "bin" / "vdesktop"
PACKAGE_LIB = REPO_ROOT / "scripts" / "package-lib.ps1"

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


def _require_windows() -> None:
    if os.name != "nt":
        _skip_or_fail("PowerShell (package-lib.ps1) tests require Windows (os.name == 'nt')")


# ---------------------------------------------------------------------------
# R1 -- Codex manifest references ./.mcp.json instead of an inline dict
# ---------------------------------------------------------------------------


def test_codex_manifest_references_mcp_json():
    raw = CODEX_MANIFEST.read_text(encoding="utf-8")
    manifest = json.loads(raw)
    mcp_ref = manifest.get("mcpServers")
    assert mcp_ref == "./.mcp.json", (
        "expected .codex-plugin/plugin.json's mcpServers to be the string "
        f"'./.mcp.json', got {mcp_ref!r}"
    )
    assert ".exe" not in raw, (
        f"expected no '.exe' reference left in {CODEX_MANIFEST}, but the raw text contains one"
    )
    # A literal-string match alone would pass for a manifest pointing at the
    # right string in a form or location Codex never actually loads.
    # Resolve the reference the way a loader would -- per plan P2, "paths
    # resolve against the plugin root" (REPO_ROOT), using the exact string
    # from mcpServers -- rather than trusting the hardcoded MCP_JSON
    # constant, so a manifest holding the right literal but naming the wrong
    # file still fails here. (NOT against CODEX_MANIFEST.parent --
    # .codex-plugin/ is not the plugin root, and resolving there would make
    # this assertion contradict a correct implementation.)
    referenced = (REPO_ROOT / mcp_ref).resolve()
    assert referenced == MCP_JSON.resolve(), (
        f"expected the reference {mcp_ref!r} (resolved against the plugin root {REPO_ROOT}) "
        f"to point at {MCP_JSON}, got {referenced}"
    )
    assert referenced.is_file(), (
        f"expected the file referenced by mcpServers ({referenced}) to actually exist"
    )
    # Must be the SAME file R2 (test_mcp_json_command_is_extensionless)
    # validates the shape of -- loaded via the resolved reference, not a
    # same-named decoy elsewhere.
    referenced_manifest = json.loads(referenced.read_text(encoding="utf-8"))
    assert "vdesktop" in referenced_manifest.get("mcpServers", {}), (
        f"expected {referenced} (the file mcpServers actually points at) to "
        "declare an mcpServers.vdesktop entry"
    )


def test_claude_manifest_unaffected():
    """Additional edge-case coverage: Claude Code's own manifest keeps its
    separate inline mcpServers block untouched -- expected to already pass."""
    manifest = json.loads(CLAUDE_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["mcpServers"]["vdesktop"]["command"] == "${CLAUDE_PLUGIN_ROOT}/bin/vdesktop.exe"


# ---------------------------------------------------------------------------
# R2 -- .mcp.json declares the extensionless command
# ---------------------------------------------------------------------------


def test_mcp_json_command_is_extensionless():
    raw = MCP_JSON.read_text(encoding="utf-8")  # FileNotFoundError pre-change
    manifest = json.loads(raw)
    server = manifest["mcpServers"]["vdesktop"]
    assert server["command"] == "./bin/vdesktop", (
        f"expected command './bin/vdesktop', got {server.get('command')!r}"
    )
    assert PurePosixPath(server["command"]).suffix == "", (
        f"expected an extensionless command, got suffix on {server['command']!r}"
    )
    assert ".exe" not in raw, f"expected no '.exe' reference in {MCP_JSON}"
    assert isinstance(server["args"], list)
    assert server["cwd"] == "."

    # The literal checks above pass for a .mcp.json nothing ever reads.
    # Prove the command is actually resolvable to a real file, using the
    # same resolution logic (plugin root + cwd + command) the build and
    # Codex apply, and tie it to the SAME file R3 (test_launcher_committed_executable)
    # and R4 (test_staged_package_ships_declared_command) reason about --
    # so a syntactically-fine but wrong/unresolvable command fails here.
    plugin_root = MCP_JSON.parent
    resolved_command = (plugin_root / server["cwd"] / server["command"]).resolve()
    assert resolved_command == LAUNCHER.resolve(), (
        f"expected command {server['command']!r} resolved against cwd {server['cwd']!r} "
        f"from the plugin root {plugin_root} to point at {LAUNCHER}, got {resolved_command}"
    )
    # The equality above is path arithmetic on the same literals already
    # asserted, so it holds by construction and proves nothing on its own.
    # Require the resolved command to actually exist ON DISK -- a .mcp.json
    # with syntactically-correct-but-dangling paths (the launcher never
    # committed, or committed under a different name) fails here even though
    # every literal check above it passed.
    assert resolved_command.exists(), (
        f"expected the resolved command {resolved_command} to exist on disk, "
        "but no file is there -- a correct './bin/vdesktop' literal is not "
        "enough if the launcher itself was never committed"
    )
    resolved_exe = resolved_command.with_name(resolved_command.name + ".exe")
    expected_exe = (REPO_ROOT / "bin" / "vdesktop.exe").resolve()
    assert resolved_exe == expected_exe, (
        f"expected the .exe sibling of the resolved command to be {expected_exe} "
        f"(the same build artifact R4 resolves in the staged package), got {resolved_exe}"
    )


# ---------------------------------------------------------------------------
# R3 -- the launcher is committed, executable, LF-only
# ---------------------------------------------------------------------------


def test_launcher_committed_executable():
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-s", "bin/vdesktop"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"git ls-files failed: {result.stderr!r}"
    line = result.stdout.strip()
    assert line, "bin/vdesktop has no 'git ls-files -s' entry (not committed yet)"
    mode = line.split()[0]
    assert mode == "100755", f"expected mode 100755 for bin/vdesktop, got {mode!r} (line={line!r})"

    # --no-index is required: without it, `git check-ignore` never reports a
    # path that is already in the index as ignored (it exits 1 regardless of
    # whether a .gitignore rule matches), so the check above -- which just
    # proved bin/vdesktop IS tracked -- would make this assertion toothless.
    # --no-index consults the .gitignore patterns independent of tracking
    # state, so a rule like `bin/*` still makes this fail (exit 0) even
    # though the file is committed.
    ignore = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "check-ignore", "--no-index", "bin/vdesktop"],
        capture_output=True,
        text=True,
    )
    assert ignore.returncode == 1, (
        f"expected bin/vdesktop to NOT be gitignored (git check-ignore --no-index exit 1), "
        f"got {ignore.returncode} (stdout={ignore.stdout!r})"
    )

    content = LAUNCHER.read_bytes()
    assert content.startswith(b"#!/bin/sh\n"), f"expected a #!/bin/sh shebang, got {content[:32]!r}"
    assert b"\r" not in content, "bin/vdesktop must be LF-only (no CR)"


# ---------------------------------------------------------------------------
# R4 -- the staged package ships what the declared command resolves to
# ---------------------------------------------------------------------------


def _copy_git_tracked_files(dest: Path) -> None:
    """Copy every `git ls-files` entry from REPO_ROOT into dest, so only
    committed (index-tracked) files count -- matching what the release
    workflow's `git add -A` on the orphan branch actually ships."""
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z"],
        capture_output=True,
    )
    assert result.returncode == 0, f"git ls-files -z failed: {result.stderr!r}"
    for raw in result.stdout.split(b"\x00"):
        if not raw:
            continue
        rel = raw.decode("utf-8")
        src = REPO_ROOT / rel
        if not src.is_file():
            continue
        dst = dest / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _run_package_lib_command(command: str) -> subprocess.CompletedProcess:
    # Captured as bytes and decoded manually: Windows PowerShell 5.1 writes
    # redirected stderr in the console's OEM code page, not the locale
    # encoding `text=True` assumes, and a mismatch there raised
    # UnicodeDecodeError deep in subprocess's reader thread instead of
    # producing a usable CompletedProcess.
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True,
    )
    return subprocess.CompletedProcess(
        args=result.args,
        returncode=result.returncode,
        stdout=result.stdout.decode("utf-8", errors="replace"),
        stderr=result.stderr.decode("utf-8", errors="replace"),
    )


def test_staged_package_ships_declared_command(tmp_path):
    _require_windows()
    root = tmp_path / "root"
    stage = tmp_path / "stage"
    root.mkdir()
    _copy_git_tracked_files(root)
    # The one build artifact that isn't git-tracked: stub it so the staging
    # copy has something real to pick up for bin/vdesktop.exe.
    bin_dir = root / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "vdesktop.exe").write_bytes(b"MZ")

    command = (
        "$ErrorActionPreference = 'Stop'; "
        "try { "
        f". '{PACKAGE_LIB}'; "
        f"Copy-PluginStage -Root '{root}' -Stage '{stage}'; "
        f"Resolve-McpCommand -PluginRoot '{stage}' "
        "} catch { Write-Error $_; exit 1 }"
    )
    result = _run_package_lib_command(command)
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode} "
        f"(package-lib.ps1 missing produces a non-zero exit here); "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    stdout_lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert stdout_lines, f"expected Resolve-McpCommand to print a path; stdout={result.stdout!r}"
    resolved = stdout_lines[-1].strip()
    expected = stage / "bin" / "vdesktop.exe"
    assert resolved == str(expected), f"expected resolved command {str(expected)!r}, got {resolved!r}"
    assert Path(resolved).exists(), f"resolved command {resolved!r} does not exist in the stage"

    # WSL resolution path: the shim ships alongside the .exe.
    shim = stage / "bin" / "vdesktop"
    assert shim.exists(), f"expected the WSL shim to be staged at {shim}"
    assert shim.read_bytes().startswith(b"#!/bin/sh"), "staged bin/vdesktop must keep its #!/bin/sh shebang"

    # Manifest link: the staged Codex manifest's mcpServers file must exist in the stage.
    staged_manifest = stage / ".codex-plugin" / "plugin.json"
    assert staged_manifest.exists(), f"expected {staged_manifest} to be staged"
    manifest = json.loads(staged_manifest.read_text(encoding="utf-8"))
    mcp_ref = manifest.get("mcpServers")
    assert isinstance(mcp_ref, str) and mcp_ref.startswith("./"), (
        f"expected the staged manifest's mcpServers to be a relative file reference, got {mcp_ref!r}"
    )
    linked = stage / mcp_ref[2:]
    assert linked.exists(), f"expected the staged manifest's mcpServers file to exist at {linked}"


def test_resolve_reads_declared_command_from_mcp_json(tmp_path):
    """Additional edge-case coverage: Resolve-McpCommand must actually read
    .mcp.json's declared command rather than returning a hardcoded
    bin\\vdesktop.exe path. Retargeting the staged manifest's command to a
    different (still extensionless) name must change the resolved output to
    follow it."""
    _require_windows()
    root = tmp_path / "root"
    stage = tmp_path / "stage"
    root.mkdir()
    _copy_git_tracked_files(root)
    bin_dir = root / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "vdesktop.exe").write_bytes(b"MZ")
    # A second, differently-named build artifact so the retargeted command
    # still resolves to a real staged file.
    (bin_dir / "otherlauncher.exe").write_bytes(b"MZ")

    # Point the root .mcp.json's declared command at a different name before
    # staging -- a resolver that hardcodes bin\vdesktop.exe would not notice.
    mcp_json_path = root / ".mcp.json"
    mcp_config = json.loads(mcp_json_path.read_text(encoding="utf-8"))
    mcp_config["mcpServers"]["vdesktop"]["command"] = "./bin/otherlauncher"
    mcp_json_path.write_text(json.dumps(mcp_config), encoding="utf-8")

    command = (
        "$ErrorActionPreference = 'Stop'; "
        "try { "
        f". '{PACKAGE_LIB}'; "
        f"Copy-PluginStage -Root '{root}' -Stage '{stage}'; "
        f"Resolve-McpCommand -PluginRoot '{stage}' "
        "} catch { Write-Error $_; exit 1 }"
    )
    result = _run_package_lib_command(command)
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}; stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    stdout_lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert stdout_lines, f"expected Resolve-McpCommand to print a path; stdout={result.stdout!r}"
    resolved = stdout_lines[-1].strip()
    expected = stage / "bin" / "otherlauncher.exe"
    assert resolved == str(expected), (
        f"expected Resolve-McpCommand to follow the retargeted command and resolve to "
        f"{str(expected)!r}, got {resolved!r} -- a resolver that hardcodes bin\\vdesktop.exe "
        "would still print the original path here"
    )
    assert resolved != str(stage / "bin" / "vdesktop.exe"), (
        f"resolved path {resolved!r} must not be the original hardcoded vdesktop.exe path -- "
        "that would mean the resolver never read .mcp.json's command field"
    )


def test_resolve_fails_when_package_lacks_exe(tmp_path):
    """Additional edge-case coverage: with no .exe stub in the stage,
    Resolve-McpCommand's throw names the missing vdesktop.exe path.

    Copy-PluginStage and Resolve-McpCommand run as two separate PowerShell
    invocations (rather than one try/catch around both) so the failure below
    can only be attributed to Resolve-McpCommand's own check -- not to
    Copy-PluginStage failing first for an unrelated reason (e.g. an
    implementation that copies bin\\vdesktop.exe by explicit path and throws
    on the missing file itself, before Resolve-McpCommand ever runs).
    Copy-PluginStage must actually succeed -- proven by the staged shim's
    presence -- before the resolve step is even attempted.
    """
    _require_windows()
    root = tmp_path / "root"
    stage = tmp_path / "stage"
    root.mkdir()
    _copy_git_tracked_files(root)
    # Deliberately no bin/vdesktop.exe stub in root/bin -- it's gitignored,
    # so a real checkout would not have it either.

    copy_command = (
        "$ErrorActionPreference = 'Stop'; "
        "try { "
        f". '{PACKAGE_LIB}'; "
        f"Copy-PluginStage -Root '{root}' -Stage '{stage}' "
        "} catch { Write-Error $_; exit 1 }"
    )
    copy_result = _run_package_lib_command(copy_command)
    assert copy_result.returncode == 0, (
        "expected Copy-PluginStage alone to succeed even without bin/vdesktop.exe "
        f"present; stdout={copy_result.stdout!r} stderr={copy_result.stderr!r}"
    )
    staged_shim = stage / "bin" / "vdesktop"
    assert staged_shim.exists(), (
        f"expected Copy-PluginStage to have staged {staged_shim} -- if the copy step "
        "didn't actually run, the resolver failure checked below would prove nothing"
    )

    resolve_command = (
        "$ErrorActionPreference = 'Stop'; "
        "try { "
        f". '{PACKAGE_LIB}'; "
        f"Resolve-McpCommand -PluginRoot '{stage}' "
        "} catch { Write-Error $_; exit 1 }"
    )
    result = _run_package_lib_command(resolve_command)
    assert result.returncode != 0, (
        "expected Resolve-McpCommand alone (staging already succeeded above) to fail "
        f"when the staged package lacks vdesktop.exe, got 0; stdout={result.stdout!r}"
    )
    assert "vdesktop.exe" in result.stderr, (
        f"expected stderr to name the missing vdesktop.exe path, got stderr={result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# R5 -- the shim execs the sibling .exe, passing args and stdin through
# ---------------------------------------------------------------------------


def test_shim_execs_sibling_exe(tmp_path):
    _require_bash()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shim_path = bin_dir / "vdesktop"
    shutil.copy2(LAUNCHER, shim_path)  # FileNotFoundError pre-change
    stub = bin_dir / "vdesktop.exe"
    # The stub prints its own $0 first. If bin/vdesktop really execs this
    # sibling file, $0 inside the stub is the exec target name and ends in
    # "vdesktop.exe". A bin/vdesktop that never execs -- i.e. one whose own
    # body IS "echo $0; echo $@; cat", masquerading as the whole double --
    # would instead report its own invocation name ("./bin/vdesktop", no
    # ".exe"), so that variant fails the assertion below.
    with open(stub, "w", newline="\n", encoding="utf-8") as f:
        f.write('#!/bin/sh\necho "$0"\necho "$@"\ncat\n')

    chmod = subprocess.run(
        [BASH_EXE, "-c", "chmod +x bin/vdesktop bin/vdesktop.exe"],
        cwd=tmp_path,
        capture_output=True,
    )
    assert chmod.returncode == 0, f"chmod setup failed: {chmod.stderr!r}"

    # Run from a directory that is neither bin/ nor its parent, and invoke
    # the shim by its own absolute path (argv0), not a "./bin/vdesktop"
    # reference relative to this cwd. This discriminates dirname-based
    # resolution from cwd-relative resolution: a shim written as
    # `exec ./bin/vdesktop.exe "$@"` would resolve that path against
    # `elsewhere` -- which has no bin/ subdirectory -- and fail to find its
    # sibling, while a shim using `$(dirname "$0")` still finds it because
    # $0 (the absolute shim path passed below) carries its own location
    # regardless of the caller's working directory.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    result = subprocess.run(
        [BASH_EXE, "-c", 'exec "$0" "$@"', str(shim_path), "a", "b"],
        cwd=elsewhere,
        input=b"ping",
        capture_output=True,
    )
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}; stderr={result.stderr!r}"
    )
    lines = result.stdout.split(b"\n", 1)
    assert len(lines) == 2, (
        f"expected an argv0 line followed by the passthrough payload; stdout={result.stdout!r}"
    )
    argv0_line, payload = lines
    argv0 = argv0_line.decode("utf-8", errors="replace")
    # Proves an exec hand-off actually crossed into the sibling file: the
    # process image that produced this output reports itself as
    # ".../vdesktop.exe", not the shim's own name ("vdesktop").
    assert argv0.endswith("vdesktop.exe"), (
        "expected the stub's own $0 to end in 'vdesktop.exe' (proving bin/vdesktop "
        f"exec'd its sibling rather than acting as the double itself), got {argv0!r}"
    )
    assert payload == b"a b\nping", f"stdout payload={payload!r} (full stdout={result.stdout!r})"
