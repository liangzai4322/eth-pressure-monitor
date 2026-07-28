#!/usr/bin/env python3
import hashlib
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

EVENT_LOG = Path(os.environ.get(
    "ETH_SOURCE_EVENT_LOG",
    "/opt/eth-key-event-monitor/events.jsonl",
))
STATE_FILE = Path(os.environ.get(
    "ETH_CONSUMER_STATE",
    "/var/lib/eth-monitor-api/event-consumer-state.json",
))
API = os.environ.get("ETH_MONITOR_LOCAL_API", "http://127.0.0.1:8765/api")
TOKEN = os.environ["ETH_MONITOR_SYNC_TOKEN"]
INTERVAL = max(2, int(os.environ.get("ETH_CONSUMER_INTERVAL", "5")))


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
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def event_key(event):
    stable = event.get("summaryContentId")
    if stable:
        return str(stable)
    material = "|".join(
        str(event.get(key, ""))
        for key in ("instId", "timeStamp", "type", "newTitle", "eventDetail")
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def amount_eth(event):
    for field in ("newTitle", "newContent", "eventDetail"):
        match = re.search(
            r"([\d,]+(?:\.\d+)?)\s*ETH\b",
            str(event.get(field) or ""),
            re.IGNORECASE,
        )
        if match:
            return float(match.group(1).replace(",", ""))
    return None


def eligible(event):
    if str(event.get("summaryContentId") or "").startswith("ACC-"):
        return False
    if str(event.get("instId", "")).upper() != "ETH-USDT":
        return False
    type_title = str(event.get("typeTitle") or "").lower()
    title = str(event.get("newTitle") or "").lower()
    return (
        "交易所转入" in type_title
        or "exchange inflow" in type_title
        or ("划转" in title and " eth" in title)
    )


def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_state(value):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def initialize():
    stat = EVENT_LOG.stat()
    state = {
        "initialized": True,
        "inode": stat.st_ino,
        "offset": stat.st_size,
        "lastReadAt": datetime.now(timezone.utc).isoformat(),
    }
    save_state(state)
    return state


def consume_once():
    if not EVENT_LOG.exists():
        raise FileNotFoundError(EVENT_LOG)
    stat = EVENT_LOG.stat()
    state = load_state()
    if not state:
        state = initialize()
        post("/collector", {
            "last_poll": datetime.now(timezone.utc).isoformat(),
            "events_seen": 0,
            "eligible_events": 0,
            "source": str(EVENT_LOG),
            "last_error": "",
        })
        return {"baseline": True, "lines": 0, "ingested": 0}
    if state.get("inode") != stat.st_ino or int(state.get("offset", 0)) > stat.st_size:
        state = initialize()
        return {"rebaselined": True, "lines": 0, "ingested": 0}

    offset = int(state.get("offset", 0))
    lines = eligible_count = ingested = 0
    with EVENT_LOG.open("rb") as handle:
        handle.seek(offset)
        while True:
            before = handle.tell()
            raw = handle.readline()
            if not raw:
                break
            if not raw.endswith(b"\n"):
                handle.seek(before)
                break
            offset = handle.tell()
            lines += 1
            try:
                record = json.loads(raw.decode("utf-8"))
                event = record.get("event", {})
                amount = amount_eth(event)
                if not eligible(event) or amount is None:
                    continue
                eligible_count += 1
                result = post("/inflow", {
                    "event_id": event_key(event),
                    "amount_eth": amount,
                    "event_timestamp": event.get("timeStamp") or time.time(),
                    "title": str(event.get("newTitle") or "ETH 交易所转入"),
                    "source": str(EVENT_LOG),
                })
                if result.get("ok") and not result.get("duplicate"):
                    ingested += 1
            except Exception as exc:
                print(f"skip malformed event line at {before}: {exc}", flush=True)
    state.update({
        "inode": stat.st_ino,
        "offset": offset,
        "lastReadAt": datetime.now(timezone.utc).isoformat(),
    })
    save_state(state)
    post("/collector", {
        "last_poll": state["lastReadAt"],
        "events_seen": lines,
        "eligible_events": eligible_count,
        "source": str(EVENT_LOG),
        "last_error": "",
    })
    return {"baseline": False, "lines": lines, "eligible": eligible_count, "ingested": ingested}


def main():
    while True:
        try:
            print(json.dumps(consume_once(), ensure_ascii=False), flush=True)
        except Exception as exc:
            print(f"event consumer error: {exc}", flush=True)
            try:
                post("/collector", {
                    "last_poll": datetime.now(timezone.utc).isoformat(),
                    "events_seen": 0,
                    "eligible_events": 0,
                    "source": str(EVENT_LOG),
                    "last_error": str(exc),
                })
            except Exception:
                pass
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
