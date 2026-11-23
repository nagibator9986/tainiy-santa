"""Участники, пары и переписка поверх SQLite."""
from flask import current_app, url_for

from . import db
from .crypto import unseal


def people():
    rows = db.query("SELECT * FROM participants")
    return sorted(rows, key=lambda r: (r["name"].casefold(), r["id"]))


def by_token(token: str):
    return db.query("SELECT * FROM participants WHERE token = ?", (token,), one=True)


def by_id(pid: int):
    return db.query("SELECT * FROM participants WHERE id = ?", (pid,), one=True)


def link_for(p) -> str:
    base = current_app.config.get("PUBLIC_URL")
    if base:
        return base + url_for("public.participant", token=p["token"])
    return url_for("public.participant", token=p["token"], _external=True)


def letter_filled(p) -> bool:
    return any((p[k] or "").strip() for k in ("wishes", "dislikes", "about"))


def is_drawn() -> bool:
    return db.query("SELECT 1 FROM assignments LIMIT 1", one=True) is not None


def _open_pair(row):
    """Расшифровать строку assignments → id получателя или None."""
    raw = unseal(row["sealed"]) or ""
    giver, _, recipient = raw.partition(":")
    if giver != str(row["giver_id"]) or not recipient.isdigit():
        return None
    return int(recipient)


def giftee_of(pid: int):
    """(получатель, подарок готов, конверт повреждён)."""
    row = db.query("SELECT giver_id, sealed, gift_ready FROM assignments WHERE giver_id = ?", (pid,), one=True)
    if not row:
        return None, False, False
    rid = _open_pair(row)
    giftee = by_id(rid) if rid else None
    return giftee, bool(row["gift_ready"]), giftee is None


def santa_of(pid: int):
    """id того, кто дарит участнику. Только для переписки — наружу не отдаётся."""
    for row in db.query("SELECT giver_id, sealed FROM assignments"):
        if _open_pair(row) == pid:
            return row["giver_id"]
    return None


def thread(giver_id: int) -> list[dict]:
    rows = db.query("SELECT from_santa, sealed, created_at FROM messages WHERE giver_id = ? ORDER BY id", (giver_id,))
    return [
        {"from_santa": bool(r["from_santa"]), "text": unseal(r["sealed"]) or "…", "at": r["created_at"]}
        for r in rows
    ]


def thread_size(giver_id: int) -> int:
    return db.query("SELECT COUNT(*) AS c FROM messages WHERE giver_id = ?", (giver_id,), one=True)["c"]


def forbidden_pairs(rows) -> set:
    """Исключения и группы → направленные запрещённые пары."""
    forbidden = set()
    for e in db.query("SELECT a_id, b_id FROM exclusions"):
        forbidden.add((e["a_id"], e["b_id"]))
        forbidden.add((e["b_id"], e["a_id"]))
    groups: dict[str, list[int]] = {}
    for p in rows:
        key = (p["grp"] or "").strip().casefold()
        if key:
            groups.setdefault(key, []).append(p["id"])
    for members in groups.values():
        for a in members:
            for b in members:
                if a != b:
                    forbidden.add((a, b))
    return forbidden
