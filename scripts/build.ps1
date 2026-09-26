# Build the vdesktop-plugin MCP server into a single-file Windows .exe.
#
# Usage (from plugin root):
#   pwsh -File scripts/build.ps1
#   pwsh -File scripts/build.ps1 -Clean      # remove dist/ build/ first
#   pwsh -File scripts/build.ps1 -Package    # also produce dist/vdesktop-plugin-<ver>.zip
#
# Requires: Python 3.11+ on PATH (via py.exe -3 launcher).
# Installs pyinstaller into the user-site or current env if missing.

[CmdletBinding()]
param(
    [switch]$Clean,
    [switch]$Package
)

$root = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $root

# Shared staging (Copy-PluginStage) and command-resolution (Resolve-McpCommand)
# logic -- also dot-sourced directly by tests/test_codex_mcp_manifest.py (R4)
# so the PR suite exercises the real code path this script runs.
. (Join-Path $PSScriptRoot "package-lib.ps1")

# Note: do NOT set $ErrorActionPreference = "Stop" globally. PowerShell 5.1
# wraps native-command stderr as ErrorRecord, which trips Stop semantics for
# tools like PyInstaller that log heavily to stderr. We check $LASTEXITCODE
# after each native call instead.

function Write-Step($msg) {
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Fail($msg) {
    Write-Host "ERROR: $msg" -ForegroundColor Red
    exit 1
}

# 1. Verify Python.
# In CI ($env:CI = "true") prefer python.exe on PATH so we get the version
# that actions/setup-python installed — py.exe consults the registry and can
# pick a different Python (e.g. one from the toolcache) than setup-python
# placed on PATH, which would silently change the bundled interpreter.
# Locally, prefer py.exe -3 because that's what Windows users normally have.
Write-Step "Checking Python"
$script:PyCmd = $null
$script:PyArgs = @()

$preferPython = ($env:CI -eq "true")

if (-not $preferPython -and (Get-Command py.exe -ErrorAction SilentlyContinue)) {
    $verRaw = & py.exe -3 --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        $script:PyCmd = "py.exe"
        $script:PyArgs = @("-3")
        Write-Host "    $verRaw (via py.exe)"
    }
}
if (-not $script:PyCmd -and (Get-Command python.exe -ErrorAction SilentlyContinue)) {
    $verRaw = & python.exe --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        $script:PyCmd = "python.exe"
        $note = if ($preferPython) { "via python.exe, CI mode" } else { "via python.exe" }
        Write-Host "    $verRaw ($note)"
    }
}
if (-not $script:PyCmd -and $preferPython -and (Get-Command py.exe -ErrorAction SilentlyContinue)) {
    # Final fallback inside CI: py.exe if python.exe wasn't found.
    $verRaw = & py.exe -3 --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        $script:PyCmd = "py.exe"
        $script:PyArgs = @("-3")
        Write-Host "    $verRaw (via py.exe, CI fallback)"
    }
}
if (-not $script:PyCmd) {
    Fail "No usable Python found. Install Python 3.11+ from https://www.python.org/downloads/ (with the py launcher option)."
}

function Invoke-Py {
    & $script:PyCmd @script:PyArgs @args
}

# 2. Ensure plugin + build deps are installed.
Write-Step "Ensuring dependencies (plugin + pyinstaller)"
Invoke-Py -m pip install --quiet --disable-pip-version-check -e ".[build]"
if ($LASTEXITCODE -ne 0) {
    Fail "pip install failed."
}

# 3. Clean previous build artifacts if requested.
if ($Clean) {
    Write-Step "Cleaning dist/ and build/"
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue dist, build
}

# 4. Run PyInstaller.
Write-Step "Running PyInstaller"
Invoke-Py -m PyInstaller vdesktop.spec --clean --noconfirm
if ($LASTEXITCODE -ne 0) {
    Fail "PyInstaller build failed."
}

$exe = Join-Path $root "dist\vdesktop.exe"
if (-not (Test-Path $exe)) {
    Fail "Expected dist/vdesktop.exe not produced."
}
$exeSize = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host "    dist/vdesktop.exe (${exeSize} MB)"

# 5. Copy into bin/ where plugin.json expects it.
# Retries the copy because Defender briefly locks freshly-emitted .exe files.
# If the lock turns out to be a running vdesktop.exe (i.e. the dev's own
# Claude Code session has the plugin loaded), surface that clearly.
Write-Step "Copying to bin/vdesktop.exe"
New-Item -ItemType Directory -Force -Path "bin" | Out-Null
$copied = $false
for ($i = 0; $i -lt 5; $i++) {
    try {
        Copy-Item -Force $exe "bin/vdesktop.exe" -ErrorAction Stop
        $copied = $true
        break
    } catch [System.IO.IOException] {
        Write-Host "    file locked (try $($i+1)/5), retrying..." -ForegroundColor Yellow
        Start-Sleep -Milliseconds 800
    }
}
if (-not $copied) {
    $running = @(Get-Process -Name vdesktop -ErrorAction SilentlyContinue)
    if ($running.Count -gt 0) {
        $pids = ($running | ForEach-Object { $_.Id }) -join ", "
        Write-Host "    vdesktop.exe is still running (PID: $pids)." -ForegroundColor Yellow
        Write-Host "    A Claude Code session likely has the plugin's MCP server loaded."
        Write-Host "    Close it (or run '/mcp' and disconnect 'vdesktop') and re-run the build."
        Write-Host "    To kill it now without that:   Stop-Process -Name vdesktop -Force"
    }
    Fail "Could not copy dist/vdesktop.exe to bin/ -- file remained locked."
}

# 6. Smoke-test: MCP initialize handshake.
# Resolve the command the way Codex/Windows actually resolves .mcp.json's
# declared "./bin/vdesktop" (P1: Windows appends ".exe" to an extensionless
# relative command) rather than hard-coding "bin\vdesktop.exe" here, so a
# build never silently smoke-tests a launcher .mcp.json no longer declares.
# PowerShell 5.1's Process StreamWriter prepends a UTF-8 BOM that MCP rejects.
# Work around it by staging the request in a temp file and using
# Start-Process -RedirectStandardInput, which pipes raw OS bytes.
Write-Step "Smoke-testing the binary (MCP initialize)"
$mcpConfig = Get-Content -Raw -Path (Join-Path $root ".mcp.json") | ConvertFrom-Json
$declaredCommand = $mcpConfig.mcpServers.vdesktop.command
$declaredArgs = $mcpConfig.mcpServers.vdesktop.args
try {
    $resolvedCommand = Resolve-McpCommand -PluginRoot $root
} catch {
    Fail "Resolve-McpCommand failed: $_"
}
Write-Host "    $declaredCommand -> $resolvedCommand"
$initMsg = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"build-smoke","version":"1"}}}'
$inFile = [System.IO.Path]::GetTempFileName()
$outFile = [System.IO.Path]::GetTempFileName()
$errFile = [System.IO.Path]::GetTempFileName()
[System.IO.File]::WriteAllBytes($inFile, [System.Text.Encoding]::UTF8.GetBytes($initMsg + "`n"))
# Splatted rather than passed as a fixed -ArgumentList: PS 5.1's Start-Process
# rejects -ArgumentList outright when the array is empty ("argument is NULL
# or empty"), and .mcp.json's declared args is exactly that ([]).
$startProcessArgs = @{
    FilePath              = $resolvedCommand
    RedirectStandardInput = $inFile
    RedirectStandardOutput = $outFile
    RedirectStandardError = $errFile
    WorkingDirectory      = $root
    NoNewWindow           = $true
    PassThru              = $true
}
if ($declaredArgs -and @($declaredArgs).Count -gt 0) {
    $startProcessArgs["ArgumentList"] = $declaredArgs
}
$proc = Start-Process @startProcessArgs
if (-not $proc.WaitForExit(8000)) { $proc.Kill(); Start-Sleep -Milliseconds 200 }
$stdout = (Get-Content -Raw -ErrorAction SilentlyContinue $outFile)
$stderrText = (Get-Content -Raw -ErrorAction SilentlyContinue $errFile)
Remove-Item -ErrorAction SilentlyContinue $inFile, $outFile, $errFile
if ($stdout -match '"result"' -and $stdout -match '"protocolVersion"') {
    Write-Host "    handshake OK" -ForegroundColor Green
} else {
    Write-Host "    stdout: $stdout" -ForegroundColor Yellow
    Write-Host "    stderr: $stderrText" -ForegroundColor Yellow
    Fail "Handshake failed -- see output above."
}

# 7. Optional: produce a release zip.
if ($Package) {
    Write-Step "Packaging release zip"
    $version = (Select-String -Path ".claude-plugin/plugin.json" -Pattern '"version"\s*:\s*"([^"]+)"').Matches[0].Groups[1].Value
    $zipName = "vdesktop-plugin-$version.zip"
    $zipPath = Join-Path $root "dist\$zipName"
    if (Test-Path $zipPath) { Remove-Item $zipPath }
    $stage = Join-Path $root "build\stage\vdesktop-plugin"
    Copy-PluginStage -Root $root -Stage $stage
    # Resolve against the STAGED copy, not $root -- the smoke test in step 6
    # already proved $root's own layout works, but only this call proves the
    # zip actually contains what .mcp.json's declared command resolves to.
    try {
        $stagedResolved = Resolve-McpCommand -PluginRoot $stage
    } catch {
        Fail "Resolve-McpCommand failed on the staged package: $_"
    }
    Write-Host "    staged command resolves to $stagedResolved"
    Compress-Archive -Path "$stage\*" -DestinationPath $zipPath -Force
    $zipSize = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
    Write-Host "    dist/$zipName (${zipSize} MB)"
}

Write-Step "Done."
Write-Host "bin/vdesktop.exe is ready. .mcp.json's declared ./bin/vdesktop already resolves to it."
