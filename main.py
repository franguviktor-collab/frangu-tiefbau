"""Frangu Tiefbau — Glasfaser Termine (FastAPI)."""

import json
import os
from typing import Annotated, Literal

import dotenv
from fastapi import FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.middleware.sessions import SessionMiddleware

import database as db

dotenv.load_dotenv()

CONTACT_PHONE = os.getenv("CONTACT_PHONE", "+49 174 211 3689")
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "frangu.tiefbau@gmail.com")
FOOTER_ADDRESS = os.getenv(
    "FOOTER_ADDRESS",
    "Krümpelstraße 11 · 49504 Lotte · Deutschland",
)


def _public_ctx() -> dict:
    return {
        "contact_phone": CONTACT_PHONE,
        "contact_email": CONTACT_EMAIL,
        "contact_address": FOOTER_ADDRESS,
    }


Lang = Literal["de", "ru", "en"]

I18N: dict[Lang, dict[str, str]] = {
    "de": {
        "title": "Glasfaser — Termin",
        "brand": "Frangu Tiefbau",
        "subtitle": "Glasfaser Termine · Anmeldung",
        "first_name": "Vorname",
        "last_name": "Nachname",
        "street": "Straße & Hausnummer",
        "plz": "PLZ",
        "city": "Ort",
        "phone": "Telefon",
        "preferred_date": "Wunschdatum",
        "preferred_time": "Wunschuhrzeit",
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
        "brand": "Frangu Tiefbau",
        "subtitle": "Glasfaser Termine · запись на визит",
        "first_name": "Имя",
        "last_name": "Фамилия",
        "street": "Улица и номер дома",
        "plz": "Индекс (PLZ)",
        "city": "Город",
        "phone": "Телефон",
        "preferred_date": "Желаемая дата",
        "preferred_time": "Желаемое время",
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
        "brand": "Frangu Tiefbau",
        "subtitle": "Glasfaser Termine · book a slot",
        "first_name": "First name",
        "last_name": "Last name",
        "street": "Street & house number",
        "plz": "Postal code (PLZ)",
        "city": "City",
        "phone": "Phone",
        "preferred_date": "Preferred date",
        "preferred_time": "Preferred time",
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
        "table_datetime": "Wunschtermin",
        "table_status": "Status",
        "table_created": "Eingegangen",
        "delete": "Löschen",
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
        "table_datetime": "Желаемые дата/время",
        "table_status": "Статус",
        "table_created": "Создано",
        "delete": "Удалить",
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
        "table_datetime": "Preferred slot",
        "table_status": "Status",
        "table_created": "Received",
        "delete": "Delete",
        "empty": "No appointments yet.",
        "lang_admin": "Admin language",
    },
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_j = Environment(
    loader=FileSystemLoader(os.path.join(BASE_DIR, "templates")),
    autoescape=select_autoescape(["html", "xml"]),
)

app = FastAPI(title="Frangu Tiefbau — Glasfaser Termine")

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


def _wants_json_status_update(request: Request) -> bool:
    accept = request.headers.get("accept") or ""
    return "application/json" in accept


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
        **_public_ctx(),
    )
    resp = HTMLResponse(content=html)
    if lang in ("de", "ru", "en"):
        resp.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365, httponly=False)
    return resp


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
):
    l = _normalize_lang(lang)
    if not all(
        [
            first_name.strip(),
            last_name.strip(),
            street.strip(),
            plz.strip(),
            city.strip(),
            phone.strip(),
            preferred_date.strip(),
            preferred_time.strip(),
        ]
    ):
        t = I18N[l]
        html = env_j.get_template("form.html").render(
            request=request,
            t=t,
            lang=l,
            contact_name="Evgheni Frangu",
            **_public_ctx(),
            error=True,
            form_data={
                "first_name": first_name,
                "last_name": last_name,
                "street": street,
                "plz": plz,
                "city": city,
                "phone": phone,
                "preferred_date": preferred_date,
                "preferred_time": preferred_time,
            },
        )
        return HTMLResponse(content=html, status_code=status.HTTP_400_BAD_REQUEST)

    db.create_appointment(
        first_name, last_name, street, plz, city, phone, preferred_date, preferred_time
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
            **_public_ctx(),
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
            **_public_ctx(),
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
            **_public_ctx(),
        )
    )
    resp.set_cookie("admin_lang", al, **COOKIE_ADMIN_LANG)
    return resp


@app.post("/admin/delete/{appt_id}")
async def admin_delete(request: Request, appt_id: int):
    if not _admin_ok(request):
        raise HTTPException(status_code=401)
    db.delete_appointment(appt_id)
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
