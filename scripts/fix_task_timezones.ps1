# Make scheduled tasks follow local time (and so daylight saving) instead of a fixed UTC offset.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\fix_task_timezones.ps1 [-WhatIf]
#
# Tasks created with a start time like 2026-10-19T16:30:00-04:00 are pinned to that UTC offset
# ("synchronize across time zones"): when DST ends they fire an hour early in local time. Removing
# the offset (2026-10-19T16:30:00) makes Task Scheduler read the time as local on every run.
# Prints each task's trigger start and next run before and after; -WhatIf changes nothing.

param(
    [string[]]$Tasks = @("pulse500 daily collection", "TickerLake-Daily", "HubRefresh", "DailyScraper", "PrecloseScraper"),
    [switch]$WhatIf
)

$offset = '([+-]\d{2}:\d{2}|Z)$'
foreach ($name in $Tasks) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $task) { "{0,-26} not found" -f $name; continue }
    $before = (Get-ScheduledTaskInfo -TaskPath $task.TaskPath -TaskName $name).NextRunTime
    $pinned = @($task.Triggers | Where-Object { $_.StartBoundary -match $offset })
    if (-not $pinned) {
        "{0,-26} already local time   next run {1:ddd MMM dd HH:mm}" -f $name, $before
        continue
    }
    $old = ($task.Triggers | ForEach-Object { $_.StartBoundary }) -join ', '
    foreach ($t in $task.Triggers) { $t.StartBoundary = $t.StartBoundary -replace $offset, '' }
    $new = ($task.Triggers | ForEach-Object { $_.StartBoundary }) -join ', '
    if ($WhatIf) {
        "{0,-26} would change {1} -> {2}   next run now {3:ddd MMM dd HH:mm}" -f $name, $old, $new, $before
        continue
    }
    try {
        Set-ScheduledTask -TaskPath $task.TaskPath -TaskName $name -Trigger $task.Triggers -ErrorAction Stop | Out-Null
    } catch {
        # S4U tasks ("run whether user is logged on or not") can only be changed from an elevated prompt
        "{0,-26} NOT CHANGED: {1} (logon {2}: run this script as administrator)" -f $name, $_.Exception.Message.Trim(), $task.Principal.LogonType
        continue
    }
    $after = (Get-ScheduledTaskInfo -TaskPath $task.TaskPath -TaskName $name).NextRunTime
    "{0,-26} {1} -> {2}   next run {3:ddd MMM dd HH:mm} -> {4:ddd MMM dd HH:mm}" -f $name, $old, $new, $before, $after
}
