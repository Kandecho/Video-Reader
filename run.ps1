param([Parameter(ValueFromRemainingArguments = $true)][string[]]$ReaderArguments)
$ErrorActionPreference = 'Stop'
$prototypeRoot = $PSScriptRoot
$runtimePython = Join-Path $prototypeRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $runtimePython)) { throw 'Run bootstrap.ps1 first to create this component''s Python environment.' }
Push-Location -LiteralPath $prototypeRoot
try { & $runtimePython -I (Join-Path $prototypeRoot 'launch.py') @ReaderArguments; $readerExit = $LASTEXITCODE }
finally { Pop-Location }
exit $readerExit
