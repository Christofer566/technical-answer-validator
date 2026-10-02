"""MCP stdio server exposing the answer evaluator as an agent tool."""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server import MCPServer

from tav_core import RequestError, evaluate
from tav_analytics import record_call

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
mcp = MCPServer(
    "Technical Answer Validator",
    instructions=(
        "Evaluate a user's technical answer against a rubric supplied for this call. "
        "Always pass the caller's rubric and answer. Explain that results are keyword-based "
        "assistive feedback, never official exam grades; preserve review_required in your response."
    ),
)


@mcp.tool()
def evaluate_answer(rubric: dict[str, Any], answer: str) -> dict[str, Any]:
    """Check an answer against caller-provided concepts, synonyms, and numeric requirements.

    Rubric fields: required_concepts (1-50 strings), optional accepted_synonyms keyed by
    concept, optional numeric_requirements [{value, unit?, tolerance?}], and optional
    required_count. No question bank is bundled. Review the returned result; it is not
    an official exam grade.
    """
    try:
        result = evaluate({"rubric": rubric, "answer": answer})
        record_call("success")
        return result
    except RequestError as exc:
        record_call("invalid_request")
        # Return a structured error result so the agent can repair its inputs.
        return {"status": "invalid_request", "error": str(exc), "review_required": True}
    except Exception:
        record_call("error")
        raise


def main() -> None:
    # FastMCP stdio transport uses stdout for protocol messages; keep diagnostics on stderr.
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
