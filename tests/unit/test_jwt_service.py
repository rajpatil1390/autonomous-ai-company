"""Unit tests for configuration-backed JWT access tokens."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from jose import ExpiredSignatureError, JWTError, jwt

from autonomous_ai_company.auth.jwt_service import (
    create_access_token,
    decode_token,
    verify_access_token,
)
from autonomous_ai_company.config import Settings
from autonomous_ai_company.exceptions import ConfigurationError


JWT_SECRET = "test-signing-secret-that-is-at-least-thirty-two-bytes"


def jwt_settings(
    *,
    secret: str | None = JWT_SECRET,
    algorithm: str = "HS256",
    expire_minutes: int = 15,
) -> Settings:
    """Return complete application settings for isolated token tests."""

    values: dict[str, object] = {
        "ANTHROPIC_API_KEY": "test-api-key",
        "MODEL_NAME": "test-model",
        "TEMPERATURE": 0.0,
        "MAX_TOKENS": 100,
        "LOG_LEVEL": "INFO",
        "JWT_ALGORITHM": algorithm,
        "ACCESS_TOKEN_EXPIRE_MINUTES": expire_minutes,
        "_env_file": None,
    }
    if secret is not None:
        values["JWT_SECRET_KEY"] = secret
    return Settings(**values)


def test_create_decode_and_verify_access_token() -> None:
    """A configured token should preserve subject, type, and exact lifetime."""

    settings = jwt_settings()
    now = datetime.now(timezone.utc)

    token = create_access_token(
        "admin",
        settings,
        expires_delta=timedelta(minutes=5),
        now=now,
    )
    claims = decode_token(token, settings)

    assert claims["sub"] == "admin"
    assert claims["type"] == "access"
    assert int(claims["exp"]) - int(claims["iat"]) == 300
    assert verify_access_token(token, settings) == "admin"


def test_default_expiration_and_current_time_are_supported() -> None:
    """Omitted overrides should use configured lifetime and the UTC clock."""

    settings = jwt_settings(expire_minutes=2)

    token = create_access_token("admin", settings)
    claims = decode_token(token, settings)

    assert int(claims["exp"]) - int(claims["iat"]) == 120


def test_create_access_token_rejects_empty_subject() -> None:
    """Identity-less tokens must never be issued."""

    with pytest.raises(ValueError, match="subject"):
        create_access_token("", jwt_settings())


def test_missing_signing_secret_fails_closed() -> None:
    """Token operations must not substitute a hardcoded signing secret."""

    settings = jwt_settings(secret=None)

    with pytest.raises(ConfigurationError, match="JWT_SECRET_KEY"):
        create_access_token("admin", settings)
    with pytest.raises(ConfigurationError, match="JWT_SECRET_KEY"):
        decode_token("irrelevant", settings)


def test_expired_token_is_rejected() -> None:
    """An access token past its expiration must fail verification."""

    token = create_access_token(
        "admin",
        jwt_settings(),
        expires_delta=timedelta(seconds=-1),
    )

    with pytest.raises(ExpiredSignatureError):
        verify_access_token(token, jwt_settings())


def test_malformed_and_invalid_signature_tokens_are_rejected() -> None:
    """Parser failures and tokens signed by another secret must fail closed."""

    settings = jwt_settings()
    foreign = jwt_settings(
        secret="different-signing-secret-that-is-at-least-thirty-two-bytes"
    )
    foreign_token = create_access_token("admin", foreign)

    with pytest.raises(JWTError):
        decode_token("not-a-jwt", settings)
    with pytest.raises(JWTError):
        decode_token(foreign_token, settings)


def test_verify_rejects_invalid_subject_and_non_access_token() -> None:
    """Only nonempty subjects carried by access tokens are accepted."""

    settings = jwt_settings()
    with patch(
        "autonomous_ai_company.auth.jwt_service.decode_token",
        return_value={"sub": 123, "type": "access"},
    ):
        with pytest.raises(JWTError, match="subject"):
            verify_access_token("token", settings)

    now = datetime.now(timezone.utc)
    refresh_token = jwt.encode(
        {
            "sub": "admin",
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "type": "refresh",
        },
        JWT_SECRET,
        algorithm="HS256",
    )
    with pytest.raises(JWTError, match="type"):
        verify_access_token(refresh_token, settings)
