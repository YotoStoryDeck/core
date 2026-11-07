"""SQLite Connection Factory & Path Configuration."""
import os
import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger("yoto_broker.database")

IS_DOCKER = os.path.exists("/.dockerenv") or (os.path.exists("/app") and os.path.isfile("/app/app.py"))
DB_DEFAULT = "/app/data/broker.db" if IS_DOCKER else str(Path(__file__).parent.parent / "data" / "broker.db")
CONFIG_DEFAULT = "/app/data/config.json" if IS_DOCKER else str(Path(__file__).parent.parent / "config.example.json")

DB_PATH = Path(os.getenv("DB_PATH", DB_DEFAULT))
LEGACY_CONFIG_PATH = Path(os.getenv("CONFIG_PATH", CONFIG_DEFAULT))

def get_db_connection() -> sqlite3.Connection:
    """Creates a new SQLite connection with WAL mode and row factory enabled."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 30000;")
    return conn
