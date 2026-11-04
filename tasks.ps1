param([Parameter(ValueFromRemainingArguments = $true)][string[]]$TaskArguments)
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
Push-Location -LiteralPath $PSScriptRoot
try { & $taskPython -I (Join-Path $PSScriptRoot 'launch_tasks.py') @TaskArguments; $taskExit = $LASTEXITCODE }
finally { Pop-Location }
exit $taskExit
