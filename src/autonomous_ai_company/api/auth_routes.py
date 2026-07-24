"""Expose local login while keeping credential policy outside workflow routes."""

from secrets import compare_digest
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from autonomous_ai_company.auth.jwt_service import create_access_token
from autonomous_ai_company.auth.models import LoginRequest, TokenResponse
from autonomous_ai_company.auth.password import verify_password
from autonomous_ai_company.config import Settings, get_settings


_DEMO_USERNAME = "admin"
_DEMO_PASSWORD_HASH = "$2b$12$8QkKYh1EpEePjj8AB6o9peX1HSKTrYi55trpPxdHm3K0.eIRfRJyS"


def _login_exception() -> HTTPException:
    """Return one response for unknown users and invalid passwords."""

    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password",
        headers={"WWW-Authenticate": "Bearer"},
    )


def create_auth_router() -> APIRouter:
    """Create isolated authentication routes with injectable configuration."""

    router = APIRouter(prefix="/auth", tags=["authentication"])

    @router.post("/login", response_model=TokenResponse)
    async def login(
        credentials: LoginRequest,
        settings: Annotated[Settings, Depends(get_settings)],
    ) -> TokenResponse:
        """Issue an access token only after bcrypt credential verification."""

        username_matches = compare_digest(
            credentials.username,
            _DEMO_USERNAME,
        )
        password_matches = verify_password(
            credentials.password.get_secret_value(),
            _DEMO_PASSWORD_HASH,
        )
        if not username_matches or not password_matches:
            raise _login_exception()
        return TokenResponse(
            access_token=create_access_token(
                credentials.username,
                settings,
            )
        )

    return router
