# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

The **EW Brown Heartbeat Bundle** is a monitoring and status-reporting system for an Axis camera recording infrastructure deployed on a Raspberry Pi. It generates daily health reports and alert emails covering camera reachability, recording counts, SD card and SSD storage, Pi temperature, and pull service status.

## No Build System

This is a deployment bundle with no build, test, or lint tooling. Files are copied directly to the target Pi via `scp`. Dependencies are Python 3 standard library only plus `curl` and `systemctl` on the host.

## Deployment

SSH key auth is configured from the development machine to pi1 — no password needed for `scp`/`ssh`.

| Source | Target |
|--------|--------|
| `config/heartbeat.env.example` | `/home/admin/fieldcam/config/heartbeat.env` (fill in, chmod 600) |
| `scripts/run_pull_then_heartbeat.sh` | `/home/admin/fieldcam/scripts/` |
| `scripts/heartbeat_status.py` | `/home/admin/fieldcam/scripts/` |
| `systemd/pull-axis-recordings.service` | `/etc/systemd/system/` |

After copying the service unit: `sudo systemctl daemon-reload`

To test manually: `sudo systemctl start pull-axis-recordings.service`

Check output: `cat /home/admin/fieldcam/state/last_heartbeat.txt`

## Architecture

### Execution Flow

```
systemd timer (daily 08:15)
    → pull-axis-recordings.service
        → run_pull_then_heartbeat.sh
            → pull_axis_recordings.py   (existing pull script, unchanged)
            → heartbeat_status.py       (receives pull exit code as --pull-exit-code)
```

The wrapper captures the pull script's exit code, passes it to the heartbeat, then returns it so pull failures still register in systemd.

### Main Script: `scripts/heartbeat_status.py`

All config from environment variables loaded via `EnvironmentFile` in the systemd unit. The script:

1. Queries each camera at `http://<IP>/axis-cgi/record/list.cgi?recordingid=all` — parses XML with regex to get active/completed counts, yesterday's recording duration, and oldest recording on card
2. Queries each camera at `http://<IP>/axis-cgi/disks/list.cgi?diskid=all` — gets SD card used/free in KB; estimates days remaining from `used_bytes / total_completed_duration_secs`
3. Queries each camera at `http://<IP>/axis-cgi/jpg/image.cgi` — fetches JPEG snapshot for email attachment
4. Queries each camera at `http://<IP>/axis-cgi/param.cgi?action=list&group=Time` — gets configured NTP server and sync source; POSTs to `http://<IP>/axis-cgi/time.cgi` with `getDateTimeInfo` to get camera UTC time; compares to Pi time for offset
4. Reads Pi CPU temp from `/sys/class/thermal/thermal_zone0/temp`
5. Calls `systemctl show` for pull service metadata
6. Estimates SSD days remaining from write rate since oldest file on SSD
7. Writes output atomically to `state/last_heartbeat.json` and `state/last_heartbeat.txt`
8. Sends daily email with snapshots attached; sends separate alert email if any condition triggers

### Alert Conditions

- Camera unreachable
- Camera reachable but yesterday's recording duration is 0
- Camera NTP not synced to Pi (wrong server, wrong sync source, or offset ≥ 5s)
- Pull exit code non-zero
- SSD usage ≥ `ALERT_DISK_THRESHOLD` (default 80%)
- Pi CPU temp ≥ `ALERT_TEMP_THRESHOLD` (default 70°C)

### Configuration (`config/heartbeat.env.example`)

Key variables: `SITE_NAME`, `SITE_TZ`, `PI_HOSTNAME`, `PI_LAN_IP`, `SSD_PATH`, `CAM1_NAME`, `CAM1_IP`, `CAM2_NAME`, `CAM2_IP`, `AXIS_USER`, `AXIS_PASSWORD`, `SMTP_*`, `ALERT_DISK_THRESHOLD`, `ALERT_TEMP_THRESHOLD`, `ALERT_EMAIL_TO`.

**Important:** Axis cameras use `root` as the API username — `admin` returns 401. Gmail SMTP requires an App Password, not your real password.

Enable `INCLUDE_PUBLIC_IP=1` once the cellular SIM is installed.

### systemd Unit

- `Type=oneshot`, runs as `admin` user, loads `heartbeat.env` via `EnvironmentFile`
- Triggered by `pull-axis-recordings.timer` (daily at 08:15 local time, not included in this bundle)

## Runtime Requirements

- Python 3.9+ (`zoneinfo` module required)
- Linux with systemd
- `curl` in PATH
- Network access to cameras; optional SMTP server for email
