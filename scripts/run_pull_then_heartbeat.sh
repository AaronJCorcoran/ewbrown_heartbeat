#!/bin/bash
set -u

/usr/bin/python3 /home/admin/fieldcam/scripts/pull_axis_recordings.py
pull_rc=$?

/usr/bin/python3 /home/admin/fieldcam/scripts/heartbeat_status.py --pull-exit-code "$pull_rc" || true

exit $pull_rc
