"""Книга почтмейстера: участники, исключения, жеребьёвка, настройки.

Организатор видит только статусы (вошёл, написал письмо, вскрыл конверт,
подарок готов). Кто кому дарит — нигде на этих страницах не выводится.
"""
import hashlib
import hmac
import re
from datetime import timedelta
from functools import wraps

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from . import db, models
from .crypto import seal
from .draw import DrawError, cycle_count, draw, mutual_count
from .helpers import clean_line, clean_text, iso, iso_now, new_token, parse_iso, parse_local, plural, utcnow

bp = Blueprint("admin", __name__, url_prefix="/admin")

MAX_FAILS = 8
LOCK_MINUTES = 10
MAX_PEOPLE = 300


# ---------------------------------------------------------------- вход

def _password_base() -> str:
    env = current_app.config.get("ADMIN_PASSWORD")
    return ("env:" + env) if env else ("db:" + (db.setting("admin_hash") or ""))


def _fingerprint() -> str:
    key = current_app.secret_key.encode()
    return hmac.new(key, _password_base().encode(), hashlib.sha256).hexdigest()[:32]


def is_admin() -> bool:
    fp = session.get("admin")
    return bool(fp) and hmac.compare_digest(fp, _fingerprint())


def _configured() -> bool:
    return bool(current_app.config.get("ADMIN_PASSWORD") or db.setting("admin_hash"))


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_admin():
            return redirect(url_for("admin.login"))
        return view(*args, **kwargs)
    return wrapped


def _back(anchor=None):
    return redirect(url_for("admin.dashboard", _anchor=anchor))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if not _configured():
        return redirect(url_for("admin.setup"))
    if is_admin():
        return redirect(url_for("admin.dashboard"))
    if request.method == "POST":
        lock = parse_iso(db.setting("admin_lock_until"))
        if lock and lock > utcnow():
            mins = int((lock - utcnow()).total_seconds() // 60) + 1
            flash(f"Слишком много неверных попыток. Попробуйте через {mins} "
                  f"{plural(mins, 'минуту', 'минуты', 'минут')}.", "error")
            return redirect(url_for("admin.login"))

        password = request.form.get("password", "")
        env = current_app.config.get("ADMIN_PASSWORD")
        if env:
            ok = hmac.compare_digest(password.encode(), env.encode())
        else:
            ok = check_password_hash(db.setting("admin_hash"), password)
        if ok:
            db.del_setting("admin_fails")
            db.del_setting("admin_lock_until")
            db.commit()
            session["admin"] = _fingerprint()
            session.permanent = True
            return redirect(url_for("admin.dashboard"))

        fails = int(db.setting("admin_fails") or 0) + 1
        if fails >= MAX_FAILS:
            db.set_setting("admin_lock_until", iso(utcnow() + timedelta(minutes=LOCK_MINUTES)))
            db.set_setting("admin_fails", "0")
            flash(f"Пароль неверный {MAX_FAILS} раз подряд — вход закрыт на {LOCK_MINUTES} минут.", "error")
        else:
            db.set_setting("admin_fails", str(fails))
            flash("Пароль не подошёл.", "error")
        db.commit()
        return redirect(url_for("admin.login"))
    return render_template("admin/login.html")


@bp.route("/setup", methods=["GET", "POST"])
def setup():
    if _configured():
        return redirect(url_for("admin.login"))
    if request.method == "POST":
        password = request.form.get("password", "")
        if len(password) < 8:
            flash("Пароль — минимум 8 символов.", "error")
        elif password != request.form.get("password2", ""):
            flash("Пароли не совпали.", "error")
        else:
            db.set_setting("admin_hash", generate_password_hash(password))
            db.commit()
            session["admin"] = _fingerprint()
            session.permanent = True
            flash("Книга почтмейстера открыта. Добавьте участников.", "ok")
            return redirect(url_for("admin.dashboard"))
        return redirect(url_for("admin.setup"))
    return render_template("admin/setup.html")


@bp.post("/logout")
def logout():
    session.pop("admin", None)
    return redirect(url_for("public.index"))


# ---------------------------------------------------------------- книга

@bp.get("/")
@admin_required
def dashboard():
    people = models.people()
    drawn = models.is_drawn()
    ready = {r["giver_id"]: bool(r["gift_ready"]) for r in db.query("SELECT giver_id, gift_ready FROM assignments")}
    rows = [
        {
            "p": p,
            "link": models.link_for(p),
            "claimed": p["pin_hash"] is not None,
            "letter": models.letter_filled(p),
            "opened": bool(p["opened_at"]),
            "gift": ready.get(p["id"], False),
        }
        for p in people
    ]
    stats = {
        "total": len(rows),
        "claimed": sum(r["claimed"] for r in rows),
        "letters": sum(r["letter"] for r in rows),
        "opened": sum(r["opened"] for r in rows),
        "gifts": sum(r["gift"] for r in rows),
    }
    exclusions = db.query(
        "SELECT e.a_id, e.b_id, a.name AS a_name, b.name AS b_name FROM exclusions e "
        "JOIN participants a ON a.id = e.a_id JOIN participants b ON b.id = e.b_id"
    )
    exclusions = sorted(exclusions, key=lambda e: (e["a_name"].casefold(), e["b_name"].casefold()))
    groups = sorted({p["grp"] for p in people if p["grp"]}, key=str.casefold)
    group_sizes = {}
    for p in people:
        if p["grp"]:
            group_sizes[p["grp"]] = group_sizes.get(p["grp"], 0) + 1
    links_text = "\n".join(f"{r['p']['name']} — {r['link']}" for r in rows)
    meta = {
        "at": db.setting("draw_at"),
        "count": int(db.setting("draw_count") or 0),
        "cycles": int(db.setting("draw_cycles") or 0),
        "mutual": int(db.setting("draw_mutual") or 0),
    }
    return render_template(
        "admin/dashboard.html",
        rows=rows, stats=stats, drawn=drawn, exclusions=exclusions,
        groups=groups, group_sizes=group_sizes, links_text=links_text, meta=meta,
    )


@bp.post("/participants")
@admin_required
def add_participants():
    if models.is_drawn():
        flash("Конверты уже запечатаны. Чтобы добавить людей, сначала отмените жеребьёвку.", "error")
        return _back("people")
    group = clean_line(request.form.get("group"), 40)
    existing = {p["name"].casefold() for p in models.people()}
    added, skipped = [], []
    for part in re.split(r"[\n,;]+", request.form.get("names", "")):
        name = clean_line(part, 60)
        if not name:
            continue
        if name.casefold() in existing:
            skipped.append(name)
            continue
        if len(existing) >= MAX_PEOPLE:
            flash(f"Больше {MAX_PEOPLE} участников не поместится в одну книгу.", "error")
            break
        token = new_token()
        while models.by_token(token):
            token = new_token()
        db.execute(
            "INSERT INTO participants(name, grp, token, created_at) VALUES (?, ?, ?, ?)",
            (name, group, token, iso_now()),
        )
        existing.add(name.casefold())
        added.append(name)
    db.commit()
    if added:
        word = plural(len(added), "участник", "участника", "участников")
        flash(f"В книгу записано: {len(added)} {word}. Скопируйте ссылки и разошлите их.", "ok")
    if skipped:
        flash("Уже есть в списке: " + ", ".join(skipped) + ".", "info")
    if not added and not skipped:
        flash("Впишите хотя бы одно имя.", "error")
    return _back("people")


@bp.post("/participants/<int:pid>/edit")
@admin_required
def edit_participant(pid):
    p = models.by_id(pid) or abort(404)
    name = clean_line(request.form.get("name"), 60)
    group = clean_line(request.form.get("group"), 40) if "group" in request.form else p["grp"]
    if not name:
        flash("Имя не может быть пустым.", "error")
        return _back("people")
    if any(o["name"].casefold() == name.casefold() for o in models.people() if o["id"] != pid):
        flash(f"Имя «{name}» уже занято — добавьте фамилию или инициал.", "error")
        return _back("people")
    if models.is_drawn() and group != p["grp"]:
        group = p["grp"]
        flash("Группа учитывается только при жеребьёвке, поэтому после неё не меняется.", "info")
    db.execute("UPDATE participants SET name = ?, grp = ? WHERE id = ?", (name, group, pid))
    db.commit()
    flash(f"Сохранено: {name}.", "ok")
    return _back("people")


@bp.post("/participants/<int:pid>/delete")
@admin_required
def delete_participant(pid):
    p = models.by_id(pid) or abort(404)
    if models.is_drawn():
        flash("После жеребьёвки удалить человека нельзя — сначала отмените её.", "error")
        return _back("people")
    db.execute("DELETE FROM participants WHERE id = ?", (pid,))
    db.commit()
    flash(f"{p['name']} вычеркнут(а) из книги.", "ok")
    return _back("people")


@bp.post("/participants/<int:pid>/reset-pin")
@admin_required
def reset_pin(pid):
    p = models.by_id(pid) or abort(404)
    db.execute(
        "UPDATE participants SET pin_hash = NULL, pin_set_at = NULL, pin_resets = pin_resets + 1, "
        "session_ver = session_ver + 1, failed_pins = 0, locked_until = NULL WHERE id = ?",
        (pid,),
    )
    db.commit()
    flash(f"PIN для «{p['name']}» сброшен. Пришлите ссылку ещё раз — при входе появится новый PIN.", "ok")
    return _back("people")


# ---------------------------------------------------------------- исключения

@bp.post("/exclusions")
@admin_required
def add_exclusion():
    if models.is_drawn():
        flash("Исключения учитываются при жеребьёвке. Чтобы их поменять, отмените её.", "error")
        return _back("rules")
    try:
        a, b = int(request.form.get("a", 0)), int(request.form.get("b", 0))
    except ValueError:
        abort(400)
    if a == b:
        flash("Выберите двух разных людей.", "error")
        return _back("rules")
    pa, pb = models.by_id(a), models.by_id(b)
    if not pa or not pb:
        abort(404)
    db.execute("INSERT OR IGNORE INTO exclusions(a_id, b_id) VALUES (?, ?)", (min(a, b), max(a, b)))
    db.commit()
    flash(f"{pa['name']} и {pb['name']} не будут дарить друг другу.", "ok")
    return _back("rules")


@bp.post("/exclusions/delete")
@admin_required
def delete_exclusion():
    if models.is_drawn():
        flash("После жеребьёвки исключения не меняются.", "error")
        return _back("rules")
    try:
        a, b = int(request.form.get("a", 0)), int(request.form.get("b", 0))
    except ValueError:
        abort(400)
    db.execute("DELETE FROM exclusions WHERE a_id = ? AND b_id = ?", (min(a, b), max(a, b)))
    db.commit()
    return _back("rules")


# ---------------------------------------------------------------- настройки

@bp.post("/settings")
@admin_required
def save_settings():
    exchange_at = (request.form.get("exchange_at") or "").strip()
    if exchange_at and not parse_local(exchange_at):
        flash("Не получилось прочитать дату вручения.", "error")
        return _back("settings")
    values = {
        "event_name": clean_line(request.form.get("event_name"), 80) or "Новогодний обмен подарками",
        "exchange_at": exchange_at[:16],
        "budget": clean_line(request.form.get("budget"), 40),
        "place": clean_line(request.form.get("place"), 120),
        "note": clean_text(request.form.get("note"), 600),
    }
    for key, value in values.items():
        db.set_setting(key, value)
    db.commit()
    flash("Настройки праздника сохранены.", "ok")
    return _back("settings")


# ---------------------------------------------------------------- жеребьёвка

DRAW_KEYS = ("draw_at", "draw_count", "draw_cycles", "draw_mutual")


@bp.post("/draw")
@admin_required
def run_draw():
    people = models.people()
    names = {p["id"]: p["name"] for p in people}
    try:
        result = draw(list(names), models.forbidden_pairs(people))
    except DrawError as err:
        flash(err.human(names), "error")
        return _back("draw")

    con = db.get()
    con.execute("BEGIN IMMEDIATE")
    try:
        if models.is_drawn():
            con.rollback()
            flash("Конверты уже запечатаны.", "info")
            return _back("draw")
        con.execute("DELETE FROM messages")
        con.execute("UPDATE participants SET opened_at = NULL, seen_santa_at = NULL, seen_giftee_at = NULL")
        con.executemany(
            "INSERT INTO assignments(giver_id, sealed) VALUES (?, ?)",
            [(g, seal(f"{g}:{r}")) for g, r in result.items()],
        )
        db.set_setting("draw_at", iso_now())
        db.set_setting("draw_count", str(len(result)))
        db.set_setting("draw_cycles", str(cycle_count(result)))
        db.set_setting("draw_mutual", str(mutual_count(result)))
        con.commit()
    except Exception:
        con.rollback()
        raise

    n = len(result)
    flash(f"Готово! {n} {plural(n, 'конверт запечатан', 'конверта запечатаны', 'конвертов запечатаны')}. "
          "Кто кому дарит, не знает никто — даже вы.", "ok")
    return _back("draw")


@bp.post("/draw/cancel")
@admin_required
def cancel_draw():
    if not request.form.get("confirm"):
        flash("Поставьте галочку подтверждения — отмена сотрёт все пары и переписку.", "error")
        return _back("draw")
    con = db.get()
    con.execute("DELETE FROM messages")
    con.execute("DELETE FROM assignments")
    con.execute("UPDATE participants SET opened_at = NULL, seen_santa_at = NULL, seen_giftee_at = NULL")
    for key in DRAW_KEYS:
        db.del_setting(key)
    con.commit()
    flash("Жеребьёвка отменена. Список снова можно менять.", "ok")
    return _back("draw")
