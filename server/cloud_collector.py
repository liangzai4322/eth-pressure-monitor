#!/usr/bin/env python3
import argparse
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import monitor

CONFIG = Path(os.environ.get("ETH_COLLECTOR_CONFIG", "/etc/eth-monitor-collector.json"))
STATE = Path(os.environ.get("ETH_COLLECTOR_STATE", "/var/lib/eth-monitor-api/collector-state.json"))
API = os.environ.get("ETH_MONITOR_LOCAL_API", "http://127.0.0.1:8765/api")
TOKEN = os.environ["ETH_MONITOR_SYNC_TOKEN"]


def post(path, payload):
    request = urllib.request.Request(
        API + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {TOKEN}",
        },
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"initialized": False, "seen": []}


def save_state(value):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, STATE)


def poll(config, bootstrap_only=False):
    payload, source_url = monitor.fetch(config)
    events = monitor.extract_events(payload)
    state = load_state()
    seen = set(map(str, state.get("seen", [])))
    initialized = bool(state.get("initialized"))
    eligible = 0
    ingested = 0
    for event in reversed(events):
        key = monitor.event_key(event)
        if key in seen:
            continue
        seen.add(key)
        amount = monitor.extract_eth_amount(event)
        if amount is None or not monitor.is_eth_exchange_inflow(event):
            continue
        eligible += 1
        if initialized and not bootstrap_only:
            title, _ = monitor.event_text(event)
            result = post("/inflow", {
                "event_id": key,
                "amount_eth": amount,
                "event_timestamp": event.get("timeStamp") or time.time(),
                "title": title,
                "source": source_url,
            })
            if result.get("ok") and not result.get("duplicate"):
                ingested += 1
    max_seen = int(config.get("max_seen_items", 5000))
    save_state({
        "initialized": True,
        "lastPollAt": datetime.now(timezone.utc).isoformat(),
        "seen": list(seen)[-max_seen:],
    })
    status = {
        "last_poll": datetime.now(timezone.utc).isoformat(),
        "events_seen": len(events),
        "eligible_events": eligible,
        "source": source_url,
        "last_error": "",
    }
    post("/collector", status)
    print(json.dumps({**status, "ingested": ingested, "bootstrap": not initialized}, ensure_ascii=False), flush=True)
    return ingested


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--reset-bootstrap", action="store_true")
    args = parser.parse_args()
    config = monitor.load_json(CONFIG, None)
    if not isinstance(config, dict):
        raise SystemExit(f"Invalid collector config: {CONFIG}")
    if args.reset_bootstrap and STATE.exists():
        STATE.unlink()
    interval = max(15, int(config.get("poll_seconds", 60)))
    while True:
        try:
            poll(config)
        except Exception as exc:
            print(f"collector error: {exc}", flush=True)
            try:
                post("/collector", {
                    "last_poll": datetime.now(timezone.utc).isoformat(),
                    "events_seen": 0,
                    "eligible_events": 0,
                    "source": "",
                    "last_error": str(exc),
                })
            except Exception:
                pass
            if args.once:
                raise
        if args.once:
            return
        time.sleep(interval)


if __name__ == "__main__":
    main()
