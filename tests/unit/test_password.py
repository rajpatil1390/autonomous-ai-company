"""Unit tests for one-way bcrypt password handling."""

import pytest

from autonomous_ai_company.auth.password import hash_password, verify_password


def test_hash_password_creates_salted_non_plaintext_bcrypt_hashes() -> None:
    """Equal plaintext values should produce distinct irreversible hashes."""

    first = hash_password("admin123")
    second = hash_password("admin123")

    assert first != "admin123"
    assert second != "admin123"
    assert first != second
    assert first.startswith("$2b$")
    assert verify_password("admin123", first) is True
    assert verify_password("wrong-password", first) is False


@pytest.mark.parametrize("password", ["", "x" * 73])
def test_hash_password_rejects_unsafe_values(password: str) -> None:
    """Empty and bcrypt-truncated values must never be accepted for storage."""

    with pytest.raises(ValueError):
        hash_password(password)


@pytest.mark.parametrize(
    ("password", "password_hash"),
    [
        ("", "$2b$12$invalid"),
        ("admin123", "not-a-supported-hash"),
        ("é" * 37, "$2b$12$invalid"),
    ],
)
def test_verify_password_returns_false_for_invalid_inputs(
    password: str,
    password_hash: str,
) -> None:
    """Malformed, empty, or overlong inputs should fail closed."""

    assert verify_password(password, password_hash) is False
