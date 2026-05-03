"""SQLite persistence for Glasfaser appointments."""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import dotenv

dotenv.load_dotenv()


def _db_path() -> str:
    explicit = os.getenv("SQLITE_PATH")
    if explicit:
        return explicit
    if os.getenv("VERCEL"):
        return "/tmp/appointments.db"
    return str(Path(__file__).resolve().parent / "appointments.db")


def init_db() -> None:
    path = _db_path()
    parent = Path(path).parent
    if parent and str(parent) not in (".", ""):
        parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                street TEXT NOT NULL,
                plz TEXT NOT NULL,
                city TEXT NOT NULL,
                phone TEXT NOT NULL,
                preferred_date TEXT NOT NULL,
                preferred_time TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'new'
            )
            """
        )
        conn.commit()


@contextmanager
def get_conn():
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def create_appointment(
    first_name: str,
    last_name: str,
    street: str,
    plz: str,
    city: str,
    phone: str,
    preferred_date: str,
    preferred_time: str,
) -> int:
    created = datetime.utcnow().isoformat() + "Z"
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO appointments (
                first_name, last_name, street, plz, city, phone,
                preferred_date, preferred_time, created_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'new')
            """,
            (
                first_name.strip(),
                last_name.strip(),
                street.strip(),
                plz.strip(),
                city.strip(),
                phone.strip(),
                preferred_date.strip(),
                preferred_time.strip(),
                created,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def list_appointments() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, first_name, last_name, street, plz, city, phone,
                   preferred_date, preferred_time, created_at, status
            FROM appointments
            ORDER BY created_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def delete_appointment(appt_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM appointments WHERE id = ?", (appt_id,))
        conn.commit()


def set_appointment_status(appt_id: int, status: str) -> None:
    allowed = {"new", "confirmed", "completed"}
    if status not in allowed:
        raise ValueError("invalid status")
    with get_conn() as conn:
        conn.execute(
            "UPDATE appointments SET status = ? WHERE id = ?",
            (status, appt_id),
        )
        conn.commit()
