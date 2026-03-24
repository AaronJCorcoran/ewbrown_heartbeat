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
from datetime import datetime, timedelta, timezone
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


def get_pi_temperature():
    """Read Pi CPU temperature from sysfs. Returns float degrees C or None."""
    try:
        raw = Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()
        return round(int(raw) / 1000.0, 1)
    except Exception as e:
        logging.warning("Could not read Pi temperature: %s", e)
        return None


def estimate_ssd_days_remaining(ssd_path):
    """Estimate days until SSD is full based on observed write rate since oldest file."""
    import time
    ssd = Path(ssd_path)
    all_files = []
    try:
        for cam_dir in ssd.iterdir():
            if cam_dir.is_dir():
                for f in cam_dir.iterdir():
                    if f.is_file():
                        all_files.append(f)
    except Exception:
        return None

    if not all_files:
        return None

    try:
        oldest_mtime = min(f.stat().st_mtime for f in all_files)
        days_elapsed = (time.time() - oldest_mtime) / 86400
        if days_elapsed < 1:
            return None
        total, used, free = shutil.disk_usage(ssd)
        daily_rate = used / days_elapsed
        if daily_rate <= 0:
            return None
        return {
            "days_remaining": round(free / daily_rate),
            "daily_rate_human": human_bytes(daily_rate) + "/day",
        }
    except Exception as e:
        logging.warning("SSD days-remaining estimate failed: %s", e)
        return None


def get_camera_disk_info(ip, axis_user, axis_password):
    """Query SD_DISK usage from Axis camera. Returns dict with human-readable sizes or None."""
    url = f"http://{ip}/axis-cgi/disks/list.cgi?diskid=all"
    cmd = [
        "curl", "--silent", "--fail", "--anyauth",
        "--max-time", "10",
        "--user", axis_user + ":" + axis_password,
        url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            return None
        body = result.stdout
        # Sizes are in KB; extract from SD_DISK entry
        sd_m = re.search(r'diskid="SD_DISK"[^>]*>', body)
        if not sd_m:
            return None
        sd_tag = sd_m.group(0)
        total_m = re.search(r'totalsize="(\d+)"', sd_tag)
        free_m = re.search(r'freesize="(\d+)"', sd_tag)
        if not total_m or not free_m:
            return None
        total_kb = int(total_m.group(1))
        free_kb = int(free_m.group(1))
        used_kb = total_kb - free_kb
        used_pct = round(used_kb / total_kb * 100, 1) if total_kb else 0.0
        return {
            "total_human": human_bytes(total_kb * 1024),
            "used_human": human_bytes(used_kb * 1024),
            "free_human": human_bytes(free_kb * 1024),
            "used_percent": used_pct,
            "used_bytes": used_kb * 1024,
            "free_bytes": free_kb * 1024,
        }
    except Exception as e:
        logging.warning("Camera disk info failed for %s: %s", ip, e)
        return None


def format_duration(secs):
    secs = int(secs)
    if secs <= 0:
        return "0m"
    h = secs // 3600
    m = (secs % 3600) // 60
    if h:
        return str(h) + "h " + str(m) + "m"
    return str(m) + "m"


def axis_record_summary(name, ip, axis_user, axis_password, site_tz="UTC"):
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
            "yesterday_duration_secs": None,
            "yesterday_duration_human": None,
        }

    if result.returncode != 0:
        return {
            "name": name,
            "ip": ip,
            "reachable": False,
            "error": (result.stderr or result.stdout).strip(),
            "active_count": None,
            "completed_count": None,
            "yesterday_duration_secs": None,
            "yesterday_duration_human": None,
        }

    body = result.stdout
    tz = ZoneInfo(site_tz)
    yesterday = (datetime.now(tz) - timedelta(days=1)).date()

    active_count = 0
    completed_count = 0
    yesterday_duration_secs = 0
    total_completed_duration_secs = 0
    oldest_start_dt = None

    for tag in re.findall(r"<recording\b[^>]*>", body, flags=re.IGNORECASE):
        status_m = re.search(r'recordingstatus="([^"]*)"', tag)
        status_val = status_m.group(1).lower() if status_m else ""
        start_m = re.search(r'\bstarttime="([^"]*)"', tag)

        if status_val == "recording":
            active_count += 1
        else:
            completed_count += 1

        # Track oldest recording on the card (any status)
        if start_m and start_m.group(1):
            try:
                start_dt = datetime.fromisoformat(start_m.group(1).replace("Z", "+00:00"))
                if oldest_start_dt is None or start_dt < oldest_start_dt:
                    oldest_start_dt = start_dt
            except Exception:
                pass

        # Sum completed recording durations (all, and yesterday's subset)
        if status_val == "completed":
            stop_m = re.search(r'\bstoptime="([^"]*)"', tag)
            if start_m and stop_m and start_m.group(1) and stop_m.group(1):
                try:
                    start_dt = datetime.fromisoformat(start_m.group(1).replace("Z", "+00:00"))
                    stop_dt = datetime.fromisoformat(stop_m.group(1).replace("Z", "+00:00"))
                    dur = (stop_dt - start_dt).total_seconds()
                    if dur > 0:
                        total_completed_duration_secs += dur
                        if start_dt.astimezone(tz).date() == yesterday:
                            yesterday_duration_secs += dur
                except Exception:
                    pass

    oldest_local = None
    if oldest_start_dt is not None:
        oldest_local = oldest_start_dt.astimezone(tz).strftime("%Y-%m-%d %H:%M %Z")

    return {
        "name": name,
        "ip": ip,
        "reachable": True,
        "active_count": active_count,
        "completed_count": completed_count,
        "record_count_total": active_count + completed_count,
        "any_active": active_count > 0,
        "yesterday_duration_secs": yesterday_duration_secs,
        "yesterday_duration_human": format_duration(yesterday_duration_secs),
        "total_completed_duration_secs": total_completed_duration_secs,
        "oldest_recording_local": oldest_local,
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
        "--user", axis_user + ":" + axis_password,
        url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=20)
        if result.returncode == 0 and result.stdout:
            return result.stdout
    except Exception as e:
        logging.warning("Snapshot fetch failed for %s: %s", name, e)
    return None


def send_email(subject, body, snapshots=None, to_override=None):
    """Send heartbeat email. snapshots is a list of (filename, jpeg_bytes) tuples."""
    if getenv("HEARTBEAT_ENABLE_EMAIL", "0") != "1":
        return False, "email disabled"

    smtp_host = getenv("SMTP_HOST")
    smtp_port = int(getenv("SMTP_PORT", "587"))
    smtp_user = getenv("SMTP_USER")
    smtp_password = getenv("SMTP_PASSWORD")
    smtp_from = getenv("SMTP_FROM")
    smtp_to = to_override or getenv("SMTP_TO")

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
        return False, "missing SMTP config: " + ", ".join(missing)

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

    def check(ok, ok_msg, fail_msg):
        label = "OK    " if ok else "FAIL  "
        return label + (ok_msg if ok else fail_msg)

    # --- Quick Check summary ---
    pi_temp = status.get("pi_temp_c")
    summary = []
    summary.append("  Pi online   " + check(True, "uptime " + status["uptime"], ""))
    if pi_temp is not None:
        temp_ok = pi_temp < 70
        summary.append("  Pi temp     " + check(temp_ok, str(pi_temp) + " C", str(pi_temp) + " C -- HIGH"))
    disk_ok = "error" not in disk and disk.get("used_percent", 100) < 80
    ssd_est = status.get("ssd_days_remaining")
    days_str = (", ~" + str(ssd_est["days_remaining"]) + " days left") if ssd_est else ""
    disk_ok_msg = str(disk.get("used_percent", "?")) + "% used, " + str(disk.get("free_human", "?")) + " free" + days_str
    disk_fail_msg = "ERROR or " + str(disk.get("used_percent", "?")) + "% used"
    summary.append("  SSD         " + check(disk_ok, disk_ok_msg, disk_fail_msg))
    for cam_key in ("cam1", "cam2"):
        cam = cams[cam_key]
        cam_ok = cam.get("reachable", False)
        dur = cam.get("yesterday_duration_human")
        dur_str = (", yesterday=" + dur) if dur else ""
        cam_ok_msg = "completed=" + str(cam.get("completed_count", "?")) + ", active=" + str(cam.get("active_count", "?")) + dur_str
        cam_fail_msg = str(cam.get("error", "unreachable"))
        summary.append(("  " + cam_key).ljust(14) + check(cam_ok, cam_ok_msg, cam_fail_msg))
    pull_ok = pull.get("pull_exit_code") in (0, None)
    pull_rc = str(pull.get("pull_exit_code", "n/a"))
    summary.append("  Pull        " + check(pull_ok, "exit " + pull_rc, "exit " + pull_rc))

    lines = []
    lines.append("Field heartbeat: " + status["site_name"])
    lines.append("Local time: " + status["local_time"])
    lines.append("")
    lines.append("=== Quick Check ===")
    lines.extend(summary)
    lines.append("===================")
    lines.append("")
    lines.append("UTC time:   " + status["utc_time"])
    lines.append("")
    lines.append("Pi hostname: " + status["pi_hostname"])
    lines.append("Pi LAN IP:   " + status["pi_lan_ip"])
    lines.append("Uptime:      " + status["uptime"])
    if pi_temp is not None:
        lines.append("Pi CPU temp: " + str(pi_temp) + " C")
    lines.append("")

    if "error" in disk:
        lines.append("SSD: ERROR reading " + disk["path"] + ": " + disk["error"])
    else:
        lines.append(
            "SSD " + disk["path"] + ": used " + disk["used_human"] + " / " + disk["total_human"]
            + " (" + str(disk["used_percent"]) + "%), free " + disk["free_human"]
        )
        ssd_est = status.get("ssd_days_remaining")
        if ssd_est:
            lines.append(
                "SSD est. days remaining: " + str(ssd_est["days_remaining"])
                + " (writing " + ssd_est["daily_rate_human"] + ")"
            )

    lines.append("")
    for cam_key in ("cam1", "cam2"):
        cam = cams[cam_key]
        if cam["reachable"]:
            dur = cam.get("yesterday_duration_human", "0m")
            lines.append(
                cam_key + " (" + cam["ip"] + "): reachable, completed=" + str(cam["completed_count"])
                + ", active=" + str(cam["active_count"])
                + ", yesterday=" + dur
            )
            sd = cam.get("sd_disk")
            if sd:
                days_left = sd.get("days_remaining")
                days_str = (", ~" + str(days_left) + " days remaining") if days_left is not None else ""
                lines.append(
                    "  SD card: used " + sd["used_human"] + " / " + sd["total_human"]
                    + " (" + str(sd["used_percent"]) + "%), free " + sd["free_human"] + days_str
                )
            oldest = cam.get("oldest_recording_local")
            if oldest:
                lines.append("  Oldest recording on card: " + oldest)
        else:
            lines.append(cam_key + " (" + cam["ip"] + "): UNREACHABLE: " + str(cam.get("error", "unknown error")))

    lines.append("")
    lines.append("Pull service result: " + str(pull.get("service_result", "unknown")))
    lines.append("Pull exit code:      " + str(pull.get("pull_exit_code", "unknown")))
    lines.append("Last pull time:      " + str(pull.get("last_successful_pull_time", "unknown")))

    exported = pull.get("exported_total")
    if exported is None:
        lines.append("Exported last run:   unavailable")
    else:
        lines.append("Exported last run:   " + str(exported))

    lines.append("Any recording active now: " + str(status["any_recording_active_now"]))

    if status.get("public_ip"):
        lines.append("Public/WAN IP: " + status["public_ip"])

    lines.append("")

    latest = status.get("latest_files", {})
    for cam_key in ("cam1", "cam2"):
        lines.append("Latest files on SSD for " + cam_key + ":")
        items = latest.get(cam_key, [])
        if not items:
            lines.append("  (none found)")
        else:
            for item in items:
                lines.append("  " + item["name"] + " [" + item["size_human"] + "]")
        lines.append("")

    errors = pull.get("recent_error_lines", [])
    if errors:
        lines.append("Recent pull log errors:")
        for line in errors:
            lines.append("  " + line)
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

    axis_user = getenv("AXIS_USER", "root")
    axis_password = getenv("AXIS_PASSWORD", "")

    cam1_name = getenv("CAM1_NAME", "cam1")
    cam1_ip = getenv("CAM1_IP")
    cam2_name = getenv("CAM2_NAME", "cam2")
    cam2_ip = getenv("CAM2_IP")

    pull_log = getenv("PULL_LOG", "/home/admin/fieldcam/logs/pull_axis_recordings.log")
    pull_status_json_path = getenv("PULL_STATUS_JSON", "/home/admin/fieldcam/state/last_pull_status.json")

    utc_now, local_now = now_times(site_tz)

    alert_disk_threshold = int(getenv("ALERT_DISK_THRESHOLD", "80"))
    alert_temp_threshold = float(getenv("ALERT_TEMP_THRESHOLD", "70"))
    alert_email_to = getenv("ALERT_EMAIL_TO") or getenv("SMTP_TO")

    cam1 = axis_record_summary(cam1_name, cam1_ip, axis_user, axis_password, site_tz)
    cam2 = axis_record_summary(cam2_name, cam2_ip, axis_user, axis_password, site_tz)
    cam1["sd_disk"] = get_camera_disk_info(cam1_ip, axis_user, axis_password)
    cam2["sd_disk"] = get_camera_disk_info(cam2_ip, axis_user, axis_password)

    for cam in (cam1, cam2):
        sd = cam.get("sd_disk")
        total_dur = cam.get("total_completed_duration_secs", 0)
        if sd and total_dur > 0:
            bytes_per_sec = sd["used_bytes"] / total_dur
            if bytes_per_sec > 0:
                sd["days_remaining"] = round(sd["free_bytes"] / bytes_per_sec / 86400)
            else:
                sd["days_remaining"] = None
        elif sd:
            sd["days_remaining"] = None

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

    pi_temp = get_pi_temperature()

    status = {
        "site_name": site_name,
        "utc_time": utc_now.isoformat(),
        "local_time": local_now.isoformat(),
        "pi_hostname": pi_hostname,
        "pi_lan_ip": pi_lan_ip,
        "uptime": get_uptime(),
        "pi_temp_c": pi_temp,
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
        "ssd_days_remaining": estimate_ssd_days_remaining(ssd_path),
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
                snapshots.append((cam_name + "_" + ts + ".jpg", jpeg))
                logging.info("Snapshot fetched for %s (%d bytes)", cam_key, len(jpeg))
            else:
                logging.warning("Snapshot fetch returned nothing for %s", cam_key)

    subject = "[" + site_name + "] daily heartbeat " + local_now.strftime("%Y-%m-%d %H:%M:%S %Z")
    email_ok, email_msg = send_email(subject, report_text, snapshots=snapshots)

    logging.info("Heartbeat written to %s and %s", HEARTBEAT_JSON, HEARTBEAT_TXT)
    logging.info("Email status: %s (%s)", "ok" if email_ok else "not sent", email_msg)

    # --- Alert email ---
    alerts = []
    for cam_key in ("cam1", "cam2"):
        cam = status["cameras"][cam_key]
        if not cam.get("reachable"):
            alerts.append("Camera " + cam_key + " (" + cam["ip"] + ") is UNREACHABLE")
        elif cam.get("yesterday_duration_secs", 0) == 0:
            alerts.append("Camera " + cam_key + " (" + cam["ip"] + ") has NO recording from yesterday")
    pull_rc = args.pull_exit_code
    if pull_rc is not None and pull_rc != 0:
        alerts.append("Pull script exited with code " + str(pull_rc))
    disk = status["ssd"]
    if "used_percent" in disk and disk["used_percent"] >= alert_disk_threshold:
        alerts.append(
            "SSD usage is " + str(disk["used_percent"]) + "% "
            + "(" + disk["used_human"] + " used, " + disk["free_human"] + " free)"
            + " -- threshold " + str(alert_disk_threshold) + "%"
        )
    if pi_temp is not None and pi_temp >= alert_temp_threshold:
        alerts.append("Pi CPU temperature is " + str(pi_temp) + " C -- threshold " + str(alert_temp_threshold) + " C")

    if alerts:
        alert_lines = ["ALERT: " + site_name + " -- " + local_now.strftime("%Y-%m-%d %H:%M:%S %Z"), ""]
        for a in alerts:
            alert_lines.append("  !! " + a)
        alert_lines += ["", "--- Full heartbeat report ---", "", report_text]
        alert_body = "\n".join(alert_lines)
        alert_subject = "[ALERT] [" + site_name + "] " + ", ".join(alerts[:2])
        _, alert_msg = send_email(alert_subject, alert_body, to_override=alert_email_to)
        logging.warning("Alert email sent: %s", alert_msg)
    else:
        logging.info("No alert conditions detected")


if __name__ == "__main__":
    main()
