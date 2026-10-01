"""Minimal standard-library HTTP adapter for the TAV MVP."""

from __future__ import annotations

from collections import defaultdict, deque
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import hmac
import json
import re
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tav_core import RequestError, evaluate

MAX_BODY = 64 * 1024
RATE_LIMIT = 60
RATE_WINDOW = 60
_requests: dict[str, deque[float]] = defaultdict(deque)
MAX_RATE_CLIENTS = 10000


def _usage_db() -> Path:
    return Path(os.environ.get("TAV_USAGE_DB", "usage.sqlite3"))


def _api_key_id(supplied_header: str) -> str | None:
    """Resolve bearer credentials against SHA-256 digests in TAV_API_KEYS."""
    if not supplied_header.startswith("Bearer "):
        return None
    token = supplied_header[7:]
    configured = os.environ.get("TAV_API_KEYS", "")
    if configured:
        try:
            key_map = json.loads(configured)
        except json.JSONDecodeError as exc:
            raise RuntimeError("TAV_API_KEYS must be a JSON object of client_id to SHA-256 hex digest") from exc
        if not isinstance(key_map, dict):
            raise RuntimeError("TAV_API_KEYS must be a JSON object")
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        for client_id, expected_digest in key_map.items():
            if not isinstance(client_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", client_id):
                continue
            if isinstance(expected_digest, str) and hmac.compare_digest(digest, expected_digest.lower()):
                return client_id
        return None
    # Single-key mode is for local development and backwards-compatible self-hosting.
    expected = os.environ.get("TAV_API_KEY", "")
    return "default" if expected and hmac.compare_digest(token, expected) else None


def _record_usage(client_id: str, kind: str) -> None:
    """Persist aggregate counters only; never store request content or answers."""
    path = _usage_db()
    path.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).date().isoformat()
    with closing(sqlite3.connect(path, timeout=5)) as connection:
        with connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS daily_usage (
                day TEXT NOT NULL, client_id TEXT NOT NULL, requests INTEGER NOT NULL DEFAULT 0,
                successful INTEGER NOT NULL DEFAULT 0, client_errors INTEGER NOT NULL DEFAULT 0,
                rate_limited INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(day, client_id))""")
            columns = {"success": "successful", "client_error": "client_errors", "rate_limited": "rate_limited"}
            if kind not in {"success", "client_error", "rate_limited", "server_error"}:
                raise ValueError("invalid usage event")
            connection.execute("DELETE FROM daily_usage WHERE day < ?", ((datetime.now(timezone.utc).date() - timedelta(days=89)).isoformat(),))
            connection.execute("INSERT OR IGNORE INTO daily_usage(day, client_id) VALUES(?, ?)", (today, client_id))
            column = columns.get(kind)
            if column:
                connection.execute(f"UPDATE daily_usage SET requests=requests+1, {column}={column}+1 WHERE day=? AND client_id=?", (today, client_id))
            else:
                connection.execute("UPDATE daily_usage SET requests=requests+1 WHERE day=? AND client_id=?", (today, client_id))


def _read_usage(client_id: str) -> dict[str, int | str]:
    path = _usage_db()
    today = datetime.now(timezone.utc).date().isoformat()
    if not path.exists():
        return {"date_utc": today, "requests": 0, "successful": 0, "client_errors": 0, "rate_limited": 0}
    with closing(sqlite3.connect(path, timeout=5)) as connection:
        row = connection.execute(
            "SELECT day, requests, successful, client_errors, rate_limited FROM daily_usage WHERE day=? AND client_id=?",
            (today, client_id),
        ).fetchone()
    if not row:
        return {"date_utc": today, "requests": 0, "successful": 0, "client_errors": 0, "rate_limited": 0}
    if row[0] != today:
        return {"date_utc": today, "requests": 0, "successful": 0, "client_errors": 0, "rate_limited": 0}
    return {"date_utc": row[0], "requests": row[1], "successful": row[2], "client_errors": row[3], "rate_limited": row[4]}


class Handler(BaseHTTPRequestHandler):
    server_version = "TAV/0.1"

    def log_message(self, fmt: str, *args: object) -> None:
        # Avoid default logging of client address and request details.
        return

    def _send(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, code: str, message: str) -> None:
        self._send(status, {"error": {"code": code, "message": message}})

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send(200, {"status": "ok"})
            return
        if self.path == "/v1/usage":
            client_id = _api_key_id(self.headers.get("Authorization", ""))
            if client_id is None:
                self._error(401, "unauthorized", "A valid bearer API key is required")
                return
            self._send(200, _read_usage(client_id))
            return
        self._error(404, "not_found", "Route not found")

    def do_POST(self) -> None:
        if self.path != "/v1/evaluate":
            self._error(404, "not_found", "Route not found")
            return
        client_id = _api_key_id(self.headers.get("Authorization", ""))
        if client_id is None:
            self._error(401, "unauthorized", "A valid bearer API key is required")
            return

        now = time.monotonic()
        if client_id not in _requests and len(_requests) >= MAX_RATE_CLIENTS:
            _requests.pop(next(iter(_requests)))
        history = _requests[client_id]
        while history and now - history[0] >= RATE_WINDOW:
            history.popleft()
        if len(history) >= RATE_LIMIT:
            _record_usage(client_id, "rate_limited")
            self._error(429, "rate_limited", "Request limit exceeded")
            return
        history.append(now)

        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            _record_usage(client_id, "client_error")
            self._error(400, "invalid_content_length", "Content-Length must be an integer")
            return
        if length < 0:
            _record_usage(client_id, "client_error")
            self._error(400, "content_length_required", "Content-Length is required")
            return
        if length > MAX_BODY:
            _record_usage(client_id, "client_error")
            self._error(413, "body_too_large", "Request body exceeds 64 KiB")
            return
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            _record_usage(client_id, "client_error")
            self._error(415, "unsupported_media_type", "Content-Type must be application/json")
            return
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            _record_usage(client_id, "client_error")
            self._error(400, "invalid_json", "Body must be valid UTF-8 JSON")
            return
        try:
            result = evaluate(payload)
        except RequestError as exc:
            _record_usage(client_id, "client_error")
            self._error(400, "invalid_request", str(exc))
            return
        _record_usage(client_id, "success")
        self._send(200, result)

    def do_PUT(self) -> None:
        self._error(405, "method_not_allowed", "Method not allowed")

    do_PATCH = do_PUT
    do_DELETE = do_PUT


def main() -> None:
    key = os.environ.get("TAV_API_KEY", "")
    key_map = os.environ.get("TAV_API_KEYS", "")
    if key_map:
        try:
            parsed_keys = json.loads(key_map)
        except json.JSONDecodeError:
            raise SystemExit("TAV_API_KEYS must be JSON mapping client IDs to SHA-256 digests") from None
        if not isinstance(parsed_keys, dict) or not parsed_keys:
            raise SystemExit("TAV_API_KEYS must contain at least one client key")
        if any(
            not isinstance(client_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", client_id)
            or not isinstance(digest, str)
            or not re.fullmatch(r"[a-fA-F0-9]{64}", digest)
            for client_id, digest in parsed_keys.items()
        ):
            raise SystemExit("TAV_API_KEYS entries must use valid client IDs and 64-character SHA-256 hex digests")
    elif len(key) < 24:
        raise SystemExit("Set TAV_API_KEYS or TAV_API_KEY (at least 24 characters for single-key mode)")
    host = os.environ.get("TAV_HOST", "127.0.0.1")
    port = int(os.environ.get("TAV_PORT", "8080"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"TAV listening on {host}:{port}; request bodies are not logged")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
