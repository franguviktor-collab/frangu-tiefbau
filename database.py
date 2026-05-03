"""PostgreSQL persistence for Glasfaser appointments (Neon / DATABASE_URL)."""

import os
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo
import dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

dotenv.load_dotenv()

SLOT_TIMES = ("08:00", "10:00", "12:00", "14:00", "16:00", "18:00")
BOOKABLE_DAY_COUNT = 14


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
            cur.execute(
                "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS email TEXT"
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
    email: str | None,
    preferred_date: str,
    preferred_time: str,
) -> int:
    email_val = email.strip() if email else ""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO appointments (
                    first_name, last_name, street, plz, city, phone, email,
                    preferred_date, preferred_time, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'new')
                RETURNING id
                """,
                (
                    first_name.strip(),
                    last_name.strip(),
                    street.strip(),
                    plz.strip(),
                    city.strip(),
                    phone.strip(),
                    email_val or None,
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
                       email, preferred_date, preferred_time, created_at, status
                FROM appointments
                ORDER BY created_at DESC
                """
            )
            rows = cur.fetchall()
    return [_normalize_row_email(_row_dict(r)) for r in rows]


def _normalize_row_email(d: dict[str, Any]) -> dict[str, Any]:
    em = d.get("email")
    if em is None:
        d["email"] = ""
    return d


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


def booking_today() -> date:
    """Current date in Europe/Berlin for slot/booking windows."""
    return datetime.now(ZoneInfo("Europe/Berlin")).date()


def parse_iso_date_yyyy_mm_dd(s: str) -> date | None:
    s = s.strip()
    if len(s) != 10:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def bookable_dates_starting(today: date) -> list[date]:
    """Next BOOKABLE_DAY_COUNT calendar days excluding Sunday."""
    out: list[date] = []
    d = today
    while len(out) < BOOKABLE_DAY_COUNT:
        if d.weekday() != 6:
            out.append(d)
        d += timedelta(days=1)
    return out


def is_allowed_book_date(d_iso: str, today: date) -> bool:
    d = parse_iso_date_yyyy_mm_dd(d_iso)
    if d is None:
        return False
    allowed = {x.isoformat() for x in bookable_dates_starting(today)}
    return d.isoformat() in allowed


def is_bookable_now(d_iso: str) -> bool:
    """Whether d_iso is in the rolling bookable window (Europe/Berlin today)."""
    return is_allowed_book_date(d_iso, booking_today())


def normalize_slot_time(raw: str) -> str | None:
    raw = raw.strip()
    if raw not in SLOT_TIMES:
        return None
    return raw


def taken_times_for_date(
    conn,
    date_iso: str,
    exclude_appt_id: int | None = None,
) -> set[str]:
    sql = """
        SELECT preferred_time FROM appointments
        WHERE preferred_date = %s AND status <> 'completed'
    """
    args: list[Any] = [date_iso]
    if exclude_appt_id is not None:
        sql += " AND id <> %s"
        args.append(exclude_appt_id)
    with conn.cursor() as cur:
        cur.execute(sql, tuple(args))
        return {row[0] for row in cur.fetchall() if row[0]}


def slots_for_date(
    date_iso: str, exclude_appt_id: int | None = None
) -> list[dict[str, str]]:
    """Return fixed slot list with status free or taken."""
    with get_conn() as conn:
        taken = taken_times_for_date(conn, date_iso, exclude_appt_id)
    return [
        {"time": t, "status": ("taken" if t in taken else "free")}
        for t in SLOT_TIMES
    ]


def is_slot_blocked(
    date_iso: str,
    time_s: str,
    exclude_appt_id: int | None = None,
) -> bool:
    with get_conn() as conn:
        taken = taken_times_for_date(conn, date_iso, exclude_appt_id)
    return time_s in taken


def get_appointment(appt_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, first_name, last_name, street, plz, city, phone,
                       email, preferred_date, preferred_time, created_at, status
                FROM appointments WHERE id = %s
                """,
                (appt_id,),
            )
            row = cur.fetchone()
    if row is None:
        return None
    return _normalize_row_email(_row_dict(row))


def reschedule_appointment(appt_id: int, new_date: str, new_time: str) -> None:
    new_date = new_date.strip()
    new_time = new_time.strip()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE appointments
                SET preferred_date = %s, preferred_time = %s
                WHERE id = %s
                """,
                (new_date, new_time, appt_id),
            )
            if cur.rowcount == 0:
                raise LookupError("appointment not found")
        conn.commit()
