# Technical Answer Validator

<!-- mcp-name: io.github.Christofer566/technical-answer-validator -->

A tiny, deterministic answer review tool for AI agents, available over **MCP stdio** and as a REST API. Each caller supplies the concepts, accepted synonyms, numeric requirements, and answer text for a single evaluation. It does not include a question bank or answer corpus.

This is an **assistive practice tool**, not an official certification exam grader. Keyword matching can miss semantically correct paraphrases and can accept misleading surface matches. Users should review the supplied rubric and every result.

## Run locally

Python 3.10+; the REST server uses the standard library. The MCP adapter uses the official Python SDK 2.2.0.

```powershell
$env:TAV_API_KEY = "replace-with-a-long-random-secret-at-least-24-characters"
python -m tav_api
```

The service listens on `127.0.0.1:8080` by default. To change it, set `TAV_HOST` and `TAV_PORT`. Local single-key mode refuses to start without a `TAV_API_KEY` of at least 24 characters. For deployment, create a distinct key per caller with `python scripts/create_api_key.py CLIENT_ID` and configure `TAV_API_KEYS` as a JSON object mapping each client ID to the generated SHA-256 digest. Store the one-time raw key with that client; do not store or commit it in this repository. When `TAV_API_KEYS` is set, it takes precedence over `TAV_API_KEY`.

## MCP for AI agents

Install the pinned MCP SDK 2.2.0 in a virtual environment from the committed lockfile:

```powershell
uv sync --locked
.\.venv\Scripts\Activate.ps1
```

The stdio MCP server exposes one tool: `evaluate_answer(rubric, answer)`. Configure an MCP host with the absolute path to the environment's Python and `mcp_server.py`. Example Claude Desktop configuration (replace paths):

```json
{
  "mcpServers": {
    "technical-answer-validator": {
      "command": "C:\\path\\to\\technical-answer-validator\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\technical-answer-validator\\mcp_server.py"]
    }
  }
}
```

After publishing to PyPI, run with `uvx --from technical-answer-validator tav-mcp`. For local development use the `.venv` Python plus `mcp_server.py`. For Codex CLI or another MCP host, use its stdio server configuration with that command and script path. Restart the host, then ask it to list tools and call `evaluate_answer`. The stdio transport is local to the user's agent host and needs no internet endpoint or API key.

The Codex TOML template is `codex-mcp-config.example.toml`; the Claude Desktop JSON template is `claude-mcp-config.example.json`. Replace both placeholder paths with absolute paths. Merge the block into the host configuration; do not overwrite other MCP servers or global settings.

### Local MCP usage counts

The MCP server keeps local daily aggregate counts for tool calls, successful evaluations, invalid requests, and internal errors. It never stores rubric or answer text and sends nothing over the network. Counts are retained for 90 days in `~/.technical-answer-validator/usage.sqlite3` (Windows: the user's home directory). Run `tav-mcp-stats` to print a JSON report. Set `TAV_ANALYTICS=off` in the MCP server environment to disable counting; set `TAV_ANALYTICS_DB` to choose another local database path. These counts remain on the user's computer unless the user voluntarily shares the report.

To **voluntarily share anonymous usage counts** with the maintainers, enable remote telemetry in the MCP server environment only after reviewing this notice:

```text
TAV_TELEMETRY=on
TAV_TELEMETRY_URL=https://technical-answer-validator-telemetry.chl1591204.workers.dev/v1/event
```

Remote telemetry is off by default. When enabled, each tool call sends only a random persistent installation ID, package version, and outcome (`success`, `invalid_request`, or `error`) to the configured Cloudflare Worker. The ID is random and is not derived from a user, device, or account identifier; it lets us estimate distinct installations, not distinct people. Answers, rubrics, tool outputs, IP addresses, host names, and request contents are not included in the event payload. Cloudflare necessarily receives network connection metadata such as the sender IP to deliver the request; our Worker does not log or store it. Analytics Engine retains event data for three months. Disable by setting `TAV_TELEMETRY=off` and optionally remove `~/.technical-answer-validator/telemetry-id` to reset the random ID. Telemetry failures never interrupt evaluations.

The collector is deployed at the URL above and accepts events only at `/v1/event`. To read aggregate usage, create a Cloudflare API token restricted to **Account Analytics Read** for the account that owns the Worker, then run `python scripts/query_telemetry.py` from this repository. The script prompts for the token without echoing or saving it. The report groups call totals by UTC day, package version, and outcome, and estimates distinct installations; it does not identify people. Do not put the token in source control, an MCP configuration, or a command line.

PyPI 0.1.1 does not include this opt-in telemetry code. It will be available to package users in 0.1.2; collection starts only after that version is installed and a user explicitly enables both environment variables above. The local-only `tav-mcp-stats` command continues to work independently.

## Request

`POST /v1/evaluate`

```json
{
  "rubric": {
    "required_concepts": ["isolation", "lockout tag"],
    "accepted_synonyms": {"isolation": ["energy isolation"]},
    "numeric_requirements": [],
    "required_count": 2
  },
  "answer": "Apply energy isolation and attach a lockout tag."
}
```

`accepted_synonyms` keys must exactly match a concept. `numeric_requirements` is an optional array such as `[{"value":"10","unit":"kN","tolerance":"0"}]`. Numbers in an answer are only checked when explicit requirements are provided. Concept score is matched concepts / required_count (defaults to the number of concepts), capped at 1.0; numeric failures apply a 50% score penalty. The verdict thresholds are `correct >= 0.8`, `partial >= 0.4`, otherwise `wrong`.

## Response and errors

Successful requests return `api_version`, `status`, `score`, `verdict`, matched/missing concepts, numeric check details, and `review_required: true`.

Errors use JSON `{ "error": { "code": "...", "message": "..." } }`. Statuses include 400 (invalid request), 401 (missing/invalid key), 404, 405, 413 (body over 64 KiB), and 429 (over 60 requests/minute per client ID). The rate limit is 60 requests/minute per authenticated client ID, in memory, and resets when the process restarts. Daily request/success/client-error/rate-limited counters are persisted in SQLite without answer text and expire after 90 days. `GET /v1/usage` returns only the caller's current UTC-day counts. Retain and back up the usage volume as desired; it contains client IDs and aggregates only.

## Privacy and deployment limits

The stdio MCP option runs locally and sends no usage information to a central service unless the user explicitly enables remote telemetry as described above. Local aggregate call counts can be disabled separately. The REST API has separate server-side aggregates per API client.

The server does not log request bodies or answers. It stores daily counts keyed by client ID and request timestamps in process memory for REST rate limiting. The **stdio MCP option runs locally inside the agent host** and sends no requests to this HTTP server. The REST API is containerized and keeps usage counters in a persistent volume. Before public service, terminate TLS at a reverse proxy, set proxy-level rate/concurrency limits, deploy from a secret manager, monitor the host, and publish a data-retention/contact policy. The app-level per-client rate limit resets on restart and is not a substitute for edge controls.

## Verify

```powershell
python -m unittest discover -s tests -v
```

The OpenAPI contract is in `openapi.yaml`; the draft official MCP Registry descriptor is `server.json`, with publication steps in `PUBLISHING.md`. Run locally with Docker Compose after copying `.env.example` to `.env` and adding a private key; Compose publishes the service only on loopback, so configure an HTTPS reverse proxy separately. `compose.yaml` persists aggregate usage in a named volume and applies a read-only root filesystem, dropped Linux capabilities, and resource limits.

These tests check API and grading behavior; they do not establish professional exam accuracy.


