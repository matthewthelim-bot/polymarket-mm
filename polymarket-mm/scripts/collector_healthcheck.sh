#!/usr/bin/env bash
# Collector health check — runs from cron every 10 minutes on the EC2 box.
#
# Detects the failure mode systemd cannot: the process is alive but no data
# is being written (wedged WS connections, silent feed death). If today's
# data directory has no file modified within the last 10 minutes, restart
# the collector and log the action to /var/log/polymarket-healthcheck.log.
#
# Install (as root):
#   cp collector_healthcheck.sh /opt/polymarket-mm/
#   chmod +x /opt/polymarket-mm/collector_healthcheck.sh
#   echo '*/10 * * * * root /opt/polymarket-mm/collector_healthcheck.sh' > /etc/cron.d/polymarket-healthcheck

set -u

DATA_DIR="/opt/polymarket-mm/polymarket-mm/data/live"
LOG_FILE="/var/log/polymarket-healthcheck.log"
SERVICE="polymarket-collector"
STALE_MINUTES=10

log() {
    echo "$(date -u '+%Y-%m-%d %H:%M:%S') $1" >> "$LOG_FILE"
}

# 1. Service must be active (systemd restarts crashes, but catch hard failures)
if ! systemctl is-active --quiet "$SERVICE"; then
    log "FAIL: $SERVICE not active — starting"
    systemctl start "$SERVICE"
    exit 0
fi

# 2. Today's dir must have a file modified within the last STALE_MINUTES.
#    Grace period: skip the write check if the service just (re)started.
TODAY_DIR="$DATA_DIR/$(date -u +%Y-%m-%d)"
uptime_s=$(systemctl show "$SERVICE" -p ActiveEnterTimestampMonotonic --value)
now_s=$(awk '{print int($1*1000000)}' /proc/uptime)
if [ -n "$uptime_s" ] && [ $((now_s - uptime_s)) -lt $((STALE_MINUTES * 60 * 1000000)) ]; then
    exit 0  # started recently; give it time to write
fi

recent=$(find "$TODAY_DIR" -name '*.jsonl' -mmin "-$STALE_MINUTES" 2>/dev/null | head -1)
if [ -z "$recent" ]; then
    log "FAIL: no writes in $TODAY_DIR for ${STALE_MINUTES}m — restarting $SERVICE"
    systemctl restart "$SERVICE"
else
    # Healthy — log once an hour (minute 0x) to keep a heartbeat trail
    if [ "$(date -u +%M)" -lt 10 ]; then
        n=$(find "$TODAY_DIR" -name '*.jsonl' 2>/dev/null | wc -l)
        log "OK: $n files today, latest write fresh"
    fi
fi
