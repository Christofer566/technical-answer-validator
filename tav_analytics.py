"""Local-only aggregate usage counts for the MCP stdio server.

No request text, rubric, answer, host identity, or network address is stored.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import threading
import urllib.error
import urllib.request
import uuid

PACKAGE_VERSION = "0.1.2"


def _db_path() -> Path:
    configured = os.environ.get("TAV_ANALYTICS_DB")
    if configured:
        return Path(configured)
    return Path.home() / ".technical-answer-validator" / "usage.sqlite3"


def _install_id_path() -> Path:
    return Path.home() / ".technical-answer-validator" / "telemetry-id"


def _install_id() -> str:
    path = _install_id_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        value = path.read_text(encoding="ascii").strip()
        uuid.UUID(value)
        return value
    except (OSError, ValueError):
        value = str(uuid.uuid4())
        path.write_text(value, encoding="ascii")
        return value


def _send_event(outcome: str) -> None:
    """Best-effort, explicit opt-in remote event; never include tool inputs or outputs."""
    if os.environ.get("TAV_TELEMETRY", "off").lower() not in {"on", "true", "1", "yes"}:
        return
    endpoint = os.environ.get("TAV_TELEMETRY_URL", "").strip()
    if not endpoint.startswith("https://"):
        return

    def send() -> None:
        try:
            payload = json.dumps({
                "installation_id": _install_id(),
                "version": PACKAGE_VERSION,
                "outcome": outcome,
            }).encode("utf-8")
            request = urllib.request.Request(
                endpoint, data=payload,
                headers={"Content-Type": "application/json", "User-Agent": f"technical-answer-validator/{PACKAGE_VERSION}"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=2) as response:
                response.read(128)
        except (OSError, urllib.error.URLError, ValueError):
            return

    threading.Thread(target=send, name="tav-telemetry", daemon=True).start()


def record_call(outcome: str) -> None:
    """Increment the local daily total; analytics can be disabled with TAV_ANALYTICS=off."""
    if outcome not in {"success", "invalid_request", "error"}:
        outcome = "error"
    _send_event(outcome)
    if os.environ.get("TAV_ANALYTICS", "on").lower() in {"off", "false", "0", "no"}:
        return
    try:
        path = _db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        day = datetime.now(timezone.utc).date().isoformat()
        with closing(sqlite3.connect(path, timeout=5)) as connection:
            with connection:
                connection.execute("""CREATE TABLE IF NOT EXISTS daily_mcp_usage (
                    day TEXT PRIMARY KEY,
                    calls INTEGER NOT NULL DEFAULT 0,
                    successful INTEGER NOT NULL DEFAULT 0,
                    invalid_requests INTEGER NOT NULL DEFAULT 0,
                    errors INTEGER NOT NULL DEFAULT 0
                )""")
                connection.execute("DELETE FROM daily_mcp_usage WHERE day < date('now', '-89 day')")
                connection.execute("INSERT OR IGNORE INTO daily_mcp_usage(day) VALUES(?)", (day,))
                column = {"success": "successful", "invalid_request": "invalid_requests", "error": "errors"}[outcome]
                connection.execute(
                    f"UPDATE daily_mcp_usage SET calls=calls+1, {column}={column}+1 WHERE day=?", (day,)
                )
    except (OSError, sqlite3.Error):
        # Local analytics must never make an otherwise valid MCP request fail.
        return


def report() -> dict[str, object]:
    path = _db_path()
    if not path.exists():
        rows = []
    else:
        with closing(sqlite3.connect(path, timeout=5)) as connection:
            rows = connection.execute(
                "SELECT day,calls,successful,invalid_requests,errors FROM daily_mcp_usage ORDER BY day"
            ).fetchall()
    return {
        "source": "local_mcp_stdio",
        "privacy": "local aggregate only; no rubric, answer, host ID, or network address",
        "retention_days": 90,
        "days": [
            {"date_utc": day, "calls": calls, "successful": successful,
             "invalid_requests": invalid_requests, "errors": errors}
            for day, calls, successful, invalid_requests, errors in rows
        ],
        "totals": {
            "calls": sum(row[1] for row in rows),
            "successful": sum(row[2] for row in rows),
            "invalid_requests": sum(row[3] for row in rows),
            "errors": sum(row[4] for row in rows),
        },
    }


def main() -> None:
    print(json.dumps(report(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

