param(
    [string]$Python = '3.12',
    [ValidateSet('mcp','vision','asr')][string[]]$Features = @('mcp','vision'),
    [switch]$FullRuntime
)
$ErrorActionPreference = 'Stop'
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'Install uv, or use Python 3.11+ venv + pip as documented in docs/installation.md.'
}
Push-Location -LiteralPath $PSScriptRoot
try {
    $runtimePython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $runtimePython)) {
        & uv venv --python $Python (Join-Path $PSScriptRoot '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed' }
    }
    if ($FullRuntime) {
        & uv pip install --python $runtimePython -r (Join-Path $PSScriptRoot 'requirements-runtime-windows.txt')
        if ($LASTEXITCODE -ne 0) { throw 'Locked runtime installation failed' }
        & uv pip install --python $runtimePython --no-deps -e $PSScriptRoot
    } else {
        $installTarget = if ($Features.Count) { $PSScriptRoot + '[' + ($Features -join ',') + ']' } else { $PSScriptRoot }
        & uv pip install --python $runtimePython -e $installTarget
    }
    if ($LASTEXITCODE -ne 0) { throw 'Component installation failed' }
    $configFile = Join-Path $PSScriptRoot 'config.json'
    if (-not (Test-Path -LiteralPath $configFile)) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'config.example.json') -Destination $configFile
    }
    & $runtimePython (Join-Path $PSScriptRoot 'tools/build_plugins.py') --core-root $PSScriptRoot
    if ($LASTEXITCODE -ne 0) { throw 'Plugin generation failed' }
    & $runtimePython -I (Join-Path $PSScriptRoot 'launch.py') doctor
    if ($LASTEXITCODE -ne 0) { throw 'Capability check failed' }
} finally { Pop-Location }
