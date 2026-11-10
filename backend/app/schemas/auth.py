from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    password: str


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str
    new_password: str
    confirm_new_password: str


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254)


class PasswordResetConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=30, max_length=128)
    new_password: str
    confirm_new_password: str


class PasswordResetRequestResponse(BaseModel):
    message: str


class PreAuthChallengeResponse(BaseModel):
    csrf_token: str


class AuthenticatedUserResponse(BaseModel):
    id: UUID
    email: str


class SessionResponse(BaseModel):
    user: AuthenticatedUserResponse
    csrf_token: str
