param(
    [ValidateSet('Install','Status','Remove','Plan')][string]$Action = 'Status',
    [ValidateRange(1,1440)][int]$IntervalMinutes
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'scheduled_task_action.ps1')
$componentRoot = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $componentRoot '.venv/Scripts/python.exe'
$launcher = Join-Path $componentRoot 'launch_scroll.py'
$env:VIDEO_READER_CONFIG = Join-Path $componentRoot 'config.json'
$env:PYTHONIOENCODING = 'utf-8'
$legacyName = 'Video Reader Inbox Queue'

function Find-ComponentTask([string]$Name) {
    try { return Get-ScheduledTask -TaskName $Name -ErrorAction Stop }
    catch {
        if ($_.CategoryInfo.Category -eq 'ObjectNotFound') { return $null }
        throw
    }
}
if ($PSBoundParameters.ContainsKey('IntervalMinutes')) {
    if ($Action -ne 'Install') { throw 'IntervalMinutes is a legacy Install override; use background-config for separate intervals.' }
    $temporaryPayload = [IO.Path]::GetTempFileName()
    try {
        @{ interval_minutes=$IntervalMinutes } | ConvertTo-Json | Set-Content -LiteralPath $temporaryPayload -Encoding utf8
        $updated = & $runtime -X utf8 -I $launcher background-config --payload $temporaryPayload
        if ($LASTEXITCODE -ne 0) { throw 'Background policy update failed.' }
    } finally { Remove-Item -LiteralPath $temporaryPayload -Force }
}
$rawStatus = & $runtime -X utf8 -I $launcher background-status
if ($LASTEXITCODE -ne 0) { throw 'Cannot read background policy.' }
$policy = ($rawStatus | ConvertFrom-Json).policy
$windowStart = [TimeSpan]::ParseExact($policy.window_start, 'hh\:mm', [Globalization.CultureInfo]::InvariantCulture)
$windowEnd = [TimeSpan]::ParseExact($policy.window_end, 'hh\:mm', [Globalization.CultureInfo]::InvariantCulture)
$duration = $windowEnd - $windowStart
if ($duration -le [TimeSpan]::Zero) { $duration = $duration.Add([TimeSpan]::FromDays(1)) }
$wallStart = [DateTime]::SpecifyKind((Get-Date).Date.Add($windowStart), [DateTimeKind]::Unspecified)
$startAt = [DateTimeOffset]::new($wallStart, [TimeSpan]::FromMinutes($policy.timezone_offset_minutes)).LocalDateTime
$legacyLaunch = Get-ScrollScheduledLaunch -Task Intake
$baseArguments = $legacyLaunch.LegacyArguments -replace ' -Mode Intake$', ''
$plans = @(
    @{ name='Video Reader Inbox Intake'; mode='Intake'; interval_minutes=$policy.intake_interval_minutes },
    @{ name='Video Reader Task Queue'; mode='Queue'; interval_minutes=$policy.queue_interval_minutes }
)
foreach ($plan in $plans) {
    $plan.launch = Get-ScrollScheduledLaunch -Task $plan.mode
    $plan.arguments = $plan.launch.Arguments
    $plan.execute = $plan.launch.Execute
    $plan.window_start = $policy.window_start
    $plan.window_end = $policy.window_end
    $plan.duration_minutes = [int]$duration.TotalMinutes
    $plan.timezone_offset_minutes = $policy.timezone_offset_minutes
    $plan.start_at_local = $startAt.ToString('o')
}
if ($Action -eq 'Plan') {
    @{ tasks=$plans; source='background_policy'; requires_user_session=$true } | ConvertTo-Json -Depth 5
    exit 0
}
if ($Action -eq 'Status') {
    $items = foreach ($plan in $plans) {
        $task = Find-ComponentTask $plan.name
        if ($null -eq $task) { @{ installed=$false; task=$plan.name }; continue }
        $info = $task | Get-ScheduledTaskInfo
        @{ installed=$true; task=$plan.name; state=[string]$task.State; last_run=$info.LastRunTime;
           next_run=$info.NextRunTime; last_result=$info.LastTaskResult;
           interval=$task.Triggers.Repetition.Interval; start=$task.Triggers.StartBoundary;
           duration=$task.Triggers.Repetition.Duration }
    }
    @{ tasks=@($items); legacy_installed=($null -ne (Find-ComponentTask $legacyName)) } | ConvertTo-Json -Depth 5
    exit 0
}
# Validate ownership of every task before replacing or removing any of them.
foreach ($plan in $plans) {
    $existing = Find-ComponentTask $plan.name
    if ($existing -and -not (Test-ScrollScheduledLaunch -Existing $existing -Launch $plan.launch)) {
        throw ('同名计划任务属于不同入口，未覆盖：' + $plan.name)
    }
    $plan.was_disabled = ($existing -and $existing.State -eq 'Disabled')
}
$legacy = Find-ComponentTask $legacyName
if ($legacy -and (@($legacy.Actions).Count -ne 1 -or $legacy.Actions.Execute -ine $legacyLaunch.LegacyExecute -or $legacy.Actions.Arguments -cne $baseArguments)) {
    throw '旧合并任务属于不同入口，未覆盖。'
}
if ($Action -eq 'Remove') {
    foreach ($name in @($plans.name) + @($legacyName)) {
        if ($null -ne (Find-ComponentTask $name)) { Unregister-ScheduledTask -TaskName $name -Confirm:$false }
    }
    @{ removed=$true; tasks=@($plans.name) } | ConvertTo-Json
    exit 0
}
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$taskSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
foreach ($plan in $plans) {
    $taskAction = New-ScheduledTaskAction -Execute $plan.execute -Argument $plan.arguments -WorkingDirectory $componentRoot
    $trigger = New-ScheduledTaskTrigger -Daily -At $startAt
    $trigger.Repetition = (New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes $plan.interval_minutes) -RepetitionDuration $duration).Repetition
    Register-ScheduledTask -TaskName $plan.name -Action $taskAction -Trigger $trigger -Principal $principal -Settings $taskSettings -Description ('Opt-in background ' + $plan.mode + '; separate policy clock, no messages sent.') -Force | Out-Null
    if ($plan.was_disabled -or ($plan.mode -eq 'Intake' -and -not $policy.sync_enabled)) {
        Disable-ScheduledTask -TaskName $plan.name | Out-Null
    }
}
if ($legacy) { Unregister-ScheduledTask -TaskName $legacyName -Confirm:$false }
@{ installed=$true; tasks=$plans; legacy_removed=($null -ne $legacy); source='background_policy'; requires_user_session=$true } | ConvertTo-Json -Depth 5
