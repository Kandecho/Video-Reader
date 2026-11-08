param()
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'scheduled_task_action.ps1')
$root = Split-Path -Parent $PSScriptRoot
$config = Get-Content -LiteralPath (Join-Path $root 'config.json') -Raw | ConvertFrom-Json
if (-not $config.agent.daily.enabled) { throw 'Enable the explicitly authorized daily trial first.' }
if ((Get-TimeZone).BaseUtcOffset -ne [TimeSpan]::FromHours(8) -or $config.agent.daily.timezone -ne '+08:00') {
    throw 'This local daily task requires the documented Beijing/UTC+08 Windows timezone.'
}
$name = 'ScrollAgent-HomepageFirst-' + $config.agent.delivery.recipient_uid
$runner = Join-Path $root 'tools/run_scroll_daily.ps1'
$launch = Get-ScrollScheduledLaunch -Task Daily
$existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if ($existing -and -not (Test-ScrollScheduledLaunch -Existing $existing -Launch $launch)) {
    throw 'A task with this name is not managed by this installation.'
}
$action = New-ScheduledTaskAction -Execute $launch.Execute -Argument $launch.Arguments -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At ([DateTime]::Today.Add([TimeSpan]::ParseExact($config.agent.daily.time, 'hh\:mm', $null)))
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().User.Value) -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$definition = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Scroll Agent daily homepage-first trial; Bilibili DM and local archive only.'
Register-ScheduledTask -TaskName $name -InputObject $definition -Force | Out-Null
if ($existing -and $existing.State -eq 'Disabled') { Disable-ScheduledTask -TaskName $name | Out-Null }
$info = Get-ScheduledTaskInfo -TaskName $name
@{task_name=$name; next_run=$info.NextRunTime.ToString('o'); time=$config.agent.daily.time; timezone=$config.agent.daily.timezone;
  logon_type='Interactive'; runner=$runner; catch_up=$false; wake_computer=$false; max_runtime_minutes=30} | ConvertTo-Json
