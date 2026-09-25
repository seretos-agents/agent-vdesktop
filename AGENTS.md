# agent-vdesktop — architecture notes

MCP server (self-contained Windows `.exe`) that lets AI agents drive Microsoft Virtual
Desktops on Windows 11. Python source under `src/vdesktop_plugin/`, frozen with PyInstaller.

README.md covers what it does and how to install. The source tree, `pyproject.toml`,
`vdesktop.spec`, and `.github/workflows/` are the source of truth for structure, build, and
release steps. This file records only the non-obvious decisions and cross-file invariants a
contributor must not silently break — the rationale you can't reconstruct from any one file.

## Tool priority

Skills and MCP tools take priority over raw file tools — and this **explicitly overrides** the generic harness default that says "prefer the dedicated file/search tools (Glob/Grep/Read)". When a skill or MCP tool covers the task, reach for it first; fall back to raw Glob/Grep/Read only when none applies.

Concretely: any *"where is X defined / what does the code support / which Y exist / how does X work / find the callers of X"* question is a **code-understanding task → use the matching skill first** (e.g. the `serena-wrapper` symbol-aware tools), never raw Glob/Grep/Read.

## Where the code lives (read before grounding a change)

This repo is the **MCP server + tool wiring only**. The automation engine lives in
**`lib-python-vdesktop`**, pinned to an exact tag (`@vX.Y.Z`) in `pyproject.toml`:

- The engine (pyvda/COM desktops, Win32 window ops, monitors, layouts, the tracking
  registry, app launchers, WSL pathmap) and its `VDesktopManager` facade are **in the lib**.
- `src/vdesktop_plugin/` only re-supplies the MCP tool schemas: each `tools/<area>.py`
  `register(mcp)`s `@mcp.tool()` wrappers (signatures + the LLM-facing docstrings) that
  forward to the single `VDesktopManager` instance in `tools/_engine.py`.

So a change to desktop/window/layout/launcher *behaviour*, the data model, or COM/Win32
handling is almost always a change **in `lib-python-vdesktop`**, not here. This repo only
changes when the MCP surface (tool names, args, descriptions) changes.

**The lib pin is fixed, and bumped via a ticket — not by hand at random.** When
`lib-python-vdesktop` releases, its pipeline files a `chore(deps): bump lib-python-vdesktop
to vX.Y.Z` ticket here. Bump the `@vX.Y.Z` in `pyproject.toml` in response to that ticket,
rebuild, and run the suite. (There is no floating-branch dependency to keep in sync.)

## Why a frozen .exe (the core constraint)

`pyvda` calls **undocumented** `IVirtualDesktopManagerInternal` COM interfaces whose vtable
changes between Windows builds, so the working `pyvda`/Windows combination has to be pinned.
PyInstaller bundles a known-good set so users never `pip install` anything. This is also why
**Windows 10 is unsupported** (different COM semantics — don't add compat branches) and why a
stale bundle surfaces as `COMError`/`OSError` from `list_desktops` (fix = rebuild on a newer
`pyvda`). WSL changes nothing: `binfmt_misc` runs the same `.exe` on the Windows host.

## build.ps1 is written for PS 5.1 on purpose

- It must run under **Windows PowerShell 5.1** (the system default) as well as 7 — invoke it as
  `.\scripts\build.ps1`, never `pwsh -File …`.
- **No global `$ErrorActionPreference = 'Stop'`** — PyInstaller writes heavily to stderr, which
  PS 5.1 wraps as ErrorRecords; a global Stop would abort a healthy build. Don't add one.
- The build ends with an MCP `initialize` handshake against the fresh `.exe` and fails if it
  doesn't answer — that smoke test is the build's real gate; keep it.

## src-layout + spec move together

The package is `vdesktop_plugin` under `src/` (`pyproject.toml` sets `package-dir`/`pythonpath`).
`vdesktop.spec` hardcodes `src/vdesktop_plugin/__main__.py` and `pathex=[…/src]` — if the layout
ever moves, change **both** the spec and `pyproject.toml`. `pyvda`, `comtypes`, and `uiautomation`
are pulled via `collect_all(...)` because they generate COM stubs lazily; a plain import won't
bundle them. The engine package **`lib_python_vdesktop`** is bundled via
`collect_submodules(...)` (incl. its `launchers` subpackage) — without that the frozen `.exe`
would miss the lazily-reached engine modules. It reaches the bundle as a normal installed
dependency (the git-pinned `@vX.Y.Z`), so a build needs that tag resolvable.

## Release is pipeline-owned

Release is a manual workflow dispatch (`release.yml`, `version=X.Y.Z`); the steps live there. Two
things that aren't obvious from skimming it:

- **The version comes from the workflow input, not the repo.** `pyproject.toml`'s `version` and
  `plugin.json` are stamped in the CI checkout only and never pushed back to `main` — leave them
  at whatever value locally; never hand-bump to do a release.
- **The marketplace notification is a direct POST**, not a tag-triggered workflow, because tags
  created with `GITHUB_TOKEN` don't fire downstream Actions (loop prevention). Don't "simplify" it
  back to a tag trigger.

`release` is an **orphan branch** force-pushed by that workflow, carrying only install-ready files
(`plugin.json`, `bin/vdesktop.exe`, `README.md`). It shares **no history** with `main` — don't
merge between them. All real edits go to `main`.

## Other don'ts

- Win32/COM paths are tested manually on real hardware. The deterministic engine logic
  (layouts, pathmap, tracking, ...) is unit-tested **in `lib-python-vdesktop`**, not here;
  this repo's `tests/` only smoke-tests that the full MCP tool surface registers. A green
  test run does **not** mean the COM paths work.
- No `LICENSE` file without an explicit license decision — `build.ps1` references it but tolerates
  its absence.
- `dispatch.yml` is a manual recovery tool (re-send the marketplace dispatch) — don't give it
  automatic triggers.

## Error contracts

Tools in this repo raise exceptions (which FastMCP surfaces as tool errors)
rather than returning `{"error": "..."}` dicts. This intentionally diverges
from sibling MCP servers for simplicity — callers should treat a tool error
response as a failure, not inspect a dict key.

## Cross-repo contract

The dispatch step in `release.yml`/`dispatch.yml` sends the same payload to both
`seretos-agents/modular-software-factory-staging` (lands straight to main, no review) and
`seretos-agents/modular-software-factory` (opens a review PR there). It authenticates with the
`MARKETPLACE_DISPATCH_TOKEN` repo secret (write access to both).
