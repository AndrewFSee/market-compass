# Register the monthly macro panel rebuild in Task Scheduler (\MarketCompass\MacroPanelRebuild).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_panel_task.ps1
#
# Runs scripts\rebuild_macro_panel.py with the hub's venv (pythonw: no window) at 8:00 PM on
# the 20th of each month, after the weekday hub refresh, when most of the previous month's
# data is out. The rebuild takes about 3 hours. Same settings as HubRefresh: S4U, wakes the
# machine, catches up a missed run, never overlaps. Log: data\logs\macro_panel.log.
# Defined in XML because the ScheduledTasks cmdlets have no monthly trigger. The start time
# has no UTC offset, so it follows local time across DST. Re-running replaces the task.

$ErrorActionPreference = "Stop"
$hub = Split-Path -Parent $PSScriptRoot
$python = Join-Path $hub ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $python)) { throw "No venv at $python; create it first (see README)" }

function Esc([string]$s) { [System.Security.SecurityElement]::Escape($s) }
$names = [Globalization.CultureInfo]::InvariantCulture.DateTimeFormat
$months = (1..12 | ForEach-Object { "<$($names.GetMonthName($_))/>" }) -join ""
$start = (Get-Date -Day 20).ToString("yyyy-MM-dd") + "T20:00:00"

$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>market-compass: rebuild macro-regime-nowcaster's walk-forward panel, then republish it. Log: data\logs\macro_panel.log</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>$start</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByMonth>
        <DaysOfMonth><Day>20</Day></DaysOfMonth>
        <Months>$months</Months>
      </ScheduleByMonth>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$(Esc "$env:USERDOMAIN\$env:USERNAME")</UserId>
      <LogonType>S4U</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <WakeToRun>true</WakeToRun>
    <ExecutionTimeLimit>PT8H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$(Esc $python)</Command>
      <Arguments>scripts\rebuild_macro_panel.py</Arguments>
      <WorkingDirectory>$(Esc $hub)</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

Register-ScheduledTask -TaskPath "\MarketCompass\" -TaskName "MacroPanelRebuild" -Xml $xml -Force | Out-Null

$info = Get-ScheduledTaskInfo -TaskPath "\MarketCompass\" -TaskName "MacroPanelRebuild"
"Registered \MarketCompass\MacroPanelRebuild - next run $($info.NextRunTime)"
