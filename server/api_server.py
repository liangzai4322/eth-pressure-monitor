#!/usr/bin/env python3
import json
import os
import secrets
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(os.environ.get("ETH_MONITOR_DATA_DIR", "/var/lib/eth-monitor-api"))
STATE_FILE = ROOT / "state.json"
LOG_FILE = ROOT / "ETH_monitor_log.jsonl"
SYNC_TOKEN = os.environ["ETH_MONITOR_SYNC_TOKEN"]
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
ALLOWED_ORIGINS = {
    "https://liangzai4322.github.io",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "null",
}
LOCK = threading.RLock()
MAX_BODY = 4 * 1024 * 1024


def atomic_json_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_envelope():
    if STATE_FILE.exists():
        with STATE_FILE.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
            if isinstance(value, dict) and "state" in value:
                return value
    return {"revision": 0, "updated_at": "", "updated_by": "", "state": None}


def scrub_state(value):
    if not isinstance(value, dict):
        raise ValueError("state must be an object")
    clean = json.loads(json.dumps(value, ensure_ascii=False))
    for key in list(clean):
        if "key" in key.lower() or "token" in key.lower() or "password" in key.lower():
            clean.pop(key, None)
    clean["undo"] = None
    logs = clean.get("logs", [])
    if not isinstance(logs, list):
        raise ValueError("state.logs must be an array")
    if len(logs) > 2000:
        clean["logs"] = logs[-2000:]
    return clean


def append_new_logs(previous, current):
    old_ids = {
        item.get("id") for item in (previous or {}).get("logs", [])
        if isinstance(item, dict) and item.get("id")
    }
    fresh = [
        item for item in current.get("logs", [])
        if isinstance(item, dict) and item.get("id") not in old_ids
    ]
    if fresh:
        ROOT.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8", newline="\n") as handle:
            for item in fresh:
                handle.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


class Handler(BaseHTTPRequestHandler):
    server_version = "ETHMonitorAPI/1.0"

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}", flush=True)

    def cors(self):
        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-DeepSeek-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, POST, OPTIONS")
        self.send_header("Access-Control-Max-Age", "86400")

    def json_response(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        auth = self.headers.get("Authorization", "")
        return auth.startswith("Bearer ") and secrets.compare_digest(auth[7:], SYNC_TOKEN)

    def body_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_BODY:
            raise ValueError("invalid body size")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            return self.json_response(200, {"ok": True, "service": "eth-monitor-api", "time": int(time.time())})
        if self.path.rstrip("/") != "/api/state":
            return self.json_response(404, {"ok": False, "error": "not_found"})
        if not self.authorized():
            return self.json_response(401, {"ok": False, "error": "unauthorized"})
        with LOCK:
            envelope = load_envelope()
        return self.json_response(200, {"ok": True, **envelope})

    def do_PUT(self):
        if self.path.rstrip("/") != "/api/state":
            return self.json_response(404, {"ok": False, "error": "not_found"})
        if not self.authorized():
            return self.json_response(401, {"ok": False, "error": "unauthorized"})
        try:
            payload = self.body_json()
            incoming = scrub_state(payload.get("state"))
            base_revision = int(payload.get("base_revision", -1))
            device_id = str(payload.get("device_id", ""))[:100]
        except Exception as exc:
            return self.json_response(400, {"ok": False, "error": "invalid_payload", "detail": str(exc)})
        with LOCK:
            current = load_envelope()
            if base_revision != current["revision"]:
                return self.json_response(409, {"ok": False, "error": "revision_conflict", **current})
            append_new_logs(current.get("state"), incoming)
            envelope = {
                "revision": current["revision"] + 1,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "updated_by": device_id,
                "state": incoming,
            }
            atomic_json_write(STATE_FILE, envelope)
        return self.json_response(200, {"ok": True, **envelope})

    def do_POST(self):
        if self.path.rstrip("/") != "/api/parse":
            return self.json_response(404, {"ok": False, "error": "not_found"})
        if not self.authorized():
            return self.json_response(401, {"ok": False, "error": "unauthorized"})
        try:
            payload = self.body_json()
            text = str(payload.get("text", "")).strip()
            system_prompt = str(payload.get("system_prompt", ""))
            model = str(payload.get("model", "deepseek-v4-flash"))
            api_key = self.headers.get("X-DeepSeek-Key", "") or DEEPSEEK_KEY
            if not text or len(text) > 8000:
                raise ValueError("text length is invalid")
            if model not in {"deepseek-v4-flash", "deepseek-v4-pro"}:
                raise ValueError("model is invalid")
            if not api_key:
                return self.json_response(503, {"ok": False, "error": "deepseek_key_missing"})
            request_body = json.dumps({
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                "response_format": {"type": "json_object"},
                "thinking": {"type": "disabled"},
                "temperature": 0.1,
                "max_tokens": 1200,
            }, ensure_ascii=False).encode("utf-8")
            request = urllib.request.Request(
                "https://api.deepseek.com/chat/completions",
                data=request_body,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                    "User-Agent": "ETHMonitorAPI/1.0",
                },
            )
            with urllib.request.urlopen(request, timeout=45) as response:
                result = json.loads(response.read().decode("utf-8"))
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not content:
                raise ValueError("DeepSeek returned empty content")
            parsed = json.loads(content)
            return self.json_response(200, {"ok": True, "result": parsed, "model": model})
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:1000]
            return self.json_response(502, {"ok": False, "error": "deepseek_http_error", "status": exc.code, "detail": detail})
        except Exception as exc:
            return self.json_response(400, {"ok": False, "error": "parse_failed", "detail": str(exc)})


if __name__ == "__main__":
    ROOT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    print("ETH monitor API listening on 127.0.0.1:8765", flush=True)
    server.serve_forever()
