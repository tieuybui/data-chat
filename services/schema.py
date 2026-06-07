"""
Schema discovery — fetches table and column metadata from the connected database
and formats it as a text context string for the AI.

Loading is split into two lazy stages:
  1. _build_table_list  — fetches only table names (fast, runs at startup)
  2. _fetch_columns     — fetches column details for a specific set of tables (on-demand, cached per table set)

This avoids pulling the full INFORMATION_SCHEMA.COLUMNS for all tables on every cold start.
"""

import streamlit as st

_TABLES_SQL = """
SELECT TABLE_SCHEMA, TABLE_NAME
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_TYPE = 'BASE TABLE'
ORDER BY TABLE_SCHEMA, TABLE_NAME
"""


def get_schema_context() -> str:
    """Full schema string — used by the evaluator tab. Lazy: columns fetched on first call."""
    env, database = _schema_cache_identity()
    table_list = _build_table_list(env, database)
    cols_by_table = _fetch_columns(env, database, tuple(sorted(table_list)))
    return _format_schema(table_list, cols_by_table)


def get_tables_context() -> str:
    """Compact table-names-only string for AI table selection (Pass 1).
    Only fetches the table list — no column queries."""
    env, database = _schema_cache_identity()
    table_list = _build_table_list(env, database)
    return "Available tables:\n" + "\n".join(f"- {t}" for t in table_list)


def get_schema_for_tables(table_names: list[str]) -> str:
    """Focused schema for specific tables only (Pass 2).
    Fetches and caches column details only for the requested tables.
    Falls back to full schema if none of the names are valid.
    """
    env, database = _schema_cache_identity()
    table_list = _build_table_list(env, database)
    valid_set = set(table_list)
    valid = [t for t in table_names if t in valid_set]
    if not valid:
        cols_by_table = _fetch_columns(env, database, tuple(sorted(table_list)))
        return _format_schema(table_list, cols_by_table)
    cols_by_table = _fetch_columns(env, database, tuple(sorted(valid)))
    return _format_schema(valid, cols_by_table)


def get_table_count() -> int:
    """Return number of tables — cheap, uses the cached table list."""
    env, database = _schema_cache_identity()
    return len(_build_table_list(env, database))


def invalidate_schema_cache():
    _build_table_list.clear()
    _fetch_columns.clear()
    st.session_state.pop("_schema_info", None)


def _schema_cache_identity() -> tuple[str, str]:
    env = st.session_state.get("env", "")
    if env == "fabric":
        return env, st.session_state.get("fabric_database", "")
    return env, env


@st.cache_data(show_spinner=False)
def _build_table_list(env: str, database: str) -> list[str]:
    """Fetch only table names — small query, runs at startup."""
    from core.database import run_query

    print(f"\n[SCHEMA] Fetching table list — env={env}, database={database}")
    tables_df = run_query(_TABLES_SQL)
    print(f"\n[SCHEMA] {len(tables_df)} tables found")
    return [
        f"{row['TABLE_SCHEMA']}.{row['TABLE_NAME']}"
        for _, row in tables_df.iterrows()
    ]


@st.cache_data(show_spinner=False)
def _fetch_columns(_env: str, _database: str, tables_key: tuple[str, ...]) -> dict[str, list[str]]:
    """Fetch column details for a sorted tuple of tables — cached per unique table set.

    Table names come from our own _build_table_list cache (trusted INFORMATION_SCHEMA values),
    so inlining them in the IN clause is safe.
    """
    from core.database import run_query

    if not tables_key:
        return {}

    names_in = ", ".join(f"'{t.split('.', 1)[1]}'" for t in tables_key)
    schemas_in = ", ".join(f"'{t.split('.', 1)[0]}'" for t in tables_key)

    sql = f"""
SELECT c.TABLE_SCHEMA, c.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE, c.ORDINAL_POSITION
FROM INFORMATION_SCHEMA.COLUMNS c
WHERE c.TABLE_SCHEMA IN ({schemas_in})
  AND c.TABLE_NAME IN ({names_in})
ORDER BY c.TABLE_SCHEMA, c.TABLE_NAME, c.ORDINAL_POSITION
"""
    print(f"\n[SCHEMA] Fetching columns for {len(tables_key)} tables")
    cols_df = run_query(sql)

    cols_by_table: dict[str, list[str]] = {}
    for _, row in cols_df.iterrows():
        key = f"{row['TABLE_SCHEMA']}.{row['TABLE_NAME']}"
        col_line = f"  - {row['COLUMN_NAME']} ({row['DATA_TYPE'].upper()})"
        cols_by_table.setdefault(key, []).append(col_line)
    return cols_by_table


def _format_schema(table_list: list[str], cols_by_table: dict[str, list[str]]) -> str:
    lines = []
    for table in table_list:
        lines.append(f"TABLE: {table}")
        for col in cols_by_table.get(table, []):
            lines.append(col)
        lines.append("")
    return "\n".join(lines)
