param([Parameter(ValueFromRemainingArguments = $true)][string[]]$ScrollArguments)
$ErrorActionPreference = 'Stop'
$runtimePython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
Push-Location -LiteralPath $PSScriptRoot
try { & $runtimePython -I (Join-Path $PSScriptRoot 'launch_scroll.py') @ScrollArguments; $scrollExit = $LASTEXITCODE }
finally { Pop-Location }
exit $scrollExit
