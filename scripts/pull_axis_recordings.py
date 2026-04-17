#!/usr/bin/env python3

import json
import os
import pathlib
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

# =========================
# CONFIG
# =========================

CAMERAS = [
    {
        "name": "cam1",
        "host": "192.168.50.201",
        "username": "root",
        "password": "password",
        "dest_dir": "/mnt/video_ssd/cam1",
        "event_id": None,   # set to None to disable filtering
    },
    {
        "name": "cam2",
        "host": "192.168.50.202",
        "username": "root",
        "password": "password",
        "dest_dir": "/mnt/video_ssd/cam2",
        "event_id": "record_at_night",   # set to None to disable filtering
    },
]

STATE_FILE = "/home/admin/fieldcam/state/exported_recordings.json"
LOG_FILE = "/home/admin/fieldcam/logs/pull_axis_recordings.log"

LIST_TIMEOUT = 120
EXPORT_TIMEOUT = 6 * 60 * 60  # 6 hours

# Skip recordings older than this many days.  Keeps SSD usage bounded when a
# fresh drive is inserted and the SD cards still hold weeks of old footage.
# Set to 0 to disable (pull everything).
MAX_RECORDING_AGE_DAYS = 21


# =========================
# UTILITIES
# =========================

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log(message: str) -> None:
    line = f"[{now_iso()}] {message}"
    print(line)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def ensure_directories() -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    for cam in CAMERAS:
        os.makedirs(cam["dest_dir"], exist_ok=True)


def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        log("WARNING: Could not read state file, starting with empty state")
        return {}


def save_state(state: dict) -> None:
    tmp_path = STATE_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp_path, STATE_FILE)


def run_curl(url: str, username: str, password: str, timeout: int, output_path: str | None = None) -> str:
    cmd = [
        "curl",
        "--silent",
        "--show-error",
        "--fail",
        "--anyauth",
        "-u", f"{username}:{password}",
        "--max-time", str(timeout),
        url,
    ]

    if output_path is not None:
        cmd.extend(["-o", output_path])

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
    )

    return result.stdout


def parse_recordings(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    recordings_node = root.find("recordings")
    if recordings_node is None:
        return []

    recordings = []
    for rec in recordings_node.findall("recording"):
        recordings.append({
            "diskid": rec.attrib.get("diskid"),
            "recordingid": rec.attrib.get("recordingid"),
            "starttime": rec.attrib.get("starttime"),
            "starttimelocal": rec.attrib.get("starttimelocal"),
            "stoptime": rec.attrib.get("stoptime"),
            "stoptimelocal": rec.attrib.get("stoptimelocal"),
            "recordingtype": rec.attrib.get("recordingtype"),
            "eventid": rec.attrib.get("eventid"),
            "eventtrigger": rec.attrib.get("eventtrigger"),
            "recordingstatus": rec.attrib.get("recordingstatus"),
            "source": rec.attrib.get("source"),
            "locked": rec.attrib.get("locked"),
        })
    return recordings


def timestamp_for_filename(ts: str | None) -> str:
    if not ts:
        return "unknown"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%Y%m%dT%H%M%SZ")
    except Exception:
        return ts.replace(":", "").replace("-", "")


def build_filename(cam_name: str, recording: dict) -> str:
    start_str = timestamp_for_filename(recording.get("starttime"))
    recording_id = recording.get("recordingid", "unknown")
    return f"{cam_name}_{start_str}_{recording_id}.mkv"


def _recording_too_old(recording: dict) -> bool:
    """Return True if the recording started more than MAX_RECORDING_AGE_DAYS ago."""
    if MAX_RECORDING_AGE_DAYS <= 0:
        return False
    starttime = recording.get("starttime")
    if not starttime:
        return False
    try:
        start_dt = datetime.fromisoformat(starttime.replace("Z", "+00:00"))
        cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_RECORDING_AGE_DAYS)
        return start_dt < cutoff
    except Exception:
        return False


def should_export(cam: dict, recording: dict, state: dict) -> bool:
    recording_id = recording.get("recordingid")
    if not recording_id:
        return False

    if recording.get("recordingstatus") != "completed":
        return False

    if recording.get("diskid") != "SD_DISK":
        return False

    if cam.get("event_id") and recording.get("eventid") != cam["event_id"]:
        return False

    if recording_id in state.get(cam["name"], {}):
        return False

    if _recording_too_old(recording):
        return False

    return True


def list_recordings(cam: dict) -> list[dict]:
    url = f"http://{cam['host']}/axis-cgi/record/list.cgi?recordingid=all"
    xml_text = run_curl(
        url=url,
        username=cam["username"],
        password=cam["password"],
        timeout=LIST_TIMEOUT,
    )
    return parse_recordings(xml_text)


def export_recording(cam: dict, recording: dict, dest_path: str) -> None:
    recording_id = recording["recordingid"]
    diskid = recording.get("diskid") or "SD_DISK"
    filename_stem = pathlib.Path(dest_path).stem

    url = (
        f"http://{cam['host']}/axis-cgi/record/export/exportrecording.cgi"
        f"?schemaversion=1"
        f"&recordingid={recording_id}"
        f"&diskid={diskid}"
        f"&exportformat=matroska"
        f"&filename={filename_stem}"
    )

    temp_path = dest_path + ".part"
    run_curl(
        url=url,
        username=cam["username"],
        password=cam["password"],
        timeout=EXPORT_TIMEOUT,
        output_path=temp_path,
    )

    os.replace(temp_path, dest_path)


def process_camera(cam: dict, state: dict) -> None:
    cam_name = cam["name"]
    cam_state = state.setdefault(cam_name, {})

    log(f"{cam_name}: listing recordings from {cam['host']}")
    recordings = list_recordings(cam)
    log(f"{cam_name}: found {len(recordings)} recording(s)")

    recordings.sort(key=lambda r: r.get("starttime") or "")

    exported_count = 0

    for rec in recordings:
        rec_id = rec.get("recordingid", "")
        status = rec.get("recordingstatus", "")
        eventid = rec.get("eventid", "")
        start = rec.get("starttime", "")
        stop = rec.get("stoptime", "")

        log(
            f"{cam_name}: seen rec_id={rec_id} "
            f"status={status} eventid={eventid} start={start} stop={stop}"
        )

        if not should_export(cam, rec, state):
            if _recording_too_old(rec) and rec_id not in cam_state:
                log(f"{cam_name}: skipping {rec_id} (older than {MAX_RECORDING_AGE_DAYS} days)")
            continue

        filename = build_filename(cam_name, rec)
        dest_path = os.path.join(cam["dest_dir"], filename)

        if os.path.exists(dest_path):
            log(f"{cam_name}: file already exists, marking exported: {dest_path}")
            cam_state[rec_id] = {
                "exported_at": now_iso(),
                "dest_path": dest_path,
                "size_bytes": os.path.getsize(dest_path),
                "starttime": rec.get("starttime"),
                "stoptime": rec.get("stoptime"),
            }
            save_state(state)
            continue

        log(f"{cam_name}: exporting {rec_id} -> {dest_path}")
        export_recording(cam, rec, dest_path)

        size_bytes = os.path.getsize(dest_path)
        cam_state[rec_id] = {
            "exported_at": now_iso(),
            "dest_path": dest_path,
            "size_bytes": size_bytes,
            "starttime": rec.get("starttime"),
            "stoptime": rec.get("stoptime"),
        }
        save_state(state)

        exported_count += 1
        log(f"{cam_name}: export complete ({size_bytes / (1024 * 1024):.1f} MiB)")

    log(f"{cam_name}: done; exported {exported_count} new recording(s)")


def main() -> int:
    ensure_directories()
    state = load_state()

    any_error = False

    for cam in CAMERAS:
        try:
            process_camera(cam, state)
        except subprocess.CalledProcessError as e:
            any_error = True
            stderr = (e.stderr or "").strip()
            stdout = (e.stdout or "").strip()
            log(f"ERROR: {cam['name']} curl failed with return code {e.returncode}")
            if stderr:
                log(f"ERROR: stderr: {stderr}")
            if stdout:
                log(f"ERROR: stdout: {stdout}")
        except Exception as e:
            any_error = True
            log(f"ERROR: {cam['name']} unexpected failure: {e}")

    save_state(state)
    return 1 if any_error else 0


if __name__ == "__main__":
    sys.exit(main())