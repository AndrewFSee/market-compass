# Register the weekday hub refresh in Task Scheduler (\MarketCompass\HubRefresh).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_task.ps1
#
# Runs run_jobs.py with the hub's venv (pythonw: no window) at 6:15 PM Mon-Fri, after the
# vol scrapers (4:30 PM). Same settings as the projects' own tasks: runs whether or not
# you are logged on (S4U), wakes the machine, catches up a missed run, never overlaps.
# Output goes to data\logs\jobs.log. Re-running this script replaces the task.

$hub = Split-Path -Parent $PSScriptRoot
$python = Join-Path $hub ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $python)) { throw "No venv at $python; create it first (see README)" }

$action = New-ScheduledTaskAction -Execute $python -Argument "run_jobs.py" -WorkingDirectory $hub
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At "6:15 PM"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited

Register-ScheduledTask -TaskPath "\MarketCompass\" -TaskName "HubRefresh" -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force `
    -Description "market-compass: refresh every hub data job (run_jobs.py). Log: data\logs\jobs.log" | Out-Null

$info = Get-ScheduledTaskInfo -TaskPath "\MarketCompass\" -TaskName "HubRefresh"
"Registered \MarketCompass\HubRefresh - next run $($info.NextRunTime)"
