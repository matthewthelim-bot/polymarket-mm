# EC2 collector watchdog - runs from Windows Task Scheduler every 15 minutes.
#
# Checks the EC2 box from OUTSIDE (the on-box healthcheck can't report a dead
# box). Two layers:
#   1. TCP port 22 reachable?  (box alive)
#   2. If reachable: did the collector write data in the last 15 min? (pipeline alive)
#
# On state change to DOWN: Windows toast notification + log entry.
# On recovery: toast + log. State kept in a sentinel file to avoid alert spam.
#
# Install (run once from an elevated PowerShell in the repo root):
#   schtasks /Create /TN "PolymarketEC2Watchdog" /SC MINUTE /MO 15 `
#     /TR "powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File '$PWD\scripts\ec2_watchdog.ps1'" `
#     /F

$Ec2Host   = "100.52.215.239"
$Ec2User   = "ubuntu"
$RepoRoot  = Split-Path -Parent $PSScriptRoot
$KeyPath   = Join-Path $RepoRoot "polymarket-key.pem"
$StateFile = Join-Path $env:TEMP "polymarket_ec2_watchdog_state.txt"
$LogFile   = Join-Path $RepoRoot "ec2_watchdog.log"

function Write-Log($msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
    Add-Content -Path $LogFile -Value $line
}

function Show-Toast($title, $body) {
    try {
        # WinRT toast - works from scheduled tasks in the user's session
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(
            [Windows.UI.Notifications.ToastTemplateType]::ToastText02)
        $texts = $template.GetElementsByTagName("text")
        $texts.Item(0).AppendChild($template.CreateTextNode($title)) | Out-Null
        $texts.Item(1).AppendChild($template.CreateTextNode($body)) | Out-Null
        $toast = [Windows.UI.Notifications.ToastNotification]::new($template)
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier(
            "Polymarket Watchdog").Show($toast)
    } catch {
        # Fallback: message box via msg.exe (visible in interactive sessions)
        try { & msg.exe * "$title - $body" } catch {}
    }
}

# ---- Check 1: box reachable (retry once to ride out transient blips) ----
$alive = $false
foreach ($attempt in 1..2) {
    $tcp = Test-NetConnection -ComputerName $Ec2Host -Port 22 -WarningAction SilentlyContinue
    if ($tcp.TcpTestSucceeded) { $alive = $true; break }
    Start-Sleep -Seconds 20
}

# ---- Check 2: collector actually writing (only if box is up) ----
$collecting = $false
if ($alive) {
    $remote = "find /opt/polymarket-mm/polymarket-mm/data/live/`$(date -u +%Y-%m-%d) -name '*.jsonl' -mmin -15 2>/dev/null | head -1"
    $result = & ssh -i $KeyPath -o StrictHostKeyChecking=no -o ConnectTimeout=20 "$Ec2User@$Ec2Host" $remote 2>$null
    if ($LASTEXITCODE -eq 0 -and $result) { $collecting = $true }
}

$status = if (-not $alive) { "BOX-DOWN" } elseif (-not $collecting) { "NO-DATA" } else { "OK" }
$prev = if (Test-Path $StateFile) { (Get-Content $StateFile -Raw).Trim() } else { "OK" }
Set-Content -Path $StateFile -Value $status

if ($status -ne $prev) {
    if ($status -eq "OK") {
        Write-Log "RECOVERED (was $prev)"
        Show-Toast "EC2 Collector RECOVERED" "Box reachable and writing data again."
    } else {
        Write-Log "ALERT: $status (was $prev)"
        $detail = if ($status -eq "BOX-DOWN") {
            "EC2 $Ec2Host unreachable on port 22. Check AWS console - reboot may be needed."
        } else {
            "Box is up but no data written in 15 min. SSH in: journalctl -u polymarket-collector"
        }
        Show-Toast "EC2 Collector $status" $detail
    }
} elseif ($status -eq "OK" -and (Get-Date).Minute -lt 15 -and (Get-Date).Hour -eq 9) {
    Write-Log "OK (daily heartbeat)"
}
