"""
Schema discovery — fetches table and column metadata from the connected database
and formats it as a text context string for the AI.
"""

import streamlit as st
import pandas as pd

_TABLES_SQL = """
SELECT TABLE_SCHEMA, TABLE_NAME
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_TYPE = 'BASE TABLE'
ORDER BY TABLE_SCHEMA, TABLE_NAME
"""

_COLUMNS_SQL = """
SELECT
    c.TABLE_SCHEMA,
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
ORDER BY c.TABLE_SCHEMA, c.TABLE_NAME, c.ORDINAL_POSITION
"""


def get_schema_context() -> str:
    """Return cached schema context string for the current environment/database."""
    env, database = _schema_cache_identity()
    return _build_schema_context(env, database)


def invalidate_schema_cache():
    _build_schema_context.clear()
    st.session_state.pop("_schema_info", None)


def _schema_cache_identity() -> tuple[str, str]:
    env = st.session_state.get("env", "")
    if env == "fabric":
        return env, st.session_state.get("fabric_database", "")
    return env, env


@st.cache_data(show_spinner=False)
def _build_schema_context(env: str, database: str) -> str:
    """Load table/schema/column metadata once per environment/database."""
    from core.database import run_query

    print(f"\n[SCHEMA CACHE MISS] env={env}, database={database}")
    tables_df = run_query(_TABLES_SQL)
    cols_df = run_query(_COLUMNS_SQL)
    print(f"\n[SCHEMA] {len(tables_df)} tables loaded")
    return _format_schema(tables_df, cols_df)


def _format_schema(tables_df: pd.DataFrame, cols_df: pd.DataFrame) -> str:
    cols_by_table: dict[str, list[str]] = {}
    for _, row in cols_df.iterrows():
        key = f"{row['TABLE_SCHEMA']}.{row['TABLE_NAME']}"
        nullable = "" if row["IS_NULLABLE"] == "YES" else " NOT NULL"
        col_line = f"  - {row['COLUMN_NAME']} ({row['DATA_TYPE'].upper()}{nullable})"
        cols_by_table.setdefault(key, []).append(col_line)

    lines = []
    for _, row in tables_df.iterrows():
        full_name = f"{row['TABLE_SCHEMA']}.{row['TABLE_NAME']}"
        lines.append(f"TABLE: {full_name}")
        for col in cols_by_table.get(full_name, []):
            lines.append(col)
        lines.append("")

    return "\n".join(lines)
