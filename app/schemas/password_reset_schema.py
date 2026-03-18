"""Pydantic schemas for password reset flows."""

from pydantic import BaseModel, EmailStr, Field


class ForgotPasswordRequest(BaseModel):
    """Request body for initiating password reset."""

    email: EmailStr = Field(..., examples=["user@example.com"])


class ResetPasswordRequest(BaseModel):
    """Request body for completing password reset."""

    token: str = Field(..., examples=["reset-token"])
    new_password: str = Field(..., min_length=6, max_length=64, examples=["newSecret123"])

