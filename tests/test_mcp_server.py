import unittest

import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

from mcp_server import mcp


class MCPServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_discovery_and_call(self):
        async with Client(mcp) as client:
            listed = await client.list_tools()
            self.assertEqual([tool.name for tool in listed.tools], ["evaluate_answer"])

            result = await client.call_tool(
                "evaluate_answer",
                {
                    "rubric": {
                        "required_concepts": ["isolation", "lockout tag"],
                        "accepted_synonyms": {"isolation": ["energy isolation"]},
                        "required_count": 2,
                    },
                    "answer": "Apply energy isolation and attach a lockout tag.",
                },
            )
            self.assertEqual(result.structured_content["verdict"], "correct")
            self.assertTrue(result.structured_content["review_required"])

    async def test_stdio_subprocess_transport(self):
        server_file = Path(__file__).resolve().parents[1] / "mcp_server.py"
        server = StdioServerParameters(command=sys.executable, args=[str(server_file)])
        async with Client(server) as client:
            listed = await client.list_tools()
            self.assertEqual([tool.name for tool in listed.tools], ["evaluate_answer"])
            result = await client.call_tool(
                "evaluate_answer",
                {"rubric": {"required_concepts": ["hazard"]}, "answer": "hazard identified"},
            )
            self.assertEqual(result.structured_content["verdict"], "correct")

    async def test_invalid_input_returns_repairable_error(self):
        async with Client(mcp) as client:
            result = await client.call_tool("evaluate_answer", {"rubric": {}, "answer": ""})
            self.assertEqual(result.structured_content["status"], "invalid_request")
            self.assertIn("error", result.structured_content)


if __name__ == "__main__":
    unittest.main()
