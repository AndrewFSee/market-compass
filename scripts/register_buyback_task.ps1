# Register the weekday pre-open buyback check in Task Scheduler (\MarketCompass\BuybackPreOpen).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_buyback_task.ps1
#
# Runs only the two buyback-announcement jobs (SentIQ candidates + Claude classification) at
# 9:20 AM Mon-Fri, so 8-Ks filed before the open (44% of announcements, mostly 6:00-9:30 ET;
# SentIQ polls EDGAR every 2 minutes) are on the Buybacks page before 9:30. An incremental run
# takes ~20 s plus ~1.4 s per new candidate (~$0.0003 each). The evening HubRefresh still runs
# every job. Same settings as HubRefresh (S4U, wakes the machine, never overlaps); run_jobs.py's
# lock keeps it from overlapping a manual refresh. Output goes to data\logs\jobs.log.
# The trigger is stored without a UTC offset so it follows local time across DST.
# Re-running this script replaces the task.

$hub = Split-Path -Parent $PSScriptRoot
$python = Join-Path $hub ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $python)) { throw "No venv at $python; create it first (see README)" }

$action = New-ScheduledTaskAction -Execute $python -Argument "run_jobs.py --only buyback_news buyback_news_classify" `
    -WorkingDirectory $hub
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At "9:20 AM"
# the cmdlet writes the start in UTC ("...T14:20:00Z"); stripping the Z would mean 14:20 local, so
# write the local time itself, with no offset
$trigger.StartBoundary = (Get-Date -Hour 9 -Minute 20 -Second 0).ToString("yyyy-MM-ddTHH:mm:ss")
# no catch-up: a run after the open is pointless, the evening refresh covers the day
$settings = New-ScheduledTaskSettingsSet -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited

Register-ScheduledTask -TaskPath "\MarketCompass\" -TaskName "BuybackPreOpen" -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force `
    -Description "market-compass: pre-open buyback announcements (run_jobs.py --only buyback_news buyback_news_classify). Log: data\logs\jobs.log" | Out-Null

$info = Get-ScheduledTaskInfo -TaskPath "\MarketCompass\" -TaskName "BuybackPreOpen"
"Registered \MarketCompass\BuybackPreOpen - next run $($info.NextRunTime)"
