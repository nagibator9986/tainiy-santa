import re
import sqlite3

import pytest

from santa import create_app


@pytest.fixture
def app(tmp_path):
    return create_app({"DATA_DIR": str(tmp_path), "TESTING": True, "ADMIN_PASSWORD": "north-pole"})


def csrf(client):
    client.get("/")
    with client.session_transaction() as s:
        return s["csrf"]


def post(client, url, data=None, **kw):
    data = dict(data or {})
    data["csrf"] = csrf(client)
    return client.post(url, data=data, **kw)


def admin(app):
    c = app.test_client()
    r = post(c, "/admin/login", {"password": "north-pole"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/admin/")
    return c


def tokens(app):
    con = sqlite3.connect(app.config["DATABASE"])
    rows = con.execute("SELECT name, token FROM participants").fetchall()
    con.close()
    return dict(rows)


def enter(app, token, pin="2468"):
    c = app.test_client()
    r = post(c, f"/p/{token}/claim", {"pin": pin, "pin2": pin})
    assert r.status_code == 302
    return c


def test_pages_render(app):
    c = app.test_client()
    assert c.get("/").status_code == 200
    assert c.get("/healthz").json == {"ok": True}
    assert c.get("/p/nope").status_code == 404
    assert c.get("/admin/").status_code == 302


def test_csrf_required(app):
    c = app.test_client()
    assert c.post("/admin/login", data={"password": "north-pole"}).status_code == 400


def test_wrong_admin_password(app):
    c = app.test_client()
    post(c, "/admin/login", {"password": "nope"})
    assert c.get("/admin/").status_code == 302


def test_full_flow_and_secrecy(app):
    a = admin(app)
    post(a, "/admin/participants", {"names": "Аня\nБорис, Вика\nГлеб\nДина", "group": ""})
    post(a, "/admin/participants", {"names": "аня"})  # дубликат
    t = tokens(app)
    assert sorted(t) == ["Аня", "Борис", "Вика", "Глеб", "Дина"]

    ids = {name: i for i, name in enumerate(sorted(t), 1)}
    con = sqlite3.connect(app.config["DATABASE"])
    pid = dict(con.execute("SELECT name, id FROM participants").fetchall())
    con.close()
    post(a, "/admin/exclusions", {"a": pid["Аня"], "b": pid["Борис"]})

    # письмо до жеребьёвки
    anya = enter(app, t["Аня"])
    post(anya, f"/p/{t['Аня']}/letter", {"wishes": "Книгу https://example.com/book", "dislikes": "Свечи", "about": "Размер M"})
    page = anya.get(f"/p/{t['Аня']}").get_data(as_text=True)
    assert "Книгу https://example.com/book" in page and "скоро" in page

    r = post(a, "/admin/draw")
    assert r.status_code == 302

    dash = a.get("/admin/").get_data(as_text=True)
    assert "Конверты запечатаны" in dash
    assert "Одна общая цепочка" in dash

    # в базе пары зашифрованы
    con = sqlite3.connect(app.config["DATABASE"])
    sealed = [row[0] for row in con.execute("SELECT sealed FROM assignments")]
    con.close()
    assert len(sealed) == 5
    assert all(not re.fullmatch(r"\d+:\d+", s) for s in sealed)

    # каждый видит ровно одного получателя, не себя, и Аня ≠ Борис
    givers = {}
    clients = {"Аня": anya}
    for name, token in t.items():
        c = clients.get(name) or enter(app, token)
        clients[name] = c
        html = c.get(f"/p/{token}").get_data(as_text=True)
        m = re.search(r'class="env-letter-name">([^<]+)<', html)
        assert m, name
        givers[name] = m.group(1)
    assert sorted(givers.values()) == sorted(t)
    assert all(g != r for g, r in givers.items())
    assert givers["Аня"] != "Борис" and givers["Борис"] != "Аня"

    # админка не раскрывает пары
    for giver, recipient in givers.items():
        assert f"{giver} → {recipient}" not in dash

    # вскрытие, отметка подарка, анонимная переписка
    santa_of_anya = next(g for g, r in givers.items() if r == "Аня")
    sc = clients[santa_of_anya]
    st = t[santa_of_anya]
    assert sc.post(f"/p/{st}/open", headers={"X-CSRF-Token": csrf(sc)}).json == {"ok": True}
    html = sc.get(f"/p/{st}").get_data(as_text=True)
    assert "Книгу" in html and 'href="https://example.com/book"' in html
    post(sc, f"/p/{st}/gift", {"ready": "1"})
    post(sc, f"/p/{st}/ask", {"text": "Какой размер варежек?"})

    html = anya.get(f"/p/{t['Аня']}").get_data(as_text=True)
    assert "Какой размер варежек?" in html
    assert santa_of_anya not in html.split('id="santa"')[1]
    post(anya, f"/p/{t['Аня']}/reply", {"text": "Восьмой"})
    html = sc.get(f"/p/{st}").get_data(as_text=True)
    assert "Восьмой" in html

    dash = a.get("/admin/").get_data(as_text=True)
    assert "Какой размер" not in dash and "Восьмой" not in dash

    # после жеребьёвки список закрыт
    post(a, "/admin/participants", {"names": "Ева"})
    assert "Ева" not in tokens(app)

    # отмена
    post(a, "/admin/draw/cancel", {"confirm": "1"})
    con = sqlite3.connect(app.config["DATABASE"])
    assert con.execute("SELECT COUNT(*) FROM assignments").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
    con.close()


def test_pin_protects_envelope(app):
    a = admin(app)
    post(a, "/admin/participants", {"names": "Аня, Борис, Вика"})
    t = tokens(app)
    enter(app, t["Аня"], "1357")

    stranger = app.test_client()
    html = stranger.get(f"/p/{t['Аня']}").get_data(as_text=True)
    assert "Введи свой PIN" in html
    assert stranger.post(f"/p/{t['Аня']}/open", headers={"X-CSRF-Token": csrf(stranger)}).status_code == 401
    for _ in range(5):
        post(stranger, f"/p/{t['Аня']}/login", {"pin": "0000"})
    post(stranger, f"/p/{t['Аня']}/login", {"pin": "1357"})
    assert "вход ненадолго закрыт" in stranger.get(f"/p/{t['Аня']}").get_data(as_text=True)

    # второй раз задать PIN нельзя
    post(stranger, f"/p/{t['Аня']}/claim", {"pin": "1111", "pin2": "1111"})
    assert "Введи свой PIN" in stranger.get(f"/p/{t['Аня']}").get_data(as_text=True)

    # сброс PIN организатором виден участнику и выкидывает старую сессию
    con = sqlite3.connect(app.config["DATABASE"])
    pid = con.execute("SELECT id FROM participants WHERE name = 'Аня'").fetchone()[0]
    con.close()
    post(a, f"/admin/participants/{pid}/reset-pin")
    html = app.test_client().get(f"/p/{t['Аня']}").get_data(as_text=True)
    assert "сбрасывал PIN этого конверта 1 раз" in html


def test_everyone_in_one_group_is_explained_and_fixable(app):
    """Частая ошибка: в «пару/семью» вписали название компании всем сразу."""
    a = admin(app)
    r = post(a, "/admin/participants", {"names": "Аня, Борис, Вика, Глеб", "group": "Rayband"}, follow_redirects=True)
    assert "уже 4 из 4" in r.get_data(as_text=True)
    dash = a.get("/admin/").get_data(as_text=True)
    assert "Так не сложится" in dash and "Снять пометку «Rayband»" in dash
    assert 'class="seal-btn"' not in dash

    r = post(a, "/admin/draw", follow_redirects=True)
    assert "дарить им некому" in r.get_data(as_text=True)
    assert sqlite3.connect(app.config["DATABASE"]).execute("SELECT COUNT(*) FROM assignments").fetchone()[0] == 0

    post(a, "/admin/groups/dissolve", {"group": "rayband"})
    dash = a.get("/admin/").get_data(as_text=True)
    assert "Так не сложится" not in dash and 'class="seal-btn"' in dash
    post(a, "/admin/draw")
    assert sqlite3.connect(app.config["DATABASE"]).execute("SELECT COUNT(*) FROM assignments").fetchone()[0] == 4


def test_family_of_two_is_fine_but_stuck_person_is_named(app):
    a = admin(app)
    post(a, "/admin/participants", {"names": "Аня, Борис", "group": "Ивановы"})
    post(a, "/admin/participants", {"names": "Вика, Глеб"})
    assert "Так не сложится" not in a.get("/admin/").get_data(as_text=True)
    con = sqlite3.connect(app.config["DATABASE"])
    pid = dict(con.execute("SELECT name, id FROM participants").fetchall())
    con.close()
    # Вика исключена со всеми — ей некому дарить
    for other in ("Аня", "Борис", "Глеб"):
        post(a, "/admin/exclusions", {"a": pid["Вика"], "b": pid[other]})
    r = post(a, "/admin/draw", follow_redirects=True)
    assert "Участнику «Вика» некому дарить" in r.get_data(as_text=True)


def test_setup_flow_without_env_password(tmp_path):
    app = create_app({"DATA_DIR": str(tmp_path), "TESTING": True, "ADMIN_PASSWORD": None})
    c = app.test_client()
    assert c.get("/admin/login").headers["Location"].endswith("/admin/setup")
    post(c, "/admin/setup", {"password": "snowflake9", "password2": "snowflake9"})
    assert c.get("/admin/").status_code == 200
    assert app.test_client().get("/admin/setup").status_code == 302
