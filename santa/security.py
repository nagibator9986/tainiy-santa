"""CSRF-токен в сессии и заголовки безопасности."""
import hmac
import secrets

from flask import render_template, request, session


def csrf_token() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    return session["csrf"]


def register_security(app):
    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def check_csrf():
        if request.method != "POST":
            return None
        sent = request.form.get("csrf") or request.headers.get("X-CSRF-Token") or ""
        expected = session.get("csrf", "")
        if not expected or not hmac.compare_digest(sent, expected):
            return render_template("errors/stale.html"), 400
        return None

    @app.after_request
    def headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if request.path.startswith(("/p/", "/admin")):
            resp.headers["Cache-Control"] = "no-store"
        return resp
