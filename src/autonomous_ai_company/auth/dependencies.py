"""Terminate bearer-token authentication at the FastAPI dependency boundary."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from autonomous_ai_company.auth.jwt_service import verify_access_token
from autonomous_ai_company.auth.models import AuthenticatedUser
from autonomous_ai_company.config import Settings, get_settings
from autonomous_ai_company.exceptions import ConfigurationError


_BEARER_SCHEME = HTTPBearer()


def _credentials_exception() -> HTTPException:
    """Return one non-revealing challenge for every credential failure."""

    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_BEARER_SCHEME)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthenticatedUser:
    """Validate a bearer token and expose only its authenticated identity."""

    try:
        username = verify_access_token(credentials.credentials, settings)
    except (JWTError, ConfigurationError) as error:
        raise _credentials_exception() from error
    return AuthenticatedUser(username=username)
