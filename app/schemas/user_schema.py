"""Pydantic schemas for user and auth request/response validation."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, EmailStr, Field


class RoleEnum(str, Enum):
    """Role choices for API."""

    ADMIN = "admin"
    USER = "user"


# ----- Request schemas -----


class UserCreateRequest(BaseModel):
    """Admin-only schema to create a new user."""

    username: str = Field(..., min_length=3, max_length=50, examples=["johndoe"])
    email: EmailStr = Field(..., examples=["john@example.com"])
    password: str = Field(..., min_length=6, max_length=64, examples=["secret123"])
    role: RoleEnum = Field(default=RoleEnum.USER, description="User role (admin/user).")


class UserUpdateRequest(BaseModel):
    """Admin-only schema to update user details (partial update)."""

    username: str | None = Field(default=None, min_length=3, max_length=50)
    email: EmailStr | None = Field(default=None)
    password: str | None = Field(default=None, min_length=6, max_length=64)
    role: RoleEnum | None = Field(default=None, description="User role (admin/user).")


class UserRegister(BaseModel):
    """Schema for user registration."""

    username: str = Field(..., min_length=3, max_length=50, examples=["johndoe"])
    email: EmailStr = Field(..., examples=["john@example.com"])
    password: str = Field(..., min_length=6, max_length=64, examples=["secret123"])
    role: RoleEnum = Field(default=RoleEnum.USER, description="Only admin can set role=admin")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "username": "johndoe",
                    "email": "john@example.com",
                    "password": "secret123",
                    "role": "user",
                }
            ]
        }
    }


class UserLogin(BaseModel):
    """Schema for login (email + password, with username fallback)."""

    email: EmailStr = Field(..., examples=["john@example.com"])
    password: str = Field(..., examples=["secret123"])

    model_config = {
        "json_schema_extra": {
            "examples": [{"email": "john@example.com", "password": "secret123"}]
        }
    }


# ----- Response schemas -----


class UserResponse(BaseModel):
    """Public user data in responses."""

    id: int
    username: str
    email: str
    role: RoleEnum
    created_at: datetime
    last_login: datetime | None = None

    model_config = {"from_attributes": True}

    @classmethod
    def model_validate_user(cls, user) -> "UserResponse":
        """Build from ORM user (handles UserRole -> RoleEnum)."""
        return cls(
            id=user.id,
            username=user.username,
            email=user.email,
            role=RoleEnum(user.role.value),
            created_at=user.created_at,
            last_login=user.last_login,
        )


class LoginData(BaseModel):
    """Inner data payload for login response."""

    access_token: str
    user_id: int = Field(serialization_alias="userId")
    role: RoleEnum


class LoginResponse(BaseModel):
    """Wrapped login response with statusCode, message, and data."""

    status_code: int = Field(serialization_alias="statusCode")
    message: str
    data: LoginData


class MessageResponse(BaseModel):
    """Generic message response for dashboards etc."""

    message: str

    model_config = {
        "json_schema_extra": {
            "examples": [{"message": "Welcome to the admin dashboard."}]
        }
    }
