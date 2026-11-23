"""Тайный Санта — Flask + SQLite."""
import os
import secrets
from datetime import timedelta
from pathlib import Path

from flask import Flask, render_template
from werkzeug.middleware.proxy_fix import ProxyFix

from . import db
from .helpers import register_helpers
from .security import register_security


def _load_secret(data_dir: Path) -> str:
    """SECRET_KEY из окружения или из файла рядом с базой (создаётся один раз).

    Ключ шифрует пары, поэтому живёт вместе с базой: потеряете ключ —
    конверты не откроются, понадобится новая жеребьёвка.
    """
    env = os.environ.get("SECRET_KEY", "").strip()
    if env:
        return env
    path = data_dir / "secret_key"
    if not path.exists():
        tmp = data_dir / f".secret_key.{os.getpid()}.tmp"
        tmp.write_text(secrets.token_hex(32))
        try:
            os.link(tmp, path)  # атомарно: если два процесса стартуют разом, победит один
        except FileExistsError:
            pass
        finally:
            tmp.unlink(missing_ok=True)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return path.read_text().strip()


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    config = config or {}
    data_dir = Path(config.get("DATA_DIR") or os.environ.get("DATA_DIR") or Path(app.root_path).parent / "instance")
    data_dir.mkdir(parents=True, exist_ok=True)

    app.config.update(
        DATA_DIR=str(data_dir),
        DATABASE=str(data_dir / "santa.sqlite3"),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", "").strip() or None,
        TIMEZONE=os.environ.get("APP_TIMEZONE", "Asia/Almaty"),
        PUBLIC_URL=os.environ.get("PUBLIC_URL", "").rstrip("/") or None,
        SESSION_COOKIE_NAME="santa",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(days=60),
        MAX_CONTENT_LENGTH=256 * 1024,
    )
    app.config.update({k: v for k, v in config.items() if k != "DATA_DIR"})
    app.secret_key = _load_secret(data_dir)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    register_helpers(app)
    register_security(app)

    from .admin import bp as admin_bp
    from .public import bp as public_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp)

    @app.errorhandler(404)
    def not_found(_err):
        return render_template("errors/404.html"), 404

    @app.get("/healthz")
    def healthz():
        db.query("SELECT 1")
        return {"ok": True}

    return app
