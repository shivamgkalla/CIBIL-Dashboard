"""Pydantic schemas for password reset flows."""

from pydantic import BaseModel, EmailStr, Field


class ForgotPasswordRequest(BaseModel):
    """Request body for initiating password reset."""

    email: EmailStr = Field(..., examples=["user@example.com"])


class ForgotPasswordResponse(BaseModel):
    """Response for forgot-password. Includes demo_reset_link only in dev mode."""

    message: str
    demo_reset_link: str | None = Field(
        default=None,
        description="Reset link returned only in demo mode (ENV=dev). "
        "Will be None in production when email delivery is configured.",
    )


class ResetPasswordRequest(BaseModel):
    """Request body for completing password reset."""

    token: str = Field(..., examples=["reset-token"])
    new_password: str = Field(..., min_length=6, max_length=64, examples=["newSecret123"])

