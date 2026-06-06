"""
Database connection and query execution.
Supports Local SQL Server (SQLAlchemy) and Fabric Lakehouse (pyodbc + Azure AD token).
"""

import struct

import pyodbc
import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text

from config.settings import ODBC_DRIVER, ENV_CONFIGS

_SQL_COPT_SS_ACCESS_TOKEN = 1256


def check_odbc_driver():
    if not ODBC_DRIVER:
        st.error("No SQL Server ODBC driver found. Install ODBC Driver 17 or 18.")
        st.stop()


def is_fabric() -> bool:
    return st.session_state.get("env", "").startswith("fabric")


@st.cache_resource(ttl=2400)
def _get_fabric_token():
    from azure.identity import DefaultAzureCredential
    credential = DefaultAzureCredential()
    token = credential.get_token("https://database.windows.net/.default")
    return token.token


def _get_fabric_connection():
    conn = st.session_state.get("_fabric_conn")
    if conn is not None:
        try:
            conn.cursor().execute("SELECT 1")
            return conn
        except Exception:
            try:
                conn.close()
            except Exception:
                pass

    token = _get_fabric_token()
    token_bytes = token.encode("utf-16-le")
    token_struct = struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)
    odbc_string = ENV_CONFIGS[st.session_state.env]["odbc"]
    conn = pyodbc.connect(odbc_string, attrs_before={_SQL_COPT_SS_ACCESS_TOKEN: token_struct})
    st.session_state["_fabric_conn"] = conn
    return conn


@st.cache_resource
def _get_engine(env_key: str):
    odbc_string = ENV_CONFIGS[env_key]["odbc"]
    return create_engine(f"mssql+pyodbc:///?odbc_connect={odbc_string}")


def run_query(sql: str, params: dict | None = None) -> pd.DataFrame:
    """Execute a SELECT query and return a DataFrame."""
    if is_fabric():
        conn = _get_fabric_connection()
        return pd.read_sql(sql, conn)
    with _get_engine(st.session_state.env).connect() as conn:
        return pd.read_sql(text(sql), conn, params=params)
