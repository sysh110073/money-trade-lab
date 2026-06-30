param(
    [string]$ProjectRoot = "",
    [string]$TaskName = "MoneyTrade Daily Update",
    [string]$StartTime = "16:35"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
}
else {
    (Resolve-Path -LiteralPath $ProjectRoot).Path
}
$UpdateScript = Join-Path $ProjectRoot "scripts\daily_update.ps1"

if (-not (Test-Path -LiteralPath $UpdateScript)) {
    throw "Update script not found: $UpdateScript"
}

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$UpdateScript`" -ProjectRoot `"$ProjectRoot`""

$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $StartTime

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 6)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "After the 16:30 market-data update, refresh MONEY_TRADE and sync Fundamental Lens quotes and monthly company research." `
    -Force

Write-Host "Registered scheduled task: $TaskName"
Write-Host "Schedule: Monday-Friday at $StartTime"
Write-Host "Script: $UpdateScript"
