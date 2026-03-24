#!/usr/bin/env python3

import argparse
import json
import logging
import os
import re
import shutil
import smtplib
import socket
import ssl
import subprocess
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo


BASE_DIR = Path("/home/admin/fieldcam")
STATE_DIR = BASE_DIR / "state"
LOG_DIR = BASE_DIR / "logs"

HEARTBEAT_JSON = STATE_DIR / "last_heartbeat.json"
HEARTBEAT_TXT = STATE_DIR / "last_heartbeat.txt"
HEARTBEAT_LOG = LOG_DIR / "heartbeat_status.log"


def getenv(name, default=None):
    value = os.environ.get(name, default)
    return value.strip() if isinstance(value, str) else value


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(HEARTBEAT_LOG),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def run_cmd(cmd, timeout=20):
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def write_text_atomic(path: Path, text: str):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_json_atomic(path: Path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=False), encoding="utf-8")
    tmp.replace(path)


def now_times(site_tz_name: str):
    utc_now = datetime.now(timezone.utc)
    local_now = utc_now.astimezone(ZoneInfo(site_tz_name))
    return utc_now, local_now


def human_bytes(num):
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    n = float(num)
    for unit in units:
        if n < 1024 or unit == units[-1]:
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{num} B"


def get_lan_ip():
    override = getenv("PI_LAN_IP")
    if override:
        return override

    result = run_cmd(
        [
            "bash",
            "-lc",
            "ip route get 1.1.1.1 | awk '/src/ {for (i=1;i<=NF;i++) if ($i==\"src\") print $(i+1)}'",
        ],
        timeout=5,
    )
    ip = result.stdout.strip()
    return ip or "unknown"


def get_uptime():
    try:
        with open("/proc/uptime", "r", encoding="utf-8") as f:
            seconds = int(float(f.read().split()[0]))
    except Exception:
        return "unknown"

    days = seconds // 86400
    seconds %= 86400
    hours = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def get_disk_usage(path_str):
    path = Path(path_str)
    try:
        total, used, free = shutil.disk_usage(path)
        pct = (used / total * 100) if total else 0.0
        return {
            "path": str(path),
            "total_bytes": total,
            "used_bytes": used,
            "free_bytes": free,
            "used_percent": round(pct, 1),
            "total_human": human_bytes(total),
            "used_human": human_bytes(used),
            "free_human": human_bytes(free),
        }
    except Exception as e:
        return {"path": str(path), "error": str(e)}


def axis_record_summary(name, ip, axis_user, axis_password):
    url = f"http://{ip}/axis-cgi/record/list.cgi?recordingid=all"
    cmd = [
        "curl",
        "--silent",
        "--show-error",
        "--fail",
        "--anyauth",
        "--max-time",
        "15",
        "--user",
        f"{axis_user}:{axis_password}",
        url,
    ]

    try:
        result = run_cmd(cmd, timeout=20)
    except Exception as e:
        return {
            "name": name,
            "ip": ip,
            "reachable": False,
            "error": str(e),
            "active_count": None,
            "completed_count": None,
        }

    if result.returncode != 0:
        return {
            "name": name,
            "ip": ip,
            "reachable": False,
            "error": (result.stderr or result.stdout).strip(),
            "active_count": None,
            "completed_count": None,
        }

    body = result.stdout
    statuses = re.findall(r'recordingstatus="([^"]+)"', body, flags=re.IGNORECASE)

    active_count = sum(1 for s in statuses if s.lower() == "recording")
    completed_count = sum(1 for s in statuses if s.lower() != "recording")

    return {
        "name": name,
        "ip": ip,
        "reachable": True,
        "active_count": active_count,
        "completed_count": completed_count,
        "record_count_total": len(statuses),
        "any_active": active_count > 0,
        "error": None,
    }


def read_recent_error_lines(log_path_str, max_lines=300, max_matches=8):
    log_path = Path(log_path_str)
    if not log_path.exists():
        return []

    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []

    recent = lines[-max_lines:]
    pattern = re.compile(r"(ERROR|Error|error|Traceback|Failed|FAILED|Exception)")
    matches = [line for line in recent if pattern.search(line)]
    return matches[-max_matches:]


def get_systemd_pull_info():
    result = run_cmd(
        [
            "systemctl",
            "show",
            "pull-axis-recordings.service",
            "--property=Result,ExecMainStatus,ExecMainStartTimestamp,ExecMainExitTimestamp,ActiveEnterTimestamp,ActiveExitTimestamp",
        ],
        timeout=10,
    )

    info = {}
    if result.returncode != 0:
        return info

    for line in result.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            info[k] = v
    return info


def read_json_file(path_str):
    path = Path(path_str)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def latest_files_summary(cam_name, ssd_path, limit=3):
    cam_dir = Path(ssd_path) / cam_name
    if not cam_dir.exists():
        return []

    files = [p for p in cam_dir.iterdir() if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    out = []
    for p in files[:limit]:
        st = p.stat()
        out.append(
            {
                "name": p.name,
                "size_human": human_bytes(st.st_size),
                "mtime_epoch": int(st.st_mtime),
            }
        )
    return out


def maybe_get_public_ip():
    if getenv("INCLUDE_PUBLIC_IP", "0") != "1":
        return None

    url = getenv("PUBLIC_IP_URL", "https://api.ipify.org")
    result = run_cmd(["curl", "--silent", "--show-error", "--max-time", "10", url], timeout=15)
    if result.returncode == 0:
        ip = result.stdout.strip()
        return ip or None
    return None


def fetch_camera_snapshot(name, ip, axis_user, axis_password):
    """Fetch a JPEG snapshot from an Axis camera. Returns bytes or None."""
    url = f"http://{ip}/axis-cgi/jpg/image.cgi"
    cmd = [
        "curl",
        "--silent",
        "--fail",
        "--anyauth",
        "--max-time", "15",
        "--user", f"{axis_user}:{axis_password}",
        url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=20)
        if result.returncode == 0 and result.stdout:
            return result.stdout
    except Exception as e:
        logging.warning("Snapshot fetch failed for %s: %s", name, e)
    return None


def send_email(subject, body, snapshots=None):
    """Send heartbeat email. snapshots is a list of (filename, jpeg_bytes) tuples."""
    if getenv("HEARTBEAT_ENABLE_EMAIL", "0") != "1":
        return False, "email disabled"

    smtp_host = getenv("SMTP_HOST")
    smtp_port = int(getenv("SMTP_PORT", "587"))
    smtp_user = getenv("SMTP_USER")
    smtp_password = getenv("SMTP_PASSWORD")
    smtp_from = getenv("SMTP_FROM")
    smtp_to = getenv("SMTP_TO")

    missing = [
        k
        for k, v in {
            "SMTP_HOST": smtp_host,
            "SMTP_USER": smtp_user,
            "SMTP_PASSWORD": smtp_password,
            "SMTP_FROM": smtp_from,
            "SMTP_TO": smtp_to,
        }.items()
        if not v
    ]

    if missing:
        return False, f"missing SMTP config: {', '.join(missing)}"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = smtp_to
    msg.set_content(body)

    for filename, jpeg_bytes in (snapshots or []):
        msg.add_attachment(jpeg_bytes, maintype="image", subtype="jpeg", filename=filename)

    context = ssl.create_default_context()

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
            server.starttls(context=context)
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        return True, "sent"
    except Exception as e:
        return False, str(e)


def render_text_report(status):
    cams = status["cameras"]
    pull = status["last_pull"]
    disk = status["ssd"]

    lines = []
    lines.append(f"Field heartbeat: {status['site_name']}")
    lines.append(f"Local time: {status['local_time']}")
    lines.append(f"UTC time:   {status['utc_time']}")
    lines.append("")
    lines.append(f"Pi hostname: {status['pi_hostname']}")
    lines.append(f"Pi LAN IP:   {status['pi_lan_ip']}")
    lines.append(f"Uptime:      {status['uptime']}")
    lines.append("")

    if "error" in disk:
        lines.append(f"SSD: ERROR reading {disk['path']}: {disk['error']}")
    else:
        lines.append(
            f"SSD {disk['path']}: used {disk['used_human']} / {disk['total_human']} "
            f"({disk['used_percent']}%), free {disk['free_human']}"
        )

    lines.append("")
    for cam_key in ("cam1", "cam2"):
        cam = cams[cam_key]
        if cam["reachable"]:
            lines.append(
                f"{cam_key} ({cam['ip']}): reachable, completed={cam['completed_count']}, "
                f"active={cam['active_count']}"
            )
        else:
            lines.append(f"{cam_key} ({cam['ip']}): UNREACHABLE: {cam.get('error', 'unknown error')}")

    lines.append("")

    lines.append(f"Pull service result: {pull.get('service_result', 'unknown')}")
    lines.append(f"Pull exit code:      {pull.get('pull_exit_code', 'unknown')}")
    lines.append(f"Last pull time:      {pull.get('last_successful_pull_time', 'unknown')}")

    exported = pull.get("exported_total")
    if exported is None:
        lines.append("Exported last run:   unavailable")
    else:
        lines.append(f"Exported last run:   {exported}")

    lines.append(f"Any recording active now: {status['any_recording_active_now']}")

    if status.get("public_ip"):
        lines.append(f"Public/WAN IP: {status['public_ip']}")

    lines.append("")

    latest = status.get("latest_files", {})
    for cam_key in ("cam1", "cam2"):
        lines.append(f"Latest files on SSD for {cam_key}:")
        items = latest.get(cam_key, [])
        if not items:
            lines.append("  (none found)")
        else:
            for item in items:
                lines.append(f"  {item['name']} [{item['size_human']}]")
        lines.append("")

    errors = pull.get("recent_error_lines", [])
    if errors:
        lines.append("Recent pull log errors:")
        for line in errors:
            lines.append(f"  {line}")
    else:
        lines.append("Recent pull log errors: none detected")

    return "\n".join(lines).strip() + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pull-exit-code", type=int, default=None)
    args = parser.parse_args()

    setup_logging()
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    site_name = getenv("SITE_NAME", "Field system")
    site_tz = getenv("SITE_TZ", "UTC")
    pi_hostname = getenv("PI_HOSTNAME", socket.gethostname())
    pi_lan_ip = get_lan_ip()
    ssd_path = getenv("SSD_PATH", "/mnt/video_ssd")

    axis_user = getenv("AXIS_USER", "admin")
    axis_password = getenv("AXIS_PASSWORD", "")

    cam1_name = getenv("CAM1_NAME", "cam1")
    cam1_ip = getenv("CAM1_IP")
    cam2_name = getenv("CAM2_NAME", "cam2")
    cam2_ip = getenv("CAM2_IP")

    pull_log = getenv("PULL_LOG", "/home/admin/fieldcam/logs/pull_axis_recordings.log")
    pull_status_json_path = getenv("PULL_STATUS_JSON", "/home/admin/fieldcam/state/last_pull_status.json")

    utc_now, local_now = now_times(site_tz)

    cam1 = axis_record_summary(cam1_name, cam1_ip, axis_user, axis_password)
    cam2 = axis_record_summary(cam2_name, cam2_ip, axis_user, axis_password)

    systemd_pull = get_systemd_pull_info()
    pull_status = read_json_file(pull_status_json_path)
    recent_errors = read_recent_error_lines(pull_log)

    last_successful_pull_time = None
    exported_total = None

    if pull_status:
        last_successful_pull_time = (
            pull_status.get("run_finished_utc")
            or pull_status.get("last_successful_pull_time")
            or pull_status.get("run_started_utc")
        )
        exported_total = pull_status.get("exported_total")
    else:
        last_successful_pull_time = systemd_pull.get("ExecMainExitTimestamp") or systemd_pull.get("ActiveExitTimestamp")

    status = {
        "site_name": site_name,
        "utc_time": utc_now.isoformat(),
        "local_time": local_now.isoformat(),
        "pi_hostname": pi_hostname,
        "pi_lan_ip": pi_lan_ip,
        "uptime": get_uptime(),
        "ssd": get_disk_usage(ssd_path),
        "cameras": {
            "cam1": cam1,
            "cam2": cam2,
        },
        "any_recording_active_now": bool((cam1.get("any_active") or False) or (cam2.get("any_active") or False)),
        "last_pull": {
            "pull_exit_code": args.pull_exit_code,
            "service_result": systemd_pull.get("Result"),
            "service_exec_status": systemd_pull.get("ExecMainStatus"),
            "last_successful_pull_time": last_successful_pull_time,
            "exported_total": exported_total,
            "recent_error_lines": recent_errors,
        },
        "latest_files": {
            "cam1": latest_files_summary("cam1", ssd_path),
            "cam2": latest_files_summary("cam2", ssd_path),
        },
        "public_ip": maybe_get_public_ip(),
    }

    report_text = render_text_report(status)

    write_json_atomic(HEARTBEAT_JSON, status)
    write_text_atomic(HEARTBEAT_TXT, report_text)

    snapshots = []
    for cam_key, cam_name, cam_ip in [
        ("cam1", cam1_name, cam1_ip),
        ("cam2", cam2_name, cam2_ip),
    ]:
        if status["cameras"][cam_key].get("reachable"):
            jpeg = fetch_camera_snapshot(cam_key, cam_ip, axis_user, axis_password)
            if jpeg:
                ts = local_now.strftime("%Y%m%d_%H%M%S")
                snapshots.append((f"{cam_name}_{ts}.jpg", jpeg))
                logging.info("Snapshot fetched for %s (%d bytes)", cam_key, len(jpeg))
            else:
                logging.warning("Snapshot fetch returned nothing for %s", cam_key)

    subject = f"[{site_name}] daily heartbeat {local_now.strftime('%Y-%m-%d %H:%M:%S %Z')}"
    email_ok, email_msg = send_email(subject, report_text, snapshots=snapshots)

    logging.info("Heartbeat written to %s and %s", HEARTBEAT_JSON, HEARTBEAT_TXT)
    logging.info("Email status: %s (%s)", "ok" if email_ok else "not sent", email_msg)


if __name__ == "__main__":
    main()
