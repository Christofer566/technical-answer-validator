import hashlib
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

import tav_api


class RestAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        key_a = "client-a-secret-key-1234567890"
        key_b = "client-b-secret-key-1234567890"
        key_map = {
            "client-a": hashlib.sha256(key_a.encode()).hexdigest(),
            "client-b": hashlib.sha256(key_b.encode()).hexdigest(),
        }
        self.keys = {"client-a": key_a, "client-b": key_b}
        self.patch_env = patch.dict(os.environ, {
            "TAV_API_KEYS": json.dumps(key_map),
            "TAV_API_KEY": "",
            "TAV_USAGE_DB": os.path.join(self.temp.name, "usage.sqlite3"),
        })
        self.patch_env.start()
        tav_api._requests.clear()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), tav_api.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.patch_env.stop()
        self.temp.cleanup()

    def call(self, path, key=None, method="GET", payload=None, content_type="application/json"):
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {}
        if key:
            headers["Authorization"] = "Bearer " + key
        if data is not None and content_type:
            headers["Content-Type"] = content_type
        request = Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def test_auth_evaluation_and_per_client_usage_are_separated(self):
        status, _ = self.call("/v1/evaluate", method="POST", payload={"rubric": {"required_concepts": ["risk"]}, "answer": "risk"})
        self.assertEqual(status, 401)
        status, result = self.call("/v1/evaluate", self.keys["client-a"], "POST", {"rubric": {"required_concepts": ["risk"]}, "answer": "risk"})
        self.assertEqual(status, 200)
        self.assertEqual(result["verdict"], "correct")
        status, usage_a = self.call("/v1/usage", self.keys["client-a"])
        status_b, usage_b = self.call("/v1/usage", self.keys["client-b"])
        self.assertEqual((status, status_b), (200, 200))
        self.assertEqual((usage_a["requests"], usage_a["successful"]), (1, 1))
        self.assertEqual(usage_b["requests"], 0)

    def test_rate_limit_counts_per_client_without_answer_storage(self):
        with patch.object(tav_api, "RATE_LIMIT", 1):
            payload = {"rubric": {"required_concepts": ["private-marker"]}, "answer": "private-marker answer"}
            first, _ = self.call("/v1/evaluate", self.keys["client-a"], "POST", payload)
            second, _ = self.call("/v1/evaluate", self.keys["client-a"], "POST", payload)
            other_client, _ = self.call("/v1/evaluate", self.keys["client-b"], "POST", payload)
        self.assertEqual((first, second, other_client), (200, 429, 200))
        _, usage = self.call("/v1/usage", self.keys["client-a"])
        self.assertEqual((usage["requests"], usage["successful"], usage["rate_limited"]), (2, 1, 1))
        import sqlite3
        connection = sqlite3.connect(os.environ["TAV_USAGE_DB"])
        try:
            rows = connection.execute("SELECT * FROM daily_usage").fetchall()
        finally:
            connection.close()
        self.assertNotIn("private-marker", repr(rows))

    def test_invalid_media_type_and_json_are_rejected_and_counted(self):
        payload = {"rubric": {"required_concepts": ["risk"]}, "answer": "risk"}
        status, _ = self.call("/v1/evaluate", self.keys["client-a"], "POST", payload, "text/plain")
        self.assertEqual(status, 415)
        request = Request(self.base + "/v1/evaluate", data=b"{bad", headers={"Authorization": "Bearer " + self.keys["client-a"], "Content-Type": "application/json"}, method="POST")
        try:
            urlopen(request, timeout=3)
            self.fail("invalid JSON unexpectedly succeeded")
        except HTTPError as error:
            self.assertEqual(error.code, 400)
        _, usage = self.call("/v1/usage", self.keys["client-a"])
        self.assertEqual(usage["requests"], 2)
        self.assertEqual(usage["client_errors"], 2)


if __name__ == "__main__":
    unittest.main()
