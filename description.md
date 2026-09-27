agent-vdesktop is an MCP server that lets your AI coding agent drive **Microsoft Virtual Desktops on Windows 11**. It exposes a set of tools your agent can call to organise your entire desktop environment without leaving the conversation. Works natively on Windows 11 and from inside WSL via `binfmt_misc` interop.

**Capabilities:**

- Create, switch, rename, and remove virtual desktops
- Move or route windows to specific desktops by label or window content
- Apply column, grid, and multi-monitor layouts to arrange windows automatically
- Launch Chrome, Windows Terminal, and VS Code directly into named layout slots
- Pin apps so they appear on every desktop
- Adopt and label unmanaged windows for later routing
- Resolve WSL paths to Windows paths for cross-environment app launches
