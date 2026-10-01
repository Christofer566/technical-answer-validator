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
