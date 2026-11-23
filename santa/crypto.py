"""Запечатывание пар и переписки.

Ключ выводится из SECRET_KEY приложения. Открыв файл базы, пары не
прочитать глазами — только через само приложение, и то лишь участнику
в его собственном конверте.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


def _fernet() -> Fernet:
    digest = hashlib.sha256(b"santa-seal:" + current_app.secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def seal(text: str) -> str:
    return _fernet().encrypt(text.encode()).decode()


def unseal(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None
