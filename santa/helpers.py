"""Даты по-русски, склонения, ссылки в тексте, фильтры шаблонов."""
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import current_app, url_for
from markupsafe import Markup, escape

MONTHS_GEN = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля",
              "августа", "сентября", "октября", "ноября", "декабря")
MONTHS_NOM = ("январь", "февраль", "март", "апрель", "май", "июнь", "июль",
              "август", "сентябрь", "октябрь", "ноябрь", "декабрь")
WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")

URL_RE = re.compile(r"(https?://[^\s<>\"']+)")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def iso_now() -> str:
    return iso(utcnow())


def tz() -> ZoneInfo:
    return ZoneInfo(current_app.config["TIMEZONE"])


def parse_iso(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_local(value):
    """'2026-12-27T18:00' в часовом поясе события."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=tz())


def plural(n, one, few, many):
    n = abs(int(n)) % 100
    if 11 <= n <= 19:
        return many
    n %= 10
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


def when(value) -> str:
    """UTC ISO → «23 ноября в 14:05» / «сегодня в 09:12»."""
    dt = parse_iso(value)
    if not dt:
        return ""
    local = dt.astimezone(tz())
    today = utcnow().astimezone(tz()).date()
    delta = (today - local.date()).days
    if delta == 0:
        day = "сегодня"
    elif delta == 1:
        day = "вчера"
    else:
        day = f"{local.day} {MONTHS_GEN[local.month - 1]}"
    return f"{day} в {local:%H:%M}"


def linkify(text) -> Markup:
    if not text:
        return Markup("")
    escaped = str(escape(text))

    def repl(match):
        url, trail = match.group(1), ""
        while url and url[-1] in ".,;:!?)»":
            trail = url[-1] + trail
            url = url[:-1]
        label = url.split("://", 1)[-1]
        if len(label) > 42:
            label = label[:40] + "…"
        return f'<a href="{url}" target="_blank" rel="noopener noreferrer nofollow">{label}</a>{trail}'

    return Markup(URL_RE.sub(repl, escaped).replace("\n", "<br>"))


def clean_text(value, limit: int) -> str:
    text = (value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:limit]


def clean_line(value, limit: int) -> str:
    return " ".join((value or "").split())[:limit]


def new_token() -> str:
    return secrets.token_urlsafe(9)


def event_info() -> dict:
    from . import db

    raw = db.settings()
    info = {k: v for k, v in raw.items() if not k.startswith("admin_")}
    dt = parse_local(raw.get("exchange_at"))
    info["year"] = (dt or utcnow()).year
    if dt:
        info.update(
            exchange_ms=int(dt.timestamp() * 1000),
            ex_day=dt.day,
            ex_month=MONTHS_NOM[dt.month - 1],
            ex_month_gen=MONTHS_GEN[dt.month - 1],
            ex_weekday=WEEKDAYS[dt.weekday()],
            ex_time=f"{dt:%H:%M}",
            ex_past=dt <= utcnow(),
        )
    return info


def register_helpers(app):
    static_dir = Path(app.static_folder)

    def static(path: str) -> str:
        try:
            version = int((static_dir / path).stat().st_mtime)
        except OSError:
            version = 0
        return url_for("static", filename=path, v=version)

    app.jinja_env.filters.update(when=when, linkify=linkify)
    app.jinja_env.globals.update(static=static, plural=plural)

    @app.context_processor
    def inject_event():
        return {"ev": event_info()}
