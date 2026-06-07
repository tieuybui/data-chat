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
LOCAL_SERVER    = st.secrets.get("local", {}).get("server", ".")
LOCAL_DATABASE  = st.secrets.get("local", {}).get("database", "")

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
    "local": {
        "label": "Local SQL Server",
        "fabric": False,
        "odbc": (
            f"DRIVER={{{ODBC_DRIVER}}};"
            f"Server={LOCAL_SERVER};"
            f"Database={LOCAL_DATABASE};"
            "Trusted_Connection=yes;"
            "Encrypt=no;"
            "TrustServerCertificate=yes;"
            "Command Timeout=0"
        ),
    },
}
