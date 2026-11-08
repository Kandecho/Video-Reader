# Shared action definition: pythonw starts PowerShell with CREATE_NO_WINDOW.
function Get-ScrollScheduledLaunch {
    param([ValidateSet('Intake','Queue','Daily')][string]$Task)
    $root = Split-Path -Parent $PSScriptRoot
    # uv's virtualenv pythonw shim can itself be a console executable. Use the
    # GUI interpreter from the same existing Python installation for this
    # stdlib-only launcher; the PowerShell runners still use the component venv.
    $runtime = Join-Path $root '.venv/Scripts/python.exe'
    $pythonw = & $runtime -X utf8 -I -c 'from pathlib import Path; import sys; print(Path(sys.base_prefix) / "pythonw.exe")'
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $pythonw -PathType Leaf)) { throw 'The existing Python installation must provide pythonw.exe.' }
    $binary = [IO.BinaryReader]::new([IO.File]::OpenRead($pythonw))
    try {
        $binary.BaseStream.Position = 0x3c
        $peOffset = $binary.ReadInt32()
        $binary.BaseStream.Position = $peOffset + 24 + 68
        if ($binary.ReadUInt16() -ne 2) { throw 'The scheduled launcher requires a Windows GUI interpreter, not a console shim.' }
    } finally { $binary.Dispose() }
    $publicPowerShell = Join-Path $env:ProgramFiles 'PowerShell/7/pwsh.exe'
    $pwshPath = if (Test-Path -LiteralPath $publicPowerShell -PathType Leaf) { $publicPowerShell } else { (Get-Command pwsh.exe -ErrorAction Stop).Source }
    $hiddenRunner = Join-Path $PSScriptRoot 'run_scheduled_hidden.py'
    $runner = Join-Path $PSScriptRoot $(if ($Task -eq 'Daily') { 'run_scroll_daily.ps1' } else { 'run_scroll_background.ps1' })
    $legacyArguments = '-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -File "' + $runner + '"'
    if ($Task -ne 'Daily') { $legacyArguments += ' -Mode ' + $Task }
    @{
        Execute=$pythonw
        Arguments='-X utf8 -I "' + $hiddenRunner + '" --powershell "' + $pwshPath + '" --task ' + $Task
        WorkingDirectory=$root
        LegacyExecute=$pwshPath
        LegacyArguments=$legacyArguments
    }
}

function Test-ScrollScheduledLaunch {
    param($Existing, $Launch)
    if (@($Existing.Actions).Count -ne 1) { return $false }
    $action = $Existing.Actions[0]
    return (($action.Execute -ieq $Launch.Execute -and $action.Arguments -ceq $Launch.Arguments) -or
            ($action.Execute -ieq $Launch.LegacyExecute -and $action.Arguments -ceq $Launch.LegacyArguments))
}
