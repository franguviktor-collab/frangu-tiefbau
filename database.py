"""PostgreSQL persistence for Glasfaser appointments (Neon / DATABASE_URL)."""

import os
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

dotenv.load_dotenv()


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Add a Neon connection string "
            "(postgresql://...) to your environment."
        )
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    return url


@contextmanager
def get_conn():
    conn = psycopg2.connect(_database_url())
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS appointments (
                    id SERIAL PRIMARY KEY,
                    first_name TEXT NOT NULL,
                    last_name TEXT NOT NULL,
                    street TEXT NOT NULL,
                    plz TEXT NOT NULL,
                    city TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    preferred_date TEXT NOT NULL,
                    preferred_time TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    status TEXT NOT NULL DEFAULT 'new'
                )
                """
            )
        conn.commit()


def _row_dict(r: dict[str, Any]) -> dict[str, Any]:
    out = dict(r)
    ca = out.get("created_at")
    if isinstance(ca, datetime):
        out["created_at"] = ca.replace(tzinfo=None).isoformat() + "Z"
    return out


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
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO appointments (
                    first_name, last_name, street, plz, city, phone,
                    preferred_date, preferred_time, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'new')
                RETURNING id
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
                ),
            )
            new_id = cur.fetchone()[0]
        conn.commit()
        return int(new_id)


def list_appointments() -> list[dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, first_name, last_name, street, plz, city, phone,
                       preferred_date, preferred_time, created_at, status
                FROM appointments
                ORDER BY created_at DESC
                """
            )
            rows = cur.fetchall()
    return [_row_dict(r) for r in rows]


def delete_appointment(appt_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM appointments WHERE id = %s", (appt_id,))
        conn.commit()


def set_appointment_status(appt_id: int, status: str) -> None:
    allowed = {"new", "confirmed", "completed"}
    if status not in allowed:
        raise ValueError("invalid status")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE appointments SET status = %s WHERE id = %s",
                (status, appt_id),
            )
        conn.commit()
