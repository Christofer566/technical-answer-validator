"""Generate a one-time API credential and its TAV_API_KEYS SHA-256 entry."""
import hashlib
import json
import re
import secrets
import sys

if len(sys.argv) != 2 or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", sys.argv[1]):
    raise SystemExit("Usage: python scripts/create_api_key.py CLIENT_ID (letters, digits, _ or -; max 48)")
client_id = sys.argv[1]
token = "tav_" + secrets.token_urlsafe(36)
digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
print("Save this API key now; it is shown only once:\n" + token)
print("Add this entry to your secret manager's TAV_API_KEYS JSON:")
print(json.dumps({client_id: digest}, separators=(",", ":")))
