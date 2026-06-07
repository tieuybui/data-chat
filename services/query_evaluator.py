"""
Query evaluation service.
Reviews a user-provided SQL/query against expected conditions and data sources.
"""

import json
import re


_EVALUATION_SYSTEM = """\
You are a strict SQL review assistant for a supply chain lakehouse database.
Your job is to evaluate whether a user-provided query matches the requested
business conditions and uses the correct data sources.

Database Schema:
{schema}

Review dimensions:
- Conditions: filters, date ranges, aggregations, joins, grouping, limits, and business logic.
- Sources: schema-qualified table names, joined tables, and whether the query uses tables available in the schema.
- Safety: only SELECT/read-only queries are acceptable.

The user may provide a natural-language requirement, an expected source, and a SQL query
in any format. Infer the pieces if labels are missing.

Respond ONLY with valid JSON:

{{
  "verdict": "pass|warning|fail",
  "condition_score": 0,
  "source_score": 0,
  "used_sources": ["schema.table"],
  "expected_sources": ["schema.table"],
  "missing_conditions": ["specific missing condition"],
  "source_issues": ["specific source issue"],
  "safety_issues": ["specific safety issue"],
  "notes": "Short Vietnamese explanation",
  "recommendation": "Concrete Vietnamese next step",
  "corrected_sql": null
}}

Scoring:
- 90-100: clearly correct.
- 70-89: mostly correct, minor ambiguity.
- 40-69: partially correct, important gap.
- 0-39: wrong or insufficient information.

Rules:
- Be conservative. If the requirement or SQL is missing, return warning/fail and explain what is missing.
- Do not hallucinate unavailable tables or columns.
- If suggesting corrected_sql, keep it SELECT-only and use schema-qualified table names.
- Keep arrays concise, max 6 items each.
"""


class QueryEvaluationError(Exception):
    pass


class QueryEvaluatorAI:
    def __init__(self, api_key: str, endpoint: str, deployment: str):
        try:
            from openai import AzureOpenAI
        except ImportError as e:
            raise QueryEvaluationError("openai package not installed. Run: pip install openai") from e

        self.client = AzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint.rstrip("/"),
            api_version="2024-02-01",
        )
        self.deployment = deployment

    def evaluate(self, message: str, schema: str, history: list[dict]) -> dict:
        messages = [{"role": "system", "content": _EVALUATION_SYSTEM.format(schema=schema)}]

        for item in history[-8:]:
            messages.append({"role": item["role"], "content": str(item.get("content", ""))})

        messages.append({"role": "user", "content": message})

        try:
            resp = self.client.chat.completions.create(
                model=self.deployment,
                messages=messages,
                max_completion_tokens=4000,
            )
            raw = resp.choices[0].message.content or ""
            parsed = _parse_json(raw)
            if parsed is not None:
                return _normalize_result(parsed, message)
            return _fallback_result(message, f"Không parse được phản hồi AI: {raw[:200]}")
        except Exception as exc:
            raise QueryEvaluationError(f"Azure OpenAI API error: {exc}") from exc


def _normalize_result(result: dict, message: str) -> dict:
    verdict = str(result.get("verdict", "warning")).lower()
    if verdict not in {"pass", "warning", "fail"}:
        verdict = "warning"

    normalized = {
        "verdict": verdict,
        "condition_score": _clamp_score(result.get("condition_score")),
        "source_score": _clamp_score(result.get("source_score")),
        "used_sources": _as_list(result.get("used_sources")) or _extract_sources(message),
        "expected_sources": _as_list(result.get("expected_sources")),
        "missing_conditions": _as_list(result.get("missing_conditions")),
        "source_issues": _as_list(result.get("source_issues")),
        "safety_issues": _as_list(result.get("safety_issues")),
        "notes": str(result.get("notes") or ""),
        "recommendation": str(result.get("recommendation") or ""),
        "corrected_sql": result.get("corrected_sql"),
    }
    return normalized


def _fallback_result(message: str, reason: str) -> dict:
    sources = _extract_sources(message)
    unsafe = []
    if re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|EXEC|MERGE)\b", message, re.IGNORECASE):
        unsafe.append("Query có dấu hiệu không phải SELECT/read-only.")

    return {
        "verdict": "warning" if not unsafe else "fail",
        "condition_score": 0,
        "source_score": 50 if sources else 0,
        "used_sources": sources,
        "expected_sources": [],
        "missing_conditions": ["Cần AI đánh giá chi tiết điều kiện từ yêu cầu nghiệp vụ."],
        "source_issues": [] if sources else ["Không tìm thấy source/table rõ ràng trong nội dung."],
        "safety_issues": unsafe,
        "notes": reason,
        "recommendation": "Bổ sung requirement, expected source và SQL để đánh giá chính xác hơn.",
        "corrected_sql": None,
    }


def _parse_json(text: str) -> dict | None:
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if match:
        text = match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]+\}", text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return None


def _extract_sources(text: str) -> list[str]:
    patterns = [
        r"\b(?:FROM|JOIN)\s+([\[\]\w.]+)",
        r"\bsource(?:s)?\s*[:=]\s*([\[\]\w.]+)",
    ]
    sources = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            source = match.group(1).strip("[] ")
            if "." in source and source not in sources:
                sources.append(source)
    return sources[:10]


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _clamp_score(value) -> int:
    try:
        score = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, score))
