"""Define strict transport and identity models for local JWT authentication."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class AuthModel(BaseModel):
    """Apply strict validation and reject undeclared authentication fields."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class LoginRequest(AuthModel):
    """Carry transient credentials without exposing password representations."""

    username: str = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=72)


class TokenResponse(AuthModel):
    """Return a standard bearer access token without internal JWT claims."""

    access_token: str = Field(min_length=1)
    token_type: Literal["bearer"] = "bearer"


class AuthenticatedUser(AuthModel):
    """Represent the validated identity available to protected HTTP routes."""

    username: str = Field(min_length=1, max_length=128)
