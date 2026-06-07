"""
Database connection and query execution.
Supports Local SQL Server (SQLAlchemy) and Fabric Lakehouse (pyodbc + Azure AD token).
"""

import struct
from urllib.parse import quote_plus

import pyodbc
import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text

from config.settings import ODBC_DRIVER, FABRIC_SERVER, ENV_CONFIGS, fabric_odbc

_SQL_COPT_SS_ACCESS_TOKEN = 1256

_LIST_DATABASES_SQL = """
SELECT name FROM sys.databases
WHERE name NOT IN ('master','model','msdb','tempdb')
ORDER BY name
"""


def check_odbc_driver():
    if not ODBC_DRIVER:
        st.error("No SQL Server ODBC driver found. Install ODBC Driver 17 or 18.")
        st.stop()


def is_fabric() -> bool:
    return st.session_state.get("env", "") == "fabric"


@st.cache_resource(ttl=2400)
def _get_fabric_token():
    sp = st.secrets.get("fabric_sp", {})
    if sp.get("tenant_id") and sp.get("client_id") and sp.get("client_secret"):
        from azure.identity import ClientSecretCredential
        credential = ClientSecretCredential(
            tenant_id=sp["tenant_id"],
            client_id=sp["client_id"],
            client_secret=sp["client_secret"],
        )
    else:
        from azure.identity import DefaultAzureCredential
        credential = DefaultAzureCredential()
    token = credential.get_token("https://database.windows.net/.default")
    return token.token


def _make_fabric_conn(database: str):
    token = _get_fabric_token()
    token_bytes = token.encode("utf-16-le")
    token_struct = struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)
    conn = pyodbc.connect(fabric_odbc(database), attrs_before={_SQL_COPT_SS_ACCESS_TOKEN: token_struct})
    return conn


def _get_fabric_connection():
    db = st.session_state.get("fabric_database", "")
    cache_key = f"_fabric_conn_{db}"
    conn = st.session_state.get(cache_key)
    if conn is not None:
        try:
            conn.cursor().execute("SELECT 1")
            return conn
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
    conn = _make_fabric_conn(db)
    st.session_state[cache_key] = conn
    return conn


def list_fabric_databases() -> list[str]:
    """Return available databases on the Fabric server."""
    try:
        conn = _make_fabric_conn("master")
        cursor = conn.cursor()
        cursor.execute(_LIST_DATABASES_SQL)
        names = [row[0] for row in cursor.fetchall()]
        conn.close()
        return names
    except Exception:
        # Fallback: try without master (some Fabric endpoints restrict it)
        return []


@st.cache_resource
def _get_engine(env_key: str):
    odbc_string = ENV_CONFIGS[env_key]["odbc"]
    return create_engine(f"mssql+pyodbc:///?odbc_connect={quote_plus(odbc_string)}")


def run_query(sql: str, params: dict | None = None) -> pd.DataFrame:
    """Execute a SELECT query and return a DataFrame."""
    print(f"\n[SQL]\n{sql}\n")
    if is_fabric():
        conn = _get_fabric_connection()
        cursor = conn.cursor()
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        return pd.DataFrame.from_records(cursor.fetchall(), columns=columns)
    with _get_engine(st.session_state.env).connect() as conn:
        return pd.read_sql(text(sql), conn, params=params)
