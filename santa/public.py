"""Главная и личный конверт участника."""
import re
from datetime import timedelta

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from . import db, models
from .crypto import seal
from .helpers import clean_text, iso, iso_now, parse_iso, plural, utcnow

bp = Blueprint("public", __name__)

PIN_RE = re.compile(r"\d{4,6}")
MAX_PIN_FAILS = 5
PIN_LOCK_MINUTES = 15
MAX_LETTER = 1500
MAX_MESSAGE = 600
MAX_THREAD = 200


@bp.get("/")
def index():
    count = db.query("SELECT COUNT(*) AS c FROM participants", one=True)["c"]
    return render_template("index.html", count=count, drawn=models.is_drawn())


# ---------------------------------------------------------------- доступ

def _participant(token):
    p = models.by_token(token)
    if p is None:
        abort(404)
    return p


def _authed(p) -> bool:
    return p["pin_hash"] is not None and session.get("pp", {}).get(str(p["id"])) == p["session_ver"]


def _grant(p):
    pp = dict(session.get("pp", {}))
    pp[str(p["id"])] = p["session_ver"]
    session["pp"] = pp
    session.permanent = True


def _home(token, anchor=None):
    return redirect(url_for("public.participant", token=token, _anchor=anchor))


def _require(token, as_json=False):
    p = _participant(token)
    if not _authed(p):
        if as_json:
            abort(401)
        flash("Сначала войди со своим PIN.", "error")
        abort(_home(token))
    return p


# ---------------------------------------------------------------- страница

@bp.get("/p/<token>")
def participant(token):
    p = _participant(token)
    if p["pin_hash"] is None:
        return render_template("participant/claim.html", p=p)
    if not _authed(p):
        lock = parse_iso(p["locked_until"])
        return render_template("participant/pin.html", p=p, locked=bool(lock and lock > utcnow()))

    drawn = models.is_drawn()
    giftee, gift_ready, broken = None, False, False
    santa_id = None
    to_giftee, from_santa = [], []
    if drawn:
        giftee, gift_ready, broken = models.giftee_of(p["id"])
        santa_id = models.santa_of(p["id"])
        if giftee:
            to_giftee = models.thread(p["id"])
        if santa_id:
            from_santa = models.thread(santa_id)

    seen_giftee, seen_santa = p["seen_giftee_at"] or "", p["seen_santa_at"] or ""
    for m in to_giftee:
        m["new"] = not m["from_santa"] and m["at"] > seen_giftee
    for m in from_santa:
        m["new"] = m["from_santa"] and m["at"] > seen_santa
    now = iso_now()
    db.execute("UPDATE participants SET seen_giftee_at = ?, seen_santa_at = ? WHERE id = ?", (now, now, p["id"]))
    db.commit()

    return render_template(
        "participant/home.html",
        p=p,
        drawn=drawn,
        giftee=giftee,
        gift_ready=gift_ready,
        broken=broken,
        has_santa=santa_id is not None,
        to_giftee=to_giftee,
        from_santa=from_santa,
        new_from_santa=sum(1 for m in from_santa if m["new"]),
        giftee_letter=giftee is not None and models.letter_filled(giftee),
    )


@bp.post("/p/<token>/claim")
def claim(token):
    p = _participant(token)
    if p["pin_hash"] is not None:
        flash("PIN уже придуман. Введи его, чтобы войти.", "info")
        return _home(token)
    pin = request.form.get("pin", "").strip()
    pin2 = request.form.get("pin2", "").strip()
    if not PIN_RE.fullmatch(pin):
        flash("PIN — это от 4 до 6 цифр.", "error")
        return _home(token)
    if pin != pin2:
        flash("PIN-коды не совпали. Попробуй ещё раз.", "error")
        return _home(token)
    cur = db.execute(
        "UPDATE participants SET pin_hash = ?, pin_set_at = ?, failed_pins = 0, locked_until = NULL "
        "WHERE id = ? AND pin_hash IS NULL",
        (generate_password_hash(pin), iso_now(), p["id"]),
    )
    db.commit()
    if cur.rowcount != 1:
        flash("Кто-то успел придумать PIN раньше. Введи его или попроси организатора сбросить.", "error")
        return _home(token)
    _grant(models.by_id(p["id"]))
    flash("Готово! Теперь конверт открывается только твоим PIN.", "ok")
    return _home(token)


@bp.post("/p/<token>/login")
def login(token):
    p = _participant(token)
    if p["pin_hash"] is None:
        return _home(token)
    lock = parse_iso(p["locked_until"])
    if lock and lock > utcnow():
        flash("Слишком много попыток. Подожди немного и попробуй снова.", "error")
        return _home(token)

    pin = request.form.get("pin", "").strip()
    if PIN_RE.fullmatch(pin) and check_password_hash(p["pin_hash"], pin):
        db.execute("UPDATE participants SET failed_pins = 0, locked_until = NULL WHERE id = ?", (p["id"],))
        db.commit()
        _grant(p)
        return _home(token)

    fails = p["failed_pins"] + 1
    if fails >= MAX_PIN_FAILS:
        until = iso(utcnow() + timedelta(minutes=PIN_LOCK_MINUTES))
        db.execute("UPDATE participants SET failed_pins = 0, locked_until = ? WHERE id = ?", (until, p["id"]))
        flash(f"PIN не подошёл {MAX_PIN_FAILS} раз подряд — вход закрыт на {PIN_LOCK_MINUTES} минут.", "error")
    else:
        db.execute("UPDATE participants SET failed_pins = ? WHERE id = ?", (fails, p["id"]))
        left = MAX_PIN_FAILS - fails
        flash(f"Неверный PIN. {plural(left, 'Осталась', 'Осталось', 'Осталось')} {left} "
              f"{plural(left, 'попытка', 'попытки', 'попыток')}.", "error")
    db.commit()
    return _home(token)


@bp.post("/p/<token>/logout")
def logout(token):
    p = _participant(token)
    pp = dict(session.get("pp", {}))
    pp.pop(str(p["id"]), None)
    session["pp"] = pp
    flash("Конверт закрыт. До встречи!", "ok")
    return redirect(url_for("public.index"))


# ---------------------------------------------------------------- действия

@bp.post("/p/<token>/letter")
def letter(token):
    p = _require(token)
    values = [clean_text(request.form.get(k, ""), MAX_LETTER) for k in ("wishes", "dislikes", "about")]
    db.execute(
        "UPDATE participants SET wishes = ?, dislikes = ?, about = ?, letter_at = ? WHERE id = ?",
        (*values, iso_now(), p["id"]),
    )
    db.commit()
    flash("Письмо отправлено! Твой Тайный Санта прочитает его в своём конверте.", "ok")
    return _home(token, "letter")


@bp.post("/p/<token>/open")
def open_envelope(token):
    p = _require(token, as_json=True)
    if not models.is_drawn():
        return jsonify(ok=False), 409
    db.execute("UPDATE participants SET opened_at = COALESCE(opened_at, ?) WHERE id = ?", (iso_now(), p["id"]))
    db.commit()
    return jsonify(ok=True)


@bp.post("/p/<token>/gift")
def gift(token):
    p = _require(token)
    ready = 1 if request.form.get("ready") == "1" else 0
    cur = db.execute("UPDATE assignments SET gift_ready = ? WHERE giver_id = ?", (ready, p["id"]))
    db.commit()
    if cur.rowcount:
        flash("Отмечено: подарок готов! Осталось дождаться праздника." if ready else "Отметка снята.", "ok")
    return _home(token, "giftee")


@bp.post("/p/<token>/ask")
def ask(token):
    p = _require(token)
    giftee, _, _ = models.giftee_of(p["id"])
    if giftee is None:
        flash("Жеребьёвка ещё не проведена — спрашивать пока некого.", "error")
        return _home(token)
    text = clean_text(request.form.get("text", ""), MAX_MESSAGE)
    if not text:
        flash("Пустую телеграмму не отправить.", "error")
    elif models.thread_size(p["id"]) >= MAX_THREAD:
        flash("Телеграф устал: в этой переписке уже слишком много сообщений.", "error")
    else:
        db.execute(
            "INSERT INTO messages(giver_id, from_santa, sealed, created_at) VALUES (?, 1, ?, ?)",
            (p["id"], seal(text), iso_now()),
        )
        db.commit()
        flash(f"Телеграмма ушла. {giftee['name']} не узнает, от кого она.", "ok")
    return _home(token, "questions")


@bp.post("/p/<token>/reply")
def reply(token):
    p = _require(token)
    santa_id = models.santa_of(p["id"])
    if santa_id is None:
        flash("Тайный Санта ещё не назначен.", "error")
        return _home(token)
    text = clean_text(request.form.get("text", ""), MAX_MESSAGE)
    if not text:
        flash("Пустую телеграмму не отправить.", "error")
    elif models.thread_size(santa_id) >= MAX_THREAD:
        flash("Телеграф устал: в этой переписке уже слишком много сообщений.", "error")
    else:
        db.execute(
            "INSERT INTO messages(giver_id, from_santa, sealed, created_at) VALUES (?, 0, ?, ?)",
            (santa_id, seal(text), iso_now()),
        )
        db.commit()
        flash("Ответ ушёл твоему Тайному Санте.", "ok")
    return _home(token, "santa")
