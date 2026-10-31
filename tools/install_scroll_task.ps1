param()
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$config = Get-Content -LiteralPath (Join-Path $root 'config.json') -Raw | ConvertFrom-Json
if (-not $config.agent.daily.enabled) { throw 'Enable the explicitly authorized daily trial first.' }
if ((Get-TimeZone).BaseUtcOffset -ne [TimeSpan]::FromHours(8) -or $config.agent.daily.timezone -ne '+08:00') {
    throw 'This local daily task requires the documented Beijing/UTC+08 Windows timezone.'
}
$name = 'ScrollAgent-HomepageFirst-' + $config.agent.delivery.recipient_uid
$runner = Join-Path $root 'tools/run_scroll_daily.ps1'
$pwsh = (Get-Command pwsh.exe -ErrorAction Stop).Source
$existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if ($existing -and -not ($existing.Actions.Arguments -match [regex]::Escape($runner))) {
    throw 'A task with this name is not managed by this installation.'
}
$action = New-ScheduledTaskAction -Execute $pwsh -Argument ('-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -File "' + $runner + '"') -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At ([DateTime]::Today.Add([TimeSpan]::ParseExact($config.agent.daily.time, 'hh\:mm', $null)))
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().User.Value) -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$definition = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Scroll Agent daily homepage-first trial; Bilibili DM and local archive only.'
Register-ScheduledTask -TaskName $name -InputObject $definition -Force | Out-Null
$info = Get-ScheduledTaskInfo -TaskName $name
@{task_name=$name; next_run=$info.NextRunTime.ToString('o'); time=$config.agent.daily.time; timezone=$config.agent.daily.timezone;
  logon_type='Interactive'; runner=$runner; catch_up=$false; wake_computer=$false; max_runtime_minutes=30} | ConvertTo-Json
