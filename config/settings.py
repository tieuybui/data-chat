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

# ─── Environment Configs ──────────────────────────────────
ENV_CONFIGS: dict = {
    "fabric_dev": {
        "label": "Fabric - Dev",
        "fabric": True,
        "database": FABRIC_DATABASE,
        "odbc": (
            f"DRIVER={{{ODBC_DRIVER}}};"
            f"Server={FABRIC_SERVER},1433;"
            f"Database={FABRIC_DATABASE};"
            "Encrypt=yes;"
            "TrustServerCertificate=no"
        ),
    },
    "fabric_prod": {
        "label": "Fabric - Prod",
        "fabric": True,
        "database": FABRIC_DATABASE,
        "odbc": (
            f"DRIVER={{{ODBC_DRIVER}}};"
            f"Server={FABRIC_SERVER},1433;"
            f"Database={FABRIC_DATABASE};"
            "Encrypt=yes;"
            "TrustServerCertificate=no"
        ),
    },
    "local": {
        "label": "Local SQL Server",
        "fabric": False,
        "database": LOCAL_DATABASE,
        "odbc": (
            "DRIVER={SQL Server};"
            f"Server={LOCAL_SERVER};"
            f"Database={LOCAL_DATABASE};"
            "Trusted_Connection=yes;"
            "Encrypt=no;"
            "TrustServerCertificate=yes;"
            "Command Timeout=0"
        ),
    },
}
