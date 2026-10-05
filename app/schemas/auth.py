"""Authentication request/response schemas."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class LoginForm(BaseModel):
    identity: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class SignupForm(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=1024)
    name: str | None = Field(default=None, max_length=120)


class PasswordResetRequestForm(BaseModel):
    email: EmailStr


class PasswordResetConfirmForm(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    password: str = Field(min_length=8, max_length=1024)
    password_confirm: str = Field(min_length=8, max_length=1024)


class UserOut(BaseModel):
    """Public representation of the authenticated user."""

    id: str
    email: str | None
    name: str | None
    verified: bool
