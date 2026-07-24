"""Provide one-way bcrypt password hashing and constant-time verification."""

from passlib.context import CryptContext
from passlib.exc import UnknownHashError


_PASSWORD_CONTEXT = CryptContext(schemes=["bcrypt"], deprecated="auto")
_BCRYPT_MAX_BYTES = 72


def _validate_password(password: str) -> None:
    """Reject values bcrypt cannot safely represent without truncation."""

    if not password:
        raise ValueError("password must not be empty")
    if len(password.encode("utf-8")) > _BCRYPT_MAX_BYTES:
        raise ValueError("password exceeds bcrypt's 72-byte limit")


def hash_password(password: str) -> str:
    """Return a salted bcrypt hash so plaintext is never stored."""

    _validate_password(password)
    return _PASSWORD_CONTEXT.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify through bcrypt without directly comparing plaintext values."""

    try:
        _validate_password(password)
        return _PASSWORD_CONTEXT.verify(password, password_hash)
    except (TypeError, ValueError, UnknownHashError):
        return False
