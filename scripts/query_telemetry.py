"""Query Cloudflare Analytics Engine without persisting the API token."""

from __future__ import annotations

import getpass
import json
import os
import sys
from urllib.request import Request, urlopen


QUERY = """
SELECT
  toStartOfDay(timestamp) AS day,
  blob1 AS version,
  blob2 AS outcome,
  SUM(double1 * _sample_interval) AS calls,
  COUNT(DISTINCT index1) AS active_installations
FROM tav_mcp_usage
WHERE timestamp > NOW() - INTERVAL '90' DAY
GROUP BY day, version, outcome
ORDER BY day DESC, version, outcome
FORMAT JSON
""".strip()


def main() -> int:
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "3723bfb3f71e2120e3ed1391fa2ea566")
    token = getpass.getpass("Cloudflare Account Analytics Read token (input hidden): ").strip()
    if not token:
        print("No token provided.", file=sys.stderr)
        return 2
    request = Request(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/analytics_engine/sql",
        data=QUERY.encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "text/plain"},
        method="POST",
    )
    with urlopen(request, timeout=20) as response:
        result = json.loads(response.read().decode("utf-8"))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
