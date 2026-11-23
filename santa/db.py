"""SQLite: соединение на запрос, схема и настройки события."""
import fcntl
import sqlite3
from datetime import date

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS participants (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT    NOT NULL,
    grp            TEXT    NOT NULL DEFAULT '',
    token          TEXT    NOT NULL UNIQUE,
    pin_hash       TEXT,
    pin_set_at     TEXT,
    pin_resets     INTEGER NOT NULL DEFAULT 0,
    session_ver    INTEGER NOT NULL DEFAULT 0,
    failed_pins    INTEGER NOT NULL DEFAULT 0,
    locked_until   TEXT,
    wishes         TEXT    NOT NULL DEFAULT '',
    dislikes       TEXT    NOT NULL DEFAULT '',
    about          TEXT    NOT NULL DEFAULT '',
    letter_at      TEXT,
    opened_at      TEXT,
    seen_santa_at  TEXT,
    seen_giftee_at TEXT,
    created_at     TEXT    NOT NULL
);

-- «Не дарят друг другу». Храним одну строку на пару: a_id < b_id.
CREATE TABLE IF NOT EXISTS exclusions (
    a_id INTEGER NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
    b_id INTEGER NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
    PRIMARY KEY (a_id, b_id),
    CHECK (a_id < b_id)
);

-- Получатель зашифрован: в базе не видно, кто кому дарит.
CREATE TABLE IF NOT EXISTS assignments (
    giver_id   INTEGER PRIMARY KEY REFERENCES participants(id) ON DELETE CASCADE,
    sealed     TEXT    NOT NULL,
    gift_ready INTEGER NOT NULL DEFAULT 0
);

-- Анонимная переписка дарителя (giver_id) и его подопечного.
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    giver_id   INTEGER NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
    from_santa INTEGER NOT NULL,
    sealed     TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_messages_giver ON messages(giver_id, id);
"""


def default_settings() -> dict:
    today = date.today()
    year = today.year if (today.month, today.day) <= (12, 27) else today.year + 1
    return {
        "event_name": "Новогодний обмен подарками",
        "exchange_at": f"{year}-12-27T18:00",
        "budget": "до 10 000 ₸",
        "place": "",
        "note": "",
    }


def _connect(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def get() -> sqlite3.Connection:
    if "db" not in g:
        g.db = _connect(current_app.config["DATABASE"])
    return g.db


def _close(_exc=None):
    con = g.pop("db", None)
    if con is not None:
        con.close()


def init_app(app):
    path = app.config["DATABASE"]
    # Несколько воркеров стартуют одновременно: схему создаёт кто-то один.
    with open(path + ".init-lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        con = _connect(path)
        try:
            con.execute("PRAGMA journal_mode = WAL")
            con.executescript(SCHEMA)
            for key, value in default_settings().items():
                con.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value))
            con.commit()
        finally:
            con.close()
            fcntl.flock(lock, fcntl.LOCK_UN)
    app.teardown_appcontext(_close)


def query(sql: str, args=(), one: bool = False):
    cur = get().execute(sql, args)
    rows = cur.fetchall()
    cur.close()
    if one:
        return rows[0] if rows else None
    return rows


def execute(sql: str, args=()) -> sqlite3.Cursor:
    return get().execute(sql, args)


def commit():
    get().commit()


def settings() -> dict:
    return {row["key"]: row["value"] for row in query("SELECT key, value FROM settings")}


def setting(key: str, default=None):
    row = query("SELECT value FROM settings WHERE key = ?", (key,), one=True)
    return row["value"] if row else default


def set_setting(key: str, value: str):
    execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def del_setting(key: str):
    execute("DELETE FROM settings WHERE key = ?", (key,))
