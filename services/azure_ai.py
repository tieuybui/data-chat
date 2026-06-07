"""
Azure OpenAI service for Data Chat.
Two-phase pipeline: (1) NL → SQL, (2) results → insights + chart config.
"""

import json
import re
from typing import Callable

import pandas as pd


_TABLE_SELECTOR_SYSTEM = """\
You are a data analyst working with a supply chain database.
Given a user question, identify which tables are needed to answer it.

{tables_context}

Return ONLY a JSON array of the exact table names needed (e.g. ["dbo.FactSales", "dbo.DimProduct"]).
- Include only tables directly relevant to the question.
- Include at most 10 tables.
- For fact tables, also include their related dimension tables if the question needs them.
- Use exact table names as listed above.
- Return [] only if truly no table could possibly match.
"""

_SQL_SYSTEM = """\
You are a data analyst AI assistant for a supply chain lakehouse database.
Your job is to write T-SQL queries to answer the user's questions about their data.

Database Schema:
{schema}

Rules:
- Use T-SQL syntax (SQL Server / Microsoft Fabric compatible).
- ALWAYS use the full schema-qualified table name exactly as shown in the schema (e.g. dbo.FactOpenOrders, not FactOpenOrders).
- Add TOP 500 unless the user asks for all data or specifies a different limit.
- Only write SELECT queries. Never write INSERT, UPDATE, DELETE, DROP, EXEC, or DDL.
- Never use SELECT *. Always list only the columns needed to answer the question.
- Use meaningful column aliases (e.g. AS total_revenue, AS month_name).
- When filtering dates, use CAST or CONVERT for string-to-date comparison.
- Respond ONLY with valid JSON (no markdown, no explanation outside JSON):

{{
  "sql": "SELECT ...",
  "chart_suggestion": {{
    "type": "bar|line|pie|scatter|area|histogram|table|none",
    "x": "column_name_for_x_axis",
    "y": "column_name_for_y_axis",
    "color": null,
    "title": "Descriptive chart title"
  }}
}}

If the question cannot be answered from the available schema, return:
{{"sql": null, "message": "Brief explanation of why"}}
"""

_SQL_FIX_SYSTEM = """\
You are a T-SQL expert. A query failed with an error. Fix the SQL so it runs correctly.

Rules:
- Return ONLY valid JSON (no markdown, no explanation outside JSON).
- Keep the original intent of the query.
- Only write SELECT queries.
- Use full schema-qualified table names.

{{
  "sql": "SELECT ...",
  "chart_suggestion": {{
    "type": "bar|line|pie|scatter|area|histogram|table|none",
    "x": "column_name_for_x_axis",
    "y": "column_name_for_y_axis",
    "color": null,
    "title": "Descriptive chart title"
  }}
}}
"""

_INSIGHTS_SYSTEM = """\
You are a data analyst providing concise insights about query results.
Respond ONLY with valid JSON (no markdown outside the JSON):

{{
  "text": "Markdown-formatted insights with key findings, patterns, and numbers",
  "summary": "One sentence summary of the main finding",
  "chart_type": "bar|line|pie|scatter|area|histogram|table|none",
  "chart_config": {{
    "x": "exact_column_name",
    "y": "exact_column_name",
    "color": null,
    "title": "Chart title"
  }}
}}

Guidelines for "text":
- Use **bold** for key numbers and findings.
- Use bullet points for multiple findings.
- Max 150 words. Be specific and data-driven.
- Do NOT hallucinate data not in the provided results.

Guidelines for chart_type:
- bar: comparisons between categories
- line: trends over time
- area: trends with volume emphasis
- pie: part-of-whole (max ~8 slices)
- scatter: correlation between two numeric values
- histogram: distribution of a single numeric column
- table: when data is best shown as a table (multi-column detail, text-heavy)
- none: single-value results

Use exact column names from the provided data.
"""


class AIError(Exception):
    pass


class DataChatAI:
    def __init__(self, api_key: str, endpoint: str, deployment: str):
        try:
            from openai import AzureOpenAI
        except ImportError as e:
            raise AIError("openai package not installed. Run: pip install openai") from e

        self.client = AzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint.rstrip("/"),
            api_version="2024-02-01",
        )
        self.deployment = deployment

    def answer(
        self,
        question: str,
        schema: str,
        history: list[dict],
        run_query_fn: Callable[[str], pd.DataFrame],
        get_focused_schema_fn: Callable[[list[str]], str] | None = None,
    ) -> dict:
        """Full pipeline: question → SQL → execute → insights → chart.

        When get_focused_schema_fn is provided, `schema` should be a compact
        table-names list (from get_tables_context()). The method first asks the
        AI to pick relevant tables (Pass 1), then fetches only their column
        details before generating SQL (Pass 2).
        """

        # ── Step 1: Select relevant tables (two-pass mode) ───────────
        if get_focused_schema_fn is not None:
            selected = self._select_relevant_tables(question, schema, history)
            effective_schema = get_focused_schema_fn(selected)
        else:
            effective_schema = schema

        # ── Step 2: Generate SQL ─────────────────────────────────────
        sql_result = self._generate_sql(question, effective_schema, history)

        if not sql_result.get("sql"):
            return {
                "error": None,
                "insights": f"_{sql_result.get('message', 'Không thể tạo truy vấn cho câu hỏi này.')}_",
                "sql": None,
                "data": None,
                "chart_fig": None,
                "summary": question,
            }

        sql = sql_result["sql"]
        chart_hint = sql_result.get("chart_suggestion", {})

        # ── Step 2: Execute SQL (with one auto-fix retry on error) ──────────────────────────────────────
        try:
            df = run_query_fn(sql)
        except Exception as first_exc:
            # Ask AI to fix the SQL then retry once
            fix_result = self._fix_sql(sql, str(first_exc))
            fixed_sql = fix_result.get("sql") if fix_result else None
            if fixed_sql and fixed_sql != sql:
                chart_hint = fix_result.get("chart_suggestion", chart_hint)
                sql = fixed_sql
                try:
                    df = run_query_fn(sql)
                except Exception as second_exc:
                    return {
                        "error": f"**Lỗi thực thi SQL:** {second_exc}\n\nHãy thử diễn đạt lại câu hỏi của bạn.",
                        "insights": None,
                        "sql": sql,
                        "data": None,
                        "chart_fig": None,
                        "summary": f"SQL error for: {question}",
                    }
            else:
                return {
                    "error": f"**Lỗi thực thi SQL:** {first_exc}\n\nHãy thử diễn đạt lại câu hỏi của bạn.",
                    "insights": None,
                    "sql": sql,
                    "data": None,
                    "chart_fig": None,
                    "summary": f"SQL error for: {question}",
                }

        if df.empty:
            return {
                "error": None,
                "insights": "_Không có dữ liệu nào phù hợp với yêu cầu của bạn._",
                "sql": sql,
                "data": df,
                "chart_fig": None,
                "summary": f"No data found for: {question}",
            }

        # ── Step 3: Generate insights + chart config ─────────────────
        insight_result = self._generate_insights(question, sql, df)

        chart_type = insight_result.get("chart_type") or chart_hint.get("type", "table")
        chart_config = insight_result.get("chart_config") or chart_hint

        # Ensure chart_config has required keys, merge with hint
        merged_config = {**chart_hint, **chart_config}

        from services.chart import build_chart
        chart_fig = build_chart(df, chart_type, merged_config)

        return {
            "error": None,
            "insights": insight_result.get("text", ""),
            "sql": sql,
            "data": df,
            "chart_fig": chart_fig,
            "summary": insight_result.get("summary", question),
        }

    # ── Private helpers ──────────────────────────────────────────────

    def _select_relevant_tables(self, question: str, tables_context: str, history: list[dict]) -> list[str]:
        """Pass 1: ask AI to pick which tables are needed for the question."""
        messages = [
            {"role": "system", "content": _TABLE_SELECTOR_SYSTEM.format(tables_context=tables_context)}
        ]
        for m in history[-4:]:
            messages.append({"role": m["role"], "content": str(m.get("content", ""))})
        messages.append({"role": "user", "content": question})

        try:
            resp = self.client.chat.completions.create(
                model=self.deployment,
                messages=messages,
                max_completion_tokens=300,
            )
            raw = resp.choices[0].message.content or ""
            parsed = _parse_json(raw)
            if isinstance(parsed, list):
                return [t for t in parsed if isinstance(t, str)]
            match = re.search(r"\[.*?\]", raw, re.DOTALL)
            if match:
                result = json.loads(match.group(0))
                if isinstance(result, list):
                    return [t for t in result if isinstance(t, str)]
        except Exception:
            pass
        return []

    def _generate_sql(self, question: str, schema: str, history: list[dict]) -> dict:
        messages = [{"role": "system", "content": _SQL_SYSTEM.format(schema=schema)}]

        for m in history[-6:]:
            messages.append({"role": m["role"], "content": str(m.get("content", ""))})

        messages.append({"role": "user", "content": question})

        try:
            resp = self.client.chat.completions.create(
                model=self.deployment,
                messages=messages,
                max_completion_tokens=8000,
            )
            raw = resp.choices[0].message.content or ""
            parsed = _parse_json(raw)
            if parsed is not None:
                return parsed
            sql = _extract_sql_from_text(raw)
            return {"sql": sql} if sql else {"sql": None, "message": f"Failed to parse AI response: {raw[:200]}"}
        except Exception as exc:
            raise AIError(f"Azure OpenAI API error: {exc}") from exc

    def _fix_sql(self, sql: str, error: str) -> dict | None:
        """Ask AI to fix a broken SQL query given the SQL Server error message."""
        user_msg = f"Original SQL:\n{sql}\n\nError:\n{error}\n\nFix the SQL."
        try:
            resp = self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "system", "content": _SQL_FIX_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                max_completion_tokens=4000,
            )
            raw = resp.choices[0].message.content or ""
            parsed = _parse_json(raw)
            if parsed is not None:
                return parsed
            sql_fixed = _extract_sql_from_text(raw)
            return {"sql": sql_fixed} if sql_fixed else None
        except Exception:
            return None

    def _generate_insights(self, question: str, sql: str, df: pd.DataFrame) -> dict:
        col_info = {col: str(df[col].dtype) for col in df.columns}
        preview = df.head(50).to_string(index=False)

        user_msg = (
            f"Question: {question}\n\n"
            f"SQL executed:\n{sql}\n\n"
            f"Columns (dtype): {json.dumps(col_info)}\n"
            f"Total rows: {len(df)}\n\n"
            f"Data preview:\n{preview}"
        )

        try:
            resp = self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "system", "content": _INSIGHTS_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                max_completion_tokens=4000,
            )
            raw = resp.choices[0].message.content or ""
            parsed = _parse_json(raw)
            if parsed is not None:
                return parsed
        except Exception:
            pass
        return {
            "text": "_Dữ liệu đã được tải. Xem bảng bên dưới để biết chi tiết._",
            "summary": question,
            "chart_type": "table",
            "chart_config": {},
        }


def _parse_json(text: str) -> dict | None:
    """Extract and parse JSON from a response that may be wrapped in markdown."""
    text = text.strip()
    # Strip markdown code fences
    match = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if match:
        text = match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try finding the first {...} block
        match = re.search(r"\{[\s\S]+\}", text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return None


def _extract_sql_from_text(text: str) -> str | None:
    """Fallback: extract SQL from a markdown code block."""
    match = re.search(r"```(?:sql)?\s*(SELECT[\s\S]+?)```", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search(r"(SELECT\s+[\s\S]+?;)", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None
