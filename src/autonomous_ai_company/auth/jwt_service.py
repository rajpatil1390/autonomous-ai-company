"""Create and validate signed JWT access tokens from runtime configuration."""

from datetime import datetime, timedelta, timezone
from typing import cast

from jose import JWTError, jwt
from pydantic import JsonValue

from autonomous_ai_company.config import Settings
from autonomous_ai_company.exceptions import ConfigurationError


def _secret_key(settings: Settings) -> str:
    """Return the configured secret or fail before issuing insecure tokens."""

    if settings.jwt_secret_key is None:
        raise ConfigurationError("JWT_SECRET_KEY is required for authentication")
    return settings.jwt_secret_key.get_secret_value()


def create_access_token(
    subject: str,
    settings: Settings,
    *,
    expires_delta: timedelta | None = None,
    now: datetime | None = None,
) -> str:
    """Create a signed access token with explicit issue and expiration claims."""

    if not subject:
        raise ValueError("token subject must not be empty")
    issued_at = now or datetime.now(timezone.utc)
    lifetime = expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    claims = {
        "sub": subject,
        "iat": issued_at,
        "exp": issued_at + lifetime,
        "type": "access",
    }
    return jwt.encode(
        claims,
        _secret_key(settings),
        algorithm=settings.jwt_algorithm,
    )


def decode_token(token: str, settings: Settings) -> dict[str, JsonValue]:
    """Decode and validate signature, expiration, and configured algorithm."""

    decoded = jwt.decode(
        token,
        _secret_key(settings),
        algorithms=[settings.jwt_algorithm],
        options={"require_exp": True, "require_iat": True, "require_sub": True},
    )
    return cast(dict[str, JsonValue], decoded)


def verify_access_token(token: str, settings: Settings) -> str:
    """Return the subject only for a structurally valid access token."""

    claims = decode_token(token, settings)
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise JWTError("Token subject is invalid")
    if claims.get("type") != "access":
        raise JWTError("Token type is invalid")
    return subject
