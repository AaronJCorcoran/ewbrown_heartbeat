#!/bin/bash
set -u

SSD_MOUNT="/mnt/video_ssd"

if mountpoint -q "$SSD_MOUNT"; then
    /usr/bin/python3 /home/admin/fieldcam/scripts/pull_axis_recordings.py
    pull_rc=$?
else
    echo "ERROR: $SSD_MOUNT is not a mounted filesystem -- skipping pull" >&2
    logger -t fieldcam "SSD not mounted at $SSD_MOUNT -- pull skipped"
    pull_rc=99
fi

/usr/bin/python3 /home/admin/fieldcam/scripts/heartbeat_status.py --pull-exit-code "$pull_rc" || true

exit $pull_rc
