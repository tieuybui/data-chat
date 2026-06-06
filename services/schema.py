"""
Schema discovery — fetches table and column metadata from the connected database
and formats it as a text context string for the AI.
"""

import streamlit as st
import pandas as pd

_TABLES_SQL = """
SELECT TABLE_NAME
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_TYPE = 'BASE TABLE'
ORDER BY TABLE_NAME
"""

_COLUMNS_SQL = """
SELECT
    c.TABLE_NAME,
    c.COLUMN_NAME,
    c.DATA_TYPE,
    c.IS_NULLABLE,
    c.ORDINAL_POSITION
FROM INFORMATION_SCHEMA.COLUMNS c
INNER JOIN INFORMATION_SCHEMA.TABLES t
    ON c.TABLE_NAME = t.TABLE_NAME
    AND c.TABLE_SCHEMA = t.TABLE_SCHEMA
WHERE t.TABLE_TYPE = 'BASE TABLE'
ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION
"""

# Try to pull business descriptions from data-catalog dd_tables/dd_columns if available
_DD_TABLES_SQL = """
SELECT table_name, description
FROM dd_tables
WHERE description IS NOT NULL AND description <> ''
"""

_DD_COLUMNS_SQL = """
SELECT table_name, column_name, description, business_name
FROM dd_columns
WHERE (description IS NOT NULL AND description <> '')
   OR (business_name IS NOT NULL AND business_name <> '')
"""


def get_schema_context() -> str:
    """Return cached schema context string for the current environment."""
    env = st.session_state.get("env", "")
    cache_key = f"_schema_ctx_{env}"
    if cache_key not in st.session_state:
        st.session_state[cache_key] = _build_schema_context()
    return st.session_state[cache_key]


def invalidate_schema_cache():
    env = st.session_state.get("env", "")
    st.session_state.pop(f"_schema_ctx_{env}", None)


def _build_schema_context() -> str:
    from core.database import run_query

    tables_df = run_query(_TABLES_SQL)
    cols_df = run_query(_COLUMNS_SQL)

    # Try to enrich with business descriptions from data-catalog metadata
    dd_tables: dict[str, str] = {}
    dd_cols: dict[tuple, dict] = {}
    try:
        for _, r in run_query(_DD_TABLES_SQL).iterrows():
            dd_tables[r["table_name"]] = r["description"]
        for _, r in run_query(_DD_COLUMNS_SQL).iterrows():
            dd_cols[(r["table_name"], r["column_name"])] = {
                "desc": r.get("description", ""),
                "biz": r.get("business_name", ""),
            }
    except Exception:
        pass  # metadata tables may not exist yet

    return _format_schema(tables_df, cols_df, dd_tables, dd_cols)


def _format_schema(
    tables_df: pd.DataFrame,
    cols_df: pd.DataFrame,
    dd_tables: dict,
    dd_cols: dict,
) -> str:
    cols_by_table: dict[str, list[str]] = {}
    for _, row in cols_df.iterrows():
        tbl = row["TABLE_NAME"]
        nullable = "" if row["IS_NULLABLE"] == "YES" else " NOT NULL"
        col_line = f"  - {row['COLUMN_NAME']} ({row['DATA_TYPE'].upper()}{nullable})"

        meta = dd_cols.get((tbl, row["COLUMN_NAME"]), {})
        if meta.get("biz"):
            col_line += f" — {meta['biz']}"
        if meta.get("desc"):
            col_line += f": {meta['desc']}"

        cols_by_table.setdefault(tbl, []).append(col_line)

    lines = []
    for _, row in tables_df.iterrows():
        tbl = row["TABLE_NAME"]
        desc = dd_tables.get(tbl, "")
        header = f"TABLE: {tbl}"
        if desc:
            header += f"  -- {desc}"
        lines.append(header)
        for col in cols_by_table.get(tbl, []):
            lines.append(col)
        lines.append("")

    return "\n".join(lines)
