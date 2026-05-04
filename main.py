"""German Fiber Solution GmbH & Co. KG — Glasfaser Termine (FastAPI)."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Annotated, Literal

import dotenv
import resend
from fastapi import FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.middleware.sessions import SessionMiddleware

import database as db

dotenv.load_dotenv()

logger = logging.getLogger(__name__)

RESEND_SCHEDULE_FROM = (
    "German Fiber Solution GmbH & Co. KG <onboarding@resend.dev>"
)

COMPANY_LEGAL_NAME = "German Fiber Solution GmbH & Co. KG"


def _configure_stderr_logging() -> None:
    """Serverless (e.g. Vercel) often has no handlers; ensure SMTP diagnostics reach logs."""
    root = logging.getLogger()
    if root.handlers:
        return
    level_name = (os.getenv("LOG_LEVEL") or "INFO").upper().strip()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format="%(levelname)s %(name)s %(message)s")


_configure_stderr_logging()
PUBLIC_CONTACT_PHONE = os.getenv("PUBLIC_CONTACT_PHONE", "+49 174 211 3689")
OFFICE_CONTACT_PHONE = os.getenv("OFFICE_CONTACT_PHONE", "+49 2857 486 0174")
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "frangu.tiefbau@gmail.com")
FOOTER_ADDRESS = os.getenv(
    "FOOTER_ADDRESS",
    "Lindenallee 9 · 21376 Salzhausen · Deutschland",
)


def _public_ctx(*, for_admin: bool = False) -> dict:
    header_phone = OFFICE_CONTACT_PHONE if for_admin else PUBLIC_CONTACT_PHONE
    return {
        "company_name": COMPANY_LEGAL_NAME,
        "contact_phone": header_phone,
        "footer_phone": OFFICE_CONTACT_PHONE,
        "contact_email": CONTACT_EMAIL,
        "contact_address": FOOTER_ADDRESS,
    }


def _bookable_calendar_rows(lang: Lang) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for d in db.bookable_dates_starting(db.booking_today()):
        wd = WEEKDAY_SHORT[lang][d.weekday()]
        rows.append(
            {
                "iso": d.isoformat(),
                "label": f"{wd} · {d.strftime('%d.%m.')}",
            }
        )
    return rows


def _valid_email_optional(raw: str) -> tuple[bool, str]:
    s = (raw or "").strip()
    if not s:
        return True, ""
    if not EMAIL_LOOSE_RE.match(s):
        return False, ""
    return True, s


def _format_date_de(iso_d: str) -> str:
    dt = datetime.strptime(iso_d.strip(), "%Y-%m-%d")
    return dt.strftime("%d.%m.%Y")


def _send_reschedule_email_de(
    recipient: str,
    first_name: str,
    new_date_iso: str,
    new_time: str,
) -> None:
    api_key = (
        (os.environ.get("RESEND_API_KEY") or os.getenv("RESEND_API_KEY") or "")
        .strip()
    )
    if not api_key:
        logger.warning(
            "reschedule Resend skipped: RESEND_API_KEY unset or empty in environment"
        )
        return

    from_addr = RESEND_SCHEDULE_FROM

    name = (first_name or "").strip() or "Kundin/Kunde"
    date_de = _format_date_de(new_date_iso)

    body = (
        f"Guten Tag {name},\n\n"
        "wir möchten Sie darüber informieren, dass wir Ihren gewünschten Termin leider nicht "
        "einhalten können, da wir aufgrund unseres Arbeitsablaufs etwas mehr Zeit benötigen "
        "als geplant.\n\n"
        "Daher wurde Ihr Termin für den Glasfaser-Hausanschluss verschoben.\n\n"
        f"Neuer Termin: {date_de} um {new_time} Uhr\n\n"
        "Wir bitten Sie, uns zu diesem neuen Zeitpunkt zu Hause zu empfangen. Sollten Sie Fragen "
        "haben oder der Termin nicht passen, kontaktieren Sie uns bitte.\n\n"
        "Bei Rückfragen erreichen Sie uns unter:\n"
        f"Telefon: {PUBLIC_CONTACT_PHONE}\n"
        f"E-Mail: {CONTACT_EMAIL}\n\n"
        "Mit freundlichen Grüßen\n"
        f"{COMPANY_LEGAL_NAME}\n"
    )

    resend.api_key = api_key

    params: resend.Emails.SendParams = {
        "from": from_addr,
        "to": [recipient],
        "subject": "Ihr Glasfaser-Termin wurde verschoben",
        "text": body,
        "reply_to": CONTACT_EMAIL,
    }

    logger.info(
        "reschedule Resend: sending from=%s to=%s",
        from_addr,
        recipient,
    )
    try:
        out = resend.Emails.send(params)
        eid = out.get("id") if isinstance(out, dict) else getattr(out, "id", None)
        logger.info(
            "reschedule Resend: message sent OK id=%s to=%s",
            eid,
            recipient,
        )
    except Exception:
        logger.exception(
            "reschedule Resend failed (from=%s, to=%s)",
            from_addr,
            recipient,
        )


Lang = Literal["de", "ru", "en"]

I18N: dict[Lang, dict[str, str]] = {
    "de": {
        "title": "Glasfaser — Termin",
        "brand": "German Fiber Solution GmbH & Co. KG",
        "subtitle": "Glasfaser Termine · Anmeldung",
        "first_name": "Vorname",
        "last_name": "Nachname",
        "street": "Straße & Hausnummer",
        "plz": "PLZ",
        "city": "Ort",
        "phone": "Telefon",
        "email": "E-Mail",
        "pick_date": "Datum wählen",
        "pick_time": "Uhrzeit wählen",
        "slot_loading": "Laden…",
        "preferred_date": "Wunschdatum",
        "preferred_time": "Wunschuhrzeit",
        "slot_error": "Dieser Termin ist nicht mehr frei. Bitte andere Zeit wählen.",
        "submit": "Termin anfragen",
        "lang_label": "Sprache",
        "contact": "Kontakt",
        "success_sub": "Wir haben Ihre Anfrage erhalten.",
        "fill_error": "Bitte alle Felder ausfüllen.",
        "back": "Zurück zur Anmeldung",
        "form_intro": "Wir verlegen Glasfaser in Ihrer Straße.\nVereinbaren Sie jetzt Ihren kostenlosen Hausanschluss-Termin.",
    },
    "ru": {
        "title": "Glasfaser — запись",
        "brand": "German Fiber Solution GmbH & Co. KG",
        "subtitle": "Glasfaser Termine · запись на визит",
        "first_name": "Имя",
        "last_name": "Фамилия",
        "street": "Улица и номер дома",
        "plz": "Индекс (PLZ)",
        "city": "Город",
        "phone": "Телефон",
        "email": "E-mail",
        "pick_date": "Выберите дату",
        "pick_time": "Выберите время",
        "slot_loading": "Загрузка…",
        "preferred_date": "Желаемая дата",
        "preferred_time": "Желаемое время",
        "slot_error": "Это время уже занято. Выберите другое.",
        "submit": "Отправить заявку",
        "lang_label": "Язык",
        "contact": "Контакт",
        "success_sub": "Мы получили вашу заявку.",
        "fill_error": "Пожалуйста, заполните все поля.",
        "back": "Назад к форме",
        "form_intro": "Мы прокладываем оптоволоконный кабель на вашей улице.\nЗапишитесь на бесплатный визит для подключения к дому.",
    },
    "en": {
        "title": "Glasfaser — appointment",
        "brand": "German Fiber Solution GmbH & Co. KG",
        "subtitle": "Glasfaser Termine · book a slot",
        "first_name": "First name",
        "last_name": "Last name",
        "street": "Street & house number",
        "plz": "Postal code (PLZ)",
        "city": "City",
        "phone": "Phone",
        "email": "Email",
        "pick_date": "Pick a date",
        "pick_time": "Pick a time",
        "slot_loading": "Loading…",
        "preferred_date": "Preferred date",
        "preferred_time": "Preferred time",
        "slot_error": "This slot is no longer available. Please choose another time.",
        "submit": "Request appointment",
        "lang_label": "Language",
        "contact": "Contact",
        "success_sub": "We have received your request.",
        "fill_error": "Please fill in all fields.",
        "back": "Back to form",
        "form_intro": "We install fiber in your street.\nBook your free home connection appointment now.",
    },
}

ADMIN_STATUS_LABELS = {
    "new": {"de": "Neu", "ru": "Новая", "en": "New"},
    "confirmed": {"de": "Bestätigt", "ru": "Подтверждена", "en": "Confirmed"},
    "completed": {"de": "Erledigt", "ru": "Выполнена", "en": "Completed"},
}

ADMIN_UI = {
    "de": {
        "title": "Admin — Glasfaser Termine",
        "login_title": "Anmeldung",
        "password": "Passwort",
        "login_btn": "Einloggen",
        "login_err": "Falsches Passwort.",
        "logout": "Abmelden",
        "refresh": "Aktualisieren",
        "table_name": "Name",
        "table_address": "Adresse",
        "table_phone": "Telefon",
        "table_email": "E-Mail",
        "table_datetime": "Wunschtermin",
        "table_status": "Status",
        "table_created": "Eingegangen",
        "delete": "Löschen",
        "reschedule": "Verschieben",
        "reschedule_title": "Termin verschieben",
        "reschedule_confirm": "Speichern",
        "reschedule_cancel": "Abbrechen",
        "pick_date": "Datum wählen",
        "pick_time": "Uhrzeit wählen",
        "slot_loading": "Laden…",
        "slot_conflict_admin": "Dieser Zeitslot ist schon vergeben.",
        "empty": "Keine Terminanfragen.",
        "lang_admin": "Admin-Sprache",
    },
    "ru": {
        "title": "Админ — Glasfaser Termine",
        "login_title": "Вход",
        "password": "Пароль",
        "login_btn": "Войти",
        "login_err": "Неверный пароль.",
        "logout": "Выйти",
        "refresh": "Обновить",
        "table_name": "Имя",
        "table_address": "Адрес",
        "table_phone": "Телефон",
        "table_email": "E-mail",
        "table_datetime": "Желаемые дата/время",
        "table_status": "Статус",
        "table_created": "Создано",
        "delete": "Удалить",
        "reschedule": "Перенести",
        "reschedule_title": "Перенос записи",
        "reschedule_confirm": "Сохранить",
        "reschedule_cancel": "Отмена",
        "pick_date": "Выберите дату",
        "pick_time": "Выберите время",
        "slot_loading": "Загрузка…",
        "slot_conflict_admin": "Это время уже занято.",
        "empty": "Заявок пока нет.",
        "lang_admin": "Язык админки",
    },
    "en": {
        "title": "Admin — Glasfaser Termine",
        "login_title": "Sign in",
        "password": "Password",
        "login_btn": "Log in",
        "login_err": "Wrong password.",
        "logout": "Log out",
        "refresh": "Refresh",
        "table_name": "Name",
        "table_address": "Address",
        "table_phone": "Phone",
        "table_email": "Email",
        "table_datetime": "Preferred slot",
        "table_status": "Status",
        "table_created": "Received",
        "delete": "Delete",
        "reschedule": "Reschedule",
        "reschedule_title": "Reschedule appointment",
        "reschedule_confirm": "Save",
        "reschedule_cancel": "Cancel",
        "pick_date": "Pick a date",
        "pick_time": "Pick a time",
        "slot_loading": "Loading…",
        "slot_conflict_admin": "That time slot is already taken.",
        "empty": "No appointments yet.",
        "lang_admin": "Admin language",
    },
}

WEEKDAY_SHORT: dict[Lang, list[str]] = {
    "de": ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"],
    "ru": ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
}

EMAIL_LOOSE_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_j = Environment(
    loader=FileSystemLoader(os.path.join(BASE_DIR, "templates")),
    autoescape=select_autoescape(["html", "xml"]),
)

app = FastAPI(
    title="German Fiber Solution GmbH & Co. KG — Glasfaser Termine"
)

session_secret = os.getenv("SESSION_SECRET", "dev-secret-change-in-production")
app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret,
    https_only=bool(os.getenv("VERCEL")),
)

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

db.init_db()


def _normalize_lang(lang: str | None) -> Lang:
    if lang in ("de", "ru", "en"):
        return lang  # type: ignore[return-value]
    return "de"


def _admin_ok(request: Request) -> bool:
    return bool(request.session.get("admin"))


def _admin_i18n_json() -> str:
    return json.dumps({"ui": ADMIN_UI, "status": ADMIN_STATUS_LABELS}, ensure_ascii=False)


def _wants_json(request: Request) -> bool:
    accept = request.headers.get("accept") or ""
    return "application/json" in accept


def _wants_json_status_update(request: Request) -> bool:
    return _wants_json(request)


COOKIE_ADMIN_LANG = {
    "max_age": 60 * 60 * 24 * 365,
    "httponly": False,
}


@app.get("/", response_class=HTMLResponse)
async def form_page(request: Request, lang: str | None = None):
    l = _normalize_lang(lang or request.cookies.get("lang"))
    t = I18N[l]
    html = env_j.get_template("form.html").render(
        request=request,
        t=t,
        lang=l,
        contact_name="Evgheni Frangu",
        bookable_dates=_bookable_calendar_rows(l),
        **_public_ctx(),
    )
    resp = HTMLResponse(content=html)
    if lang in ("de", "ru", "en"):
        resp.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365, httponly=False)
    return resp


@app.get("/api/slots")
async def api_slots(
    date: str,
    exclude_appt_id: int | None = None,
):
    if not db.parse_iso_date_yyyy_mm_dd(date):
        raise HTTPException(status_code=400, detail="invalid date")
    if not db.is_bookable_now(date):
        raise HTTPException(status_code=400, detail="date not bookable")
    excl = exclude_appt_id if exclude_appt_id and exclude_appt_id > 0 else None
    return JSONResponse(
        {"date": date, "slots": db.slots_for_date(date, excl)}
    )


@app.post("/submit", response_class=HTMLResponse)
async def submit(
    request: Request,
    first_name: Annotated[str, Form()],
    last_name: Annotated[str, Form()],
    street: Annotated[str, Form()],
    plz: Annotated[str, Form()],
    city: Annotated[str, Form()],
    phone: Annotated[str, Form()],
    preferred_date: Annotated[str, Form()],
    preferred_time: Annotated[str, Form()],
    lang: Annotated[str, Form()] = "de",
    email: Annotated[str, Form()] = "",
):
    l = _normalize_lang(lang)
    t = I18N[l]
    email_ok, email_clean = _valid_email_optional(email)
    norm_time = db.normalize_slot_time(preferred_time)

    def _render_form(
        *,
        error: bool = False,
        slot_error: bool = False,
        form_data_override: dict | None = None,
        status_http: int = status.HTTP_400_BAD_REQUEST,
    ) -> HTMLResponse:
        base = form_data_override or {
            "first_name": first_name,
            "last_name": last_name,
            "street": street,
            "plz": plz,
            "city": city,
            "phone": phone,
            "email": email_clean if email_ok else email,
            "preferred_date": preferred_date,
            "preferred_time": preferred_time,
        }
        html_out = env_j.get_template("form.html").render(
            request=request,
            t=t,
            lang=l,
            contact_name="Evgheni Frangu",
            bookable_dates=_bookable_calendar_rows(l),
            error=error,
            slot_error=slot_error,
            form_data=base,
            **_public_ctx(),
        )
        return HTMLResponse(content=html_out, status_code=status_http)

    base_fields_ok = bool(
        first_name.strip()
        and last_name.strip()
        and street.strip()
        and plz.strip()
        and city.strip()
        and phone.strip()
        and preferred_date.strip()
        and preferred_time.strip()
    )
    if not base_fields_ok:
        return _render_form(error=True)

    if not email_ok:
        return _render_form(error=True)

    if not norm_time:
        return _render_form(slot_error=False, error=True)

    if not db.is_bookable_now(preferred_date.strip()):
        return _render_form(slot_error=True)

    if db.is_slot_blocked(preferred_date.strip(), norm_time):
        return _render_form(slot_error=True)

    db.create_appointment(
        first_name,
        last_name,
        street,
        plz,
        city,
        phone,
        email_clean,
        preferred_date.strip(),
        norm_time,
    )
    return RedirectResponse(
        url=f"/success?lang={l}", status_code=status.HTTP_303_SEE_OTHER
    )


@app.get("/success", response_class=HTMLResponse)
async def success_page(request: Request, lang: str | None = None):
    l = _normalize_lang(lang or request.cookies.get("lang"))
    t = I18N[l]
    html = env_j.get_template("success.html").render(
        request=request,
        t=t,
        lang=l,
        back_lang=l,
        **_public_ctx(),
    )
    return HTMLResponse(content=html)


@app.post("/admin/login", response_class=HTMLResponse)
async def admin_login_post(
    request: Request,
    password: Annotated[str, Form()],
    admin_lang: Annotated[str, Form()] = "de",
):
    expected = os.getenv("ADMIN_PASSWORD", "")
    al = _normalize_lang(admin_lang)
    at = ADMIN_UI[al]
    if not expected or password != expected:
        html = env_j.get_template("admin.html").render(
            request=request,
            logged_in=False,
            login_error=True,
            rows=[],
            admin_lang=al,
            at=at,
            status_labels=ADMIN_STATUS_LABELS,
            admin_i18n_json="",
            bookable_slot_calendar_json="[]",
            **_public_ctx(for_admin=True),
        )
        resp = HTMLResponse(content=html, status_code=status.HTTP_401_UNAUTHORIZED)
        resp.set_cookie("admin_lang", al, **COOKIE_ADMIN_LANG)
        return resp
    request.session["admin"] = True
    request.session["admin_lang"] = al
    resp = RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie("admin_lang", al, **COOKIE_ADMIN_LANG)
    return resp


@app.get("/admin/logout")
async def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, lang: str | None = None):
    al = _normalize_lang(
        lang or request.session.get("admin_lang") or request.cookies.get("admin_lang")  # type: ignore[arg-type]
    )
    at = ADMIN_UI[al]
    if not _admin_ok(request):
        html = env_j.get_template("admin.html").render(
            request=request,
            logged_in=False,
            login_error=False,
            rows=[],
            admin_lang=al,
            at=at,
            status_labels=ADMIN_STATUS_LABELS,
            admin_i18n_json="",
            bookable_slot_calendar_json="[]",
            **_public_ctx(for_admin=True),
        )
        resp = HTMLResponse(content=html)
        if lang in ("de", "ru", "en"):
            resp.set_cookie("admin_lang", _normalize_lang(lang), **COOKIE_ADMIN_LANG)
        return resp

    if lang in ("de", "ru", "en"):
        al_n = _normalize_lang(lang)
        request.session["admin_lang"] = al_n
        al = al_n
        at = ADMIN_UI[al]

    rows = db.list_appointments()
    bookable_slot_calendar = json.dumps(
        _bookable_calendar_rows(al), ensure_ascii=False
    )
    resp = HTMLResponse(
        content=env_j.get_template("admin.html").render(
            request=request,
            logged_in=True,
            login_error=False,
            rows=rows,
            admin_lang=al,
            at=at,
            status_labels=ADMIN_STATUS_LABELS,
            admin_i18n_json=_admin_i18n_json(),
            bookable_slot_calendar_json=bookable_slot_calendar,
            **_public_ctx(for_admin=True),
        )
    )
    resp.set_cookie("admin_lang", al, **COOKIE_ADMIN_LANG)
    return resp


@app.get("/admin/api/appointments")
async def admin_api_appointments(request: Request):
    if not _admin_ok(request):
        raise HTTPException(status_code=401)
    return JSONResponse({"appointments": db.list_appointments()})


@app.post("/admin/delete/{appt_id}")
async def admin_delete(request: Request, appt_id: int):
    if not _admin_ok(request):
        raise HTTPException(status_code=401)
    db.delete_appointment(appt_id)
    if _wants_json(request):
        return JSONResponse({"ok": True})
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/lang")
async def admin_set_lang(
    request: Request,
    lang: Annotated[str, Form()],
):
    if not _admin_ok(request):
        raise HTTPException(status_code=401)
    al = _normalize_lang(lang)
    request.session["admin_lang"] = al
    r = JSONResponse({"ok": True, "lang": al})
    r.set_cookie("admin_lang", al, **COOKIE_ADMIN_LANG)
    return r


@app.post("/admin/status/{appt_id}")
async def admin_status(
    request: Request,
    appt_id: int,
    status_value: Annotated[str, Form(alias="status")],
):
    if not _admin_ok(request):
        raise HTTPException(status_code=401)
    if status_value not in ("new", "confirmed", "completed"):
        raise HTTPException(status_code=400)
    db.set_appointment_status(appt_id, status_value)
    if _wants_json_status_update(request):
        return JSONResponse({"ok": True, "status": status_value})
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/reschedule/{appt_id}")
async def admin_reschedule(
    request: Request,
    appt_id: int,
    new_date: Annotated[str, Form()],
    new_time: Annotated[str, Form()],
):
    if not _admin_ok(request):
        raise HTTPException(status_code=401)

    apt = db.get_appointment(appt_id)
    if not apt:
        raise HTTPException(status_code=404, detail="not found")

    nd = new_date.strip()
    nt = db.normalize_reschedule_time(new_time)
    if not nt:
        raise HTTPException(status_code=400, detail="invalid time")
    if not db.is_bookable_now(nd):
        raise HTTPException(status_code=400, detail="invalid date")

    try:
        db.reschedule_appointment(appt_id, nd, nt)
    except LookupError:
        raise HTTPException(status_code=404, detail="not found") from None

    to_addr = (apt.get("email") or "").strip()
    if not to_addr:
        logger.info(
            "reschedule appt_id=%s: no client email stored, notification skipped",
            appt_id,
        )
    else:
        logger.info(
            "reschedule appt_id=%s: attempting email to %s",
            appt_id,
            to_addr,
        )
        _send_reschedule_email_de(
            to_addr, apt.get("first_name") or "", nd, nt
        )

    if _wants_json(request):
        return JSONResponse(
            {
                "ok": True,
                "preferred_date": nd,
                "preferred_time": nt,
            }
        )
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
