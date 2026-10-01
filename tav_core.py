"""Deterministic grading against caller-supplied rubric data only."""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from decimal import Decimal, InvalidOperation
from typing import Any


class RequestError(ValueError):
    """Input does not satisfy the API contract."""


_NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?")
_ALLOWED_RUBRIC = {"required_concepts", "accepted_synonyms", "numeric_requirements", "required_count"}


def _normalize(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold(), flags=re.UNICODE)


def _ensure_utf8(value: Any) -> None:
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise RequestError("all input strings must be valid Unicode") from None
    elif isinstance(value, dict):
        for key, item in value.items():
            _ensure_utf8(key)
            _ensure_utf8(item)
    elif isinstance(value, list):
        for item in value:
            _ensure_utf8(item)


def _match_concept(concept: str, synonyms: list[str], answer: str) -> bool:
    candidates = [concept, *synonyms]
    norm_answer = _normalize(answer)
    for candidate in candidates:
        norm = _normalize(candidate)
        if norm and norm in norm_answer:
            return True

    # Conservative typo tolerance: only for candidates of 5+ characters,
    # using sliding windows to avoid comparing against the whole paragraph.
    for candidate in candidates:
        norm = _normalize(candidate)
        if len(norm) < 5:
            continue
        window_count = max(1, len(norm_answer) - len(norm) + 1)
        stride = max(1, (window_count + 255) // 256)
        for start in range(0, window_count, stride):
            window = norm_answer[start : start + len(norm)]
            if SequenceMatcher(None, norm, window).ratio() >= 0.88:
                return True
    return False


def _validate_rubric(rubric: Any) -> tuple[list[str], dict[str, list[str]], list[dict[str, str]], int]:
    if not isinstance(rubric, dict):
        raise RequestError("rubric must be an object")
    extra = set(rubric) - _ALLOWED_RUBRIC
    if extra:
        raise RequestError(f"unknown rubric field: {sorted(extra)[0]}")

    concepts = rubric.get("required_concepts")
    if not isinstance(concepts, list) or not 1 <= len(concepts) <= 50:
        raise RequestError("required_concepts must be an array with 1 to 50 items")
    if any(not isinstance(item, str) or not item.strip() or len(item) > 120 for item in concepts):
        raise RequestError("each concept must be a non-empty string of at most 120 characters")
    if len({_normalize(x) for x in concepts}) != len(concepts):
        raise RequestError("required_concepts must be unique after normalization")

    if len(json.dumps(rubric, ensure_ascii=False).encode("utf-8")) > 8192:
        raise RequestError("rubric must not exceed 8 KiB")

    synonym_map = rubric.get("accepted_synonyms", {})
    if not isinstance(synonym_map, dict) or set(synonym_map) - set(concepts):
        raise RequestError("accepted_synonyms must map existing concepts to arrays")
    synonyms: dict[str, list[str]] = {}
    term_owners: dict[str, str] = {}
    for concept in concepts:
        term_owners[_normalize(concept)] = concept
    for concept, values in synonym_map.items():
        if not isinstance(values, list) or len(values) > 20:
            raise RequestError("each synonym list must contain at most 20 strings")
        if any(not isinstance(value, str) or not value.strip() or len(value) > 120 for value in values):
            raise RequestError("synonyms must be non-empty strings of at most 120 characters")
        synonyms[concept] = values
        for value in values:
            normalized = _normalize(value)
            owner = term_owners.get(normalized)
            if owner is not None and owner != concept:
                raise RequestError("a concept or synonym cannot belong to multiple concepts")
            term_owners[normalized] = concept
    if sum(1 + len(synonyms.get(concept, [])) for concept in concepts) > 100:
        raise RequestError("required concepts and synonyms may contain at most 100 total terms")

    numeric = rubric.get("numeric_requirements", [])
    if not isinstance(numeric, list) or len(numeric) > 20:
        raise RequestError("numeric_requirements must be an array with at most 20 items")
    normalized_numeric: list[dict[str, str]] = []
    for item in numeric:
        if not isinstance(item, dict) or set(item) - {"value", "unit", "tolerance"} or "value" not in item:
            raise RequestError("each numeric requirement needs value and optional unit/tolerance")
        try:
            expected_decimal = Decimal(str(item["value"]))
            tolerance_decimal = Decimal(str(item.get("tolerance", "0")))
            if not expected_decimal.is_finite() or not tolerance_decimal.is_finite() or tolerance_decimal < 0:
                raise InvalidOperation
            value = str(expected_decimal)
            tolerance = str(tolerance_decimal)
        except (InvalidOperation, ValueError):
            raise RequestError("numeric value and non-negative tolerance must be decimals") from None
        unit = item.get("unit", "")
        if not isinstance(unit, str) or len(unit) > 24:
            raise RequestError("numeric unit must be a string of at most 24 characters")
        normalized_numeric.append({"value": value, "unit": unit, "tolerance": tolerance})

    required_count = rubric.get("required_count", len(concepts))
    if not isinstance(required_count, int) or isinstance(required_count, bool) or not 1 <= required_count <= len(concepts):
        raise RequestError("required_count must be an integer from 1 to the number of concepts")
    return concepts, synonyms, normalized_numeric, required_count


def _parse_number(raw: str) -> Decimal | None:
    if "," in raw:
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", raw):
            raw = raw.replace(",", "")
        elif raw.count(",") == 1 and "." not in raw:
            raw = raw.replace(",", ".")
        else:
            return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def _check_numbers(answer: str, requirements: list[dict[str, str]]) -> list[dict[str, Any]]:
    checks = []
    for requirement in requirements:
        expected = Decimal(requirement["value"])
        tolerance = Decimal(requirement["tolerance"])
        unit = requirement["unit"]
        observed: list[Decimal] = []
        candidates = list(_NUMBER_RE.finditer(answer))
        for match in candidates:
            suffix = answer[match.end() : match.end() + len(unit) + 8].lstrip() if unit else ""
            if unit:
                unit_match = re.match(re.escape(unit) + r"(?![\w])", suffix, flags=re.IGNORECASE | re.UNICODE)
                if not unit_match:
                    continue
            actual = _parse_number(match.group())
            if actual is not None:
                observed.append(actual)
        passed = bool(observed) and all(abs(actual - expected) <= tolerance for actual in observed)
        checks.append({
            "expected": requirement["value"],
            "unit": unit,
            "tolerance": requirement["tolerance"],
            "observed": [str(value) for value in observed],
            "passed": passed,
        })
    return checks


def evaluate(payload: Any) -> dict[str, Any]:
    _ensure_utf8(payload)
    if not isinstance(payload, dict) or set(payload) != {"rubric", "answer"}:
        raise RequestError("request must contain exactly rubric and answer")
    answer = payload["answer"]
    if not isinstance(answer, str) or not answer.strip() or len(answer) > 8000:
        raise RequestError("answer must be a string of at most 8000 characters")
    rubric = payload["rubric"]
    concepts, synonyms, numeric, required_count = _validate_rubric(rubric)

    matched = [concept for concept in concepts if _match_concept(concept, synonyms.get(concept, []), answer)]
    missing = [concept for concept in concepts if concept not in matched]
    score = min(len(matched) / required_count, 1.0)
    numeric_checks = _check_numbers(answer, numeric)
    if any(not check["passed"] for check in numeric_checks):
        score *= 0.5
    score = round(score, 3)
    verdict = "correct" if score >= 0.8 else "partial" if score >= 0.4 else "wrong"
    notes = []
    if len(matched) < required_count:
        notes.append(f"required_count={required_count}; matched={len(matched)}")
    if any(not check["passed"] for check in numeric_checks):
        notes.append("One or more numeric requirements did not match.")
    return {
        "api_version": "v1",
        "status": "graded",
        "score": score,
        "verdict": verdict,
        "matched_concepts": matched,
        "missing_concepts": missing,
        "numeric_checks": numeric_checks,
        "notes": notes,
        "review_required": True,
        "limitations": ["Keyword-based assistive review only; not an official exam grade."],
    }
