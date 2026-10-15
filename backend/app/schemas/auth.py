from uuid import UUID

from pydantic import BaseModel, ConfigDict


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    password: str


class PreAuthChallengeResponse(BaseModel):
    csrf_token: str


class AuthenticatedUserResponse(BaseModel):
    id: UUID
    email: str


class SessionResponse(BaseModel):
    user: AuthenticatedUserResponse
    csrf_token: str
