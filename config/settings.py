"""
Environment configs for Fabric Lakehouse and Local SQL Server connections.
Adapted from data-catalog project.
"""

import os
import pyodbc

# ─── ODBC Driver Detection ────────────────────────────────
ODBC_DRIVER: str | None = None
for _drv in ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"]:
    if _drv in pyodbc.drivers():
        ODBC_DRIVER = _drv
        break

# ─── Environment Variables ────────────────────────────────
FABRIC_SERVER = os.environ.get("FABRIC_SERVER", "")
FABRIC_DATABASE = os.environ.get("FABRIC_DATABASE", "")
LOCAL_SERVER = os.environ.get("LOCAL_SERVER", ".")
LOCAL_DATABASE = os.environ.get("LOCAL_DATABASE", "")

AZURE_OPENAI_KEY = os.environ.get("AZURE_OPENAI_KEY", "")
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-5")

APP_USERNAME = os.environ.get("APP_USERNAME", "admin")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")


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
