EW Brown heartbeat bundle
=========================

This bundle adds a daily heartbeat/status layer on top of the existing Axis recording pull workflow.
It is designed to leave the existing pull/export script intact.

Files in this bundle
--------------------

1. config/heartbeat.env.example
   Copy to: /home/admin/fieldcam/config/heartbeat.env
   Purpose: local configuration and secret placeholders.

2. scripts/run_pull_then_heartbeat.sh
   Copy to: /home/admin/fieldcam/scripts/run_pull_then_heartbeat.sh
   Purpose: wrapper that runs the pull script first, captures its exit code, then runs heartbeat_status.py.

3. scripts/heartbeat_status.py
   Copy to: /home/admin/fieldcam/scripts/heartbeat_status.py
   Purpose: generates local heartbeat JSON/text output and optional email.

4. systemd/pull-axis-recordings.service
   Copy to: /etc/systemd/system/pull-axis-recordings.service
   Purpose: updates the existing pull service so the timer fires the wrapper instead of the Python pull script directly.

Target directories on the Pi
----------------------------

/home/admin/fieldcam/config
/home/admin/fieldcam/scripts
/home/admin/fieldcam/state
/home/admin/fieldcam/logs

Create the directories on the Pi
--------------------------------

sudo mkdir -p /home/admin/fieldcam/{config,scripts,state,logs}
sudo chown -R admin:admin /home/admin/fieldcam
sudo chmod 700 /home/admin/fieldcam/config
sudo chmod 755 /home/admin/fieldcam/scripts /home/admin/fieldcam/state /home/admin/fieldcam/logs

Install the files on the Pi
---------------------------

1. Copy heartbeat.env.example to:
   /home/admin/fieldcam/config/heartbeat.env

2. Edit /home/admin/fieldcam/config/heartbeat.env and set real values for:
   - AXIS_PASSWORD
   - SMTP_* values if email will be enabled later

3. Copy run_pull_then_heartbeat.sh to:
   /home/admin/fieldcam/scripts/run_pull_then_heartbeat.sh

4. Copy heartbeat_status.py to:
   /home/admin/fieldcam/scripts/heartbeat_status.py

5. Copy pull-axis-recordings.service to:
   /etc/systemd/system/pull-axis-recordings.service

Set permissions on the Pi
-------------------------

sudo chown admin:admin /home/admin/fieldcam/config/heartbeat.env
sudo chmod 600 /home/admin/fieldcam/config/heartbeat.env

sudo chown admin:admin /home/admin/fieldcam/scripts/run_pull_then_heartbeat.sh
sudo chmod 755 /home/admin/fieldcam/scripts/run_pull_then_heartbeat.sh

sudo chown admin:admin /home/admin/fieldcam/scripts/heartbeat_status.py
sudo chmod 755 /home/admin/fieldcam/scripts/heartbeat_status.py

sudo chown root:root /etc/systemd/system/pull-axis-recordings.service
sudo chmod 644 /etc/systemd/system/pull-axis-recordings.service

Reload and test
---------------

sudo systemctl daemon-reload
sudo systemctl start pull-axis-recordings.service
journalctl -u pull-axis-recordings.service -n 100 --no-pager

Check heartbeat outputs
-----------------------

cat /home/admin/fieldcam/state/last_heartbeat.txt
jq . /home/admin/fieldcam/state/last_heartbeat.json
tail -n 100 /home/admin/fieldcam/logs/heartbeat_status.log

Notes
-----

- The existing timer can remain unchanged.
- This heartbeat script can use /home/admin/fieldcam/state/last_pull_status.json if the pull script is later enhanced to write a structured run summary.
- Until then, the heartbeat still reports camera reachability, active/completed counts, disk usage, recent pull errors, and latest files on SSD.
