"""
Environment configs — all values read from st.secrets (secrets.toml).
"""

import pyodbc
import streamlit as st

# ─── ODBC Driver Detection ────────────────────────────────
ODBC_DRIVER: str | None = None
for _drv in ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"]:
    if _drv in pyodbc.drivers():
        ODBC_DRIVER = _drv
        break

# ─── Secrets ──────────────────────────────────────────────
FABRIC_SERVER   = st.secrets.get("fabric", {}).get("server", "")
FABRIC_DATABASE = st.secrets.get("fabric", {}).get("database", "")
EDW_SERVER      = st.secrets.get("edw", {}).get("server", "")
EDW_DATABASE    = st.secrets.get("edw", {}).get("database", "")
EDW_USERNAME    = st.secrets.get("edw", {}).get("username", "")
EDW_PASSWORD    = st.secrets.get("edw", {}).get("password", "")
EDW_AUTH        = st.secrets.get("edw", {}).get("auth", "ActiveDirectoryPassword")

AZURE_OPENAI_ENDPOINT   = st.secrets.get("azure_openai", {}).get("endpoint", "")
AZURE_OPENAI_KEY        = st.secrets.get("azure_openai", {}).get("key", "")
AZURE_OPENAI_DEPLOYMENT = st.secrets.get("azure_openai", {}).get("deployment", "gpt-5")

APP_USERNAME = st.secrets.get("username", "admin")
APP_PASSWORD = st.secrets.get("password", "")


def fabric_odbc(database: str) -> str:
    return (
        f"DRIVER={{{ODBC_DRIVER}}};"
        f"Server={FABRIC_SERVER},1433;"
        f"Database={database};"
        "Encrypt=yes;"
        "TrustServerCertificate=no"
    )


# ─── Environment Configs ──────────────────────────────────
ENV_CONFIGS: dict = {
    "fabric": {
        "label": "Fabric",
        "fabric": True,
    },
    "edw": {
        "label": "EDW Database",
        "fabric": False,
        "odbc": (
            f"DRIVER={{{ODBC_DRIVER}}};"
            f"Server=tcp:{EDW_SERVER},1433;"
            f"Database={EDW_DATABASE};"
            f"Authentication={EDW_AUTH};"
            f"UID={EDW_USERNAME};"
            f"PWD={EDW_PASSWORD};"
            "Encrypt=yes;"
            "TrustServerCertificate=no;"
            "Connection Timeout=30"
        ),
    },
}
