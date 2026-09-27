<img src="assets/icon.png" alt="agent-vdesktop icon" width="96" />

# agent-vdesktop

Let your AI coding agent control **Microsoft Virtual Desktops on Windows 11**: create and switch desktops, apply column / grid / multi-monitor layouts, launch Chrome / Windows Terminal / VS Code into specific layout slots, pin apps across desktops, and address windows by label or content.

Works natively on Windows 11 **and from inside WSL** — the same binary runs in both contexts via Windows' `binfmt_misc` interop.

## Quick install

**Claude Code:**

```
/plugin marketplace add seretos-agents/modular-software-factory
/plugin install agent-vdesktop@modular-software-factory
```

Self-contained `.exe` — no Python, no `pip install`, no dependencies.

## Try it

Ask your agent something like:

> create a desktop "demo", apply a 3-column layout, open Chrome on the left, a terminal in the middle, and VS Code on the right

The agent should call `create_desktop` → `apply_layout` → three `launch_*` tools, and the desktop should pop up.

## Alternative installs

### From the GitHub Releases page

If your agent doesn't support marketplaces, or you want a specific version manually:

1. Download `vdesktop-plugin-<version>.zip` from [Releases](https://github.com/seretos-agents/agent-vdesktop/releases).
2. Unpack to a stable folder (e.g. `C:\Users\<you>\.claude\plugins\agent-vdesktop\`).
3. In Claude Code:
   ```
   /plugin install <path-to-unpacked-folder>
   ```

### From the release branch

The `release` branch always carries the latest install-ready files (no zip step):

```
git clone --branch release --depth 1 https://github.com/seretos-agents/agent-vdesktop.git
```

Then `/plugin install <cloned-path>` in Claude Code.

### Build from source

Requires Python 3.11+ (standard python.org installer with the `py` launcher).

```powershell
git clone https://github.com/seretos-agents/agent-vdesktop.git
cd agent-vdesktop
py -3 -m pip install -e ".[build]"
.\scripts\build.ps1 -Clean -Package
```

Output: `bin/vdesktop.exe` plus `dist/vdesktop-plugin-<version>.zip`. Then install via `/plugin install <path>`.

## Notes

- **Windows 10 is not supported.** `IVirtualDesktopManagerInternal` semantics changed between Windows 10 and 11; only 11 works.
- **WSL** invokes the `.exe` transparently — no separate setup needed.
- If `list_desktops` raises `COMError` or `OSError`, the bundled `pyvda` predates your Windows build. Wait for the next release, or build from source after `pip install -U pyvda`.
- Registry state (window labels, handle IDs) lives in memory and is reset when the MCP server restarts. Use `list_unmanaged_windows` + `adopt_window` to recover previously launched windows.
