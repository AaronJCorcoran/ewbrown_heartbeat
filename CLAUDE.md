# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

The **EW Brown Heartbeat Bundle** is a monitoring and status-reporting system for an Axis camera recording infrastructure deployed on a Raspberry Pi. It generates daily health reports covering camera reachability, recording counts, disk usage, and pull service status.

## No Build System

This is a deployment bundle with no build, test, or lint tooling. Files are copied directly to the target Pi. There are no `package.json`, `Makefile`, or Python package files. Dependencies are Python 3 standard library only plus `curl` and `systemctl` on the host.

## Deployment

Files are deployed to the Raspberry Pi at these paths:

| Source | Target |
|--------|--------|
| `config/heartbeat.env.example` | `/home/admin/fieldcam/config/heartbeat.env` (fill in values) |
| `scripts/run_pull_then_heartbeat.sh` | `/home/admin/fieldcam/scripts/` |
| `scripts/heartbeat_status.py` | `/home/admin/fieldcam/scripts/` |
| `systemd/pull-axis-recordings.service` | `/etc/systemd/system/` |

After copying:
```bash
sudo systemctl daemon-reload
sudo systemctl enable pull-axis-recordings.service
sudo systemctl start pull-axis-recordings.service
```

## Architecture

### Execution Flow

```
systemd (oneshot service)
    → run_pull_then_heartbeat.sh
        → pull_axis_recordings.py  (existing, separate script)
        → heartbeat_status.py      (receives pull script exit code as $1)
```

The wrapper script captures the pull script's exit code and passes it to the heartbeat script, then propagates the original exit code so pull failures still register in systemd.

### Main Script: `scripts/heartbeat_status.py`

All configuration is read from environment variables (loaded by the systemd unit from `heartbeat.env`). The script:

1. Collects metrics: hostname, LAN IP, uptime, disk usage, camera reachability (via Axis HTTP API), active/completed recording counts, pull service systemd status, recent pull log errors, and latest video files per camera
2. Queries cameras at `http://<CAM_IP>/axis-cgi/record/list.cgi` using `curl`; parses XML responses with regex
3. Calls `systemctl show` for pull service metadata
4. Writes output atomically (write to `.tmp`, then rename) to:
   - `last_heartbeat.json` — structured data
   - `last_heartbeat.txt` — human-readable report
   - `heartbeat_status.log` — execution log
5. Optionally sends an email report via SMTP and fetches a public WAN IP

### Configuration (`config/heartbeat.env.example`)

Key variables: `SITE_NAME`, `SITE_TZ`, `PI_HOSTNAME`, `PI_LAN_IP`, `SSD_PATH`, `CAM1_NAME`, `CAM1_IP`, `CAM2_NAME`, `CAM2_IP`, `AXIS_USER`, `AXIS_PASSWORD`. Email and public IP lookup are opt-in (`HEARTBEAT_ENABLE_EMAIL=1`, `INCLUDE_PUBLIC_IP=1`).

### systemd Unit (`systemd/pull-axis-recordings.service`)

- `Type=oneshot`, runs as `admin` user
- Loads `heartbeat.env` via `EnvironmentFile`
- Requires `network-online.target`
- Intended to be triggered by a systemd timer (timer unit not included in this bundle)

## Runtime Requirements

- Python 3.9+ (`zoneinfo` module required)
- Linux with systemd
- `curl` available in PATH
- Network access to cameras and optionally SMTP server
