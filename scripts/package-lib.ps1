# Shared staging/resolution logic for scripts/build.ps1 and the test suite
# (tests/test_codex_mcp_manifest.py, R4). Dot-source this file rather than
# calling it directly -- it defines functions and has no side effects of its
# own.
#
# Written PS 5.1-safe (no ternary operator, no null-coalescing) since
# build.ps1 must run under Windows PowerShell 5.1 as well as 7.

function Copy-PluginStage {
    <#
    .SYNOPSIS
    Copies the install-ready plugin files from $Root into $Stage.

    This is build.ps1's packaging step, extracted so PR CI -- which has no
    PyInstaller and therefore no dist/vdesktop.exe -- can still exercise the
    real staging code the release build uses, against a synthetic $Root.
    #>
    param(
        [Parameter(Mandatory)] [string]$Root,
        [Parameter(Mandatory)] [string]$Stage
    )

    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Stage
    New-Item -ItemType Directory -Force -Path $Stage | Out-Null

    Copy-Item -Recurse -Force (Join-Path $Root ".claude-plugin") $Stage

    $codexPlugin = Join-Path $Root ".codex-plugin"
    if (Test-Path $codexPlugin) {
        Copy-Item -Recurse -Force $codexPlugin $Stage
    }

    $mcpJson = Join-Path $Root ".mcp.json"
    if (Test-Path $mcpJson) {
        Copy-Item -Force $mcpJson $Stage
    }

    Copy-Item -Recurse -Force (Join-Path $Root "bin") $Stage

    $skills = Join-Path $Root "skills"
    if (Test-Path $skills) {
        Copy-Item -Recurse -Force $skills $Stage
    }

    foreach ($name in @("README.md", "LICENSE", "description.md")) {
        $src = Join-Path $Root $name
        if (Test-Path $src) {
            Copy-Item -Force $src $Stage
        }
    }

    $assets = Join-Path $Root "assets"
    if (Test-Path $assets) {
        Copy-Item -Recurse -Force $assets $Stage
    }
}

function Resolve-McpCommand {
    <#
    .SYNOPSIS
    Resolves .mcp.json's declared mcpServers.vdesktop.command against
    $PluginRoot the way a Windows host resolves it, and prints the resolved
    path to stdout.

    .DESCRIPTION
    .mcp.json declares an extensionless, POSIX-relative command (e.g.
    "./bin/vdesktop") so Codex on WSL can exec the committed shim directly.
    On Windows, Start-Process does not append ".exe" to a relative command by
    itself, so this function applies that rule explicitly (P1: Windows
    resolves the extensionless name to its ".exe" sibling) before checking
    the resolved file actually exists in $PluginRoot -- catching a package
    that never shipped the built .exe.
    #>
    param(
        [Parameter(Mandatory)] [string]$PluginRoot
    )

    $mcpJsonPath = Join-Path $PluginRoot ".mcp.json"
    if (-not (Test-Path $mcpJsonPath)) {
        throw "Cannot resolve mcpServers.vdesktop.command: $mcpJsonPath not found."
    }

    $config = Get-Content -Raw -Path $mcpJsonPath | ConvertFrom-Json
    $server = $config.mcpServers.vdesktop
    if (-not $server) {
        throw "Cannot resolve mcpServers.vdesktop.command: no 'vdesktop' entry in $mcpJsonPath."
    }

    $command = $server.command
    $cwd = "."
    if ($server.cwd) {
        $cwd = $server.cwd
    }

    $combined = Join-Path (Join-Path $PluginRoot $cwd) $command
    if ([System.IO.Path]::GetExtension($combined) -ne ".exe") {
        # Windows's own append-.exe-if-missing rule (P1) -- Start-Process
        # never applies it to a relative path on our behalf.
        $combined = "$combined.exe"
    }
    $resolved = [System.IO.Path]::GetFullPath($combined)

    if (-not (Test-Path $resolved)) {
        throw "Resolved command '$resolved' (declared command '$command' in $mcpJsonPath) does not exist -- expected the built vdesktop.exe to be present."
    }

    Write-Output $resolved
}
