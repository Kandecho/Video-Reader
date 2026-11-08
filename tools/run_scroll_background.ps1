param([ValidateSet('Intake','Queue','All')][string]$Mode='All')
$ErrorActionPreference = 'Stop'
$componentRoot = Split-Path -Parent $PSScriptRoot
$taskLogs = Join-Path (Join-Path $componentRoot 'data/agent/background-task') ($Mode.ToLowerInvariant())
New-Item -ItemType Directory -Path $taskLogs -Force | Out-Null
$logPath = Join-Path $taskLogs ((Get-Date -Format 'yyyy-MM-dd') + '.log')
$env:PYTHONIOENCODING = 'utf-8'
$env:VIDEO_READER_CONFIG = Join-Path $componentRoot 'config.json'
$runtime = Join-Path $componentRoot '.venv/Scripts/python.exe'
$runExit = 1
Push-Location -LiteralPath $componentRoot
try {
    ('Started: ' + [DateTimeOffset]::Now.ToString('o')) | Out-File -LiteralPath $logPath -Append -Encoding utf8
    $operation = switch ($Mode) { 'Intake' { 'background-intake' }; 'Queue' { 'background-queue' }; 'All' { 'background-tick' } }
    & $runtime -X utf8 -I (Join-Path $componentRoot 'launch_scroll.py') $operation *>> $logPath
    $runExit = $LASTEXITCODE
} catch {
    $_.Exception.Message | Out-File -LiteralPath $logPath -Append -Encoding utf8
} finally {
    Pop-Location
}
@{ exit_code=$runExit; ended=[DateTimeOffset]::Now.ToString('o'); log=$logPath } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskLogs 'last.json') -Encoding utf8
exit $runExit
