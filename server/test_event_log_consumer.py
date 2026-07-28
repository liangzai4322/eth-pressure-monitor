import json
import os
import shutil
from pathlib import Path

os.environ.setdefault("ETH_MONITOR_SYNC_TOKEN", "test-token")
import event_log_consumer as consumer


def record(event):
    return json.dumps({"observedAt": "2026-07-28T00:00:00Z", "event": event}, ensure_ascii=False) + "\n"


root = Path(__file__).with_name(".test-event-consumer")
if root.exists():
    shutil.rmtree(root)
root.mkdir()
try:
    consumer.EVENT_LOG = root / "events.jsonl"
    consumer.STATE_FILE = root / "state.json"
    calls = []
    consumer.post = lambda path, payload: calls.append((path, payload)) or {"ok": True, "duplicate": False}

    historical = {
        "instId": "ETH-USDT",
        "typeTitle": "交易所转入",
        "newTitle": "钱包向交易所划转了 1,000 ETH",
        "timeStamp": 1,
    }
    consumer.EVENT_LOG.write_text(record(historical), encoding="utf-8")
    first = consumer.consume_once()
    assert first["baseline"] is True
    assert not [item for item in calls if item[0] == "/inflow"]

    real = {
        "instId": "ETH-USDT",
        "typeTitle": "交易所转入",
        "newTitle": "钱包向交易所划转了 2,500 ETH",
        "timeStamp": 2,
    }
    aggregate = {
        **real,
        "summaryContentId": "ACC-test",
        "newContent": "本批次累计 8,000 ETH",
    }
    etf = {
        "instId": "ETH-USDT",
        "typeTitle": "美股 ETF",
        "newTitle": "ETH 每日净流入 5,000 ETH",
        "timeStamp": 3,
    }
    with consumer.EVENT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(record(real))
        handle.write(record(aggregate))
        handle.write(record(etf))

    second = consumer.consume_once()
    inflows = [payload for path, payload in calls if path == "/inflow"]
    assert second["lines"] == 3
    assert second["eligible"] == 1
    assert second["ingested"] == 1
    assert len(inflows) == 1
    assert inflows[0]["amount_eth"] == 2500
finally:
    shutil.rmtree(root)

print(json.dumps({"ok": True, "baseline": "eof", "real_inflows": 1, "aggregate_excluded": True, "etf_excluded": True}))
