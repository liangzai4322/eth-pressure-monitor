import json
import os
import shlex


ROTATION_CONFIRMATION = "I_UNDERSTAND_THIS_ROTATES_SYNC_TOKEN"
NEW_TOKEN = os.environ.get("ETH_MONITOR_SYNC_TOKEN_OVERRIDE", "").strip()
ACK = os.environ.get("ETH_MONITOR_ALLOW_TOKEN_ROTATION", "").strip()

if not NEW_TOKEN:
    raise SystemExit("ETH_MONITOR_SYNC_TOKEN_OVERRIDE is empty")
if ACK != ROTATION_CONFIRMATION:
    raise SystemExit(
        "sync token rotation is locked; set ETH_MONITOR_ALLOW_TOKEN_ROTATION="
        + ROTATION_CONFIRMATION
        + " only after the user explicitly requests rotation in the current task"
    )

HOST = os.environ["ETH_MONITOR_SERVER_HOST"]
USER = os.environ["ETH_MONITOR_SERVER_USER"]
PASSWORD = os.environ["ETH_MONITOR_SERVER_PASSWORD"]

import paramiko


def quote(value):
    return shlex.quote(str(value))


client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username=USER, password=PASSWORD, timeout=20)
sftp = client.open_sftp()


def run(command, check=True):
    _, stdout, stderr = client.exec_command(command)
    code = stdout.channel.recv_exit_status()
    output = stdout.read().decode("utf-8", "replace").strip()
    error = stderr.read().decode("utf-8", "replace").strip()
    if check and code:
        raise RuntimeError(f"remote command failed ({code}): {error or output}")
    return output, error, code


with sftp.file("/etc/eth-monitor-api.env", "rb") as handle:
    current = handle.read().decode("utf-8", "replace")

old_token = ""
updated = []
replaced = False
for line in current.splitlines():
    if line.startswith("ETH_MONITOR_SYNC_TOKEN="):
        old_token = line.split("=", 1)[1]
        updated.append(f"ETH_MONITOR_SYNC_TOKEN={NEW_TOKEN}")
        replaced = True
    else:
        updated.append(line)
if not replaced:
    updated.append(f"ETH_MONITOR_SYNC_TOKEN={NEW_TOKEN}")

with sftp.file("/tmp/eth-monitor-api.env", "wb") as handle:
    handle.write(("\n".join(updated) + "\n").encode("utf-8"))

run("install -o root -g ethmonitor -m 640 /tmp/eth-monitor-api.env /etc/eth-monitor-api.env")
run("rm -f /tmp/eth-monitor-api.env")
run("systemctl restart eth-monitor-api eth-monitor-event-consumer")

api_status, _, _ = run("systemctl is-active eth-monitor-api")
consumer_status, _, _ = run("systemctl is-active eth-monitor-event-consumer")
health, _, _ = run("curl -fsS http://127.0.0.1:8765/health")
new_http, _, _ = run(
    "curl -sS -o /dev/null -w '%{http_code}' -H "
    + quote(f"Authorization: Bearer {NEW_TOKEN}")
    + " http://127.0.0.1:8765/api/state"
)
old_http = "not-tested"
if old_token and old_token != NEW_TOKEN:
    old_http, _, _ = run(
        "curl -sS -o /dev/null -w '%{http_code}' -H "
        + quote(f"Authorization: Bearer {old_token}")
        + " http://127.0.0.1:8765/api/state",
        check=False,
    )

sftp.close()
client.close()

print(json.dumps({
    "ok": new_http == "200" and api_status == "active" and consumer_status == "active",
    "api_service": api_status,
    "consumer_service": consumer_status,
    "health": json.loads(health),
    "new_token_http": int(new_http),
    "old_token_http": int(old_http) if old_http.isdigit() else old_http,
}, ensure_ascii=False, indent=2))
