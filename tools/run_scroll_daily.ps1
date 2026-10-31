param()
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$config = Get-Content -LiteralPath (Join-Path $root 'config.json') -Raw | ConvertFrom-Json
$agentDirectory = if ($config.agent.directory) { $config.agent.directory } else { 'data/agent' }
$directory = [IO.Path]::GetFullPath([IO.Path]::Combine($root, $agentDirectory))
$logs = Join-Path $directory 'task'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$log = Join-Path $logs ((Get-Date -Format 'yyyy-MM-dd') + '.log')
$env:PYTHONIOENCODING = 'utf-8'
$env:VIDEO_READER_CONFIG = Join-Path $root 'config.json'
$runtime = Join-Path $root '.venv/Scripts/python.exe'
Push-Location -LiteralPath $root
$runExit = 1
try {
    ('Started: ' + [DateTimeOffset]::Now.ToString('o')) | Out-File -LiteralPath $log -Append -Encoding utf8
    foreach ($dependency in @('ffmpeg', 'ffprobe', 'node')) {
        $resolved = Get-Command $dependency -ErrorAction Stop
        ('Dependency: ' + $dependency + '=' + $resolved.Source) | Out-File -LiteralPath $log -Append -Encoding utf8
    }
    & $runtime -X utf8 -I (Join-Path $root 'launch_scroll.py') daily --deliver --scheduled *>> $log
    $runExit = $LASTEXITCODE
}
catch { $_.Exception.Message | Out-File -LiteralPath $log -Append -Encoding utf8 }
finally { Pop-Location }
@{exit_code=$runExit; ended=[DateTimeOffset]::Now.ToString('o'); log=$log} |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logs 'last.json') -Encoding utf8
exit $runExit
