"""Authentication routes: register, login, me."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.dependencies.role_checker import get_current_user, get_current_user_optional
from app.models.user_model import User
from app.schemas.user_schema import LoginData, LoginResponse, MessageResponse, RoleEnum, UserRegister, UserLogin, UserResponse
from app.schemas.password_reset_schema import ForgotPasswordRequest, ResetPasswordRequest
from app.services.auth_service import (
    create_user,
    authenticate_user_with_reason,
    generate_token,
    get_user_by_username,
)
from app.services.login_activity_service import log_login_attempt
from app.services.password_reset_service import request_password_reset, reset_password_with_token

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    responses={
        201: {
            "description": "User created successfully",
            "content": {
                "application/json": {
                    "example": {
                        "id": 1,
                        "username": "johndoe",
                        "email": "john@example.com",
                        "role": "user",
                        "created_at": "2025-03-16T12:00:00Z",
                    }
                }
            },
        },
        400: {"description": "Username or email already exists"},
        403: {"description": "Only admin can create another admin"},
    },
)
def register(
    data: UserRegister,
    db: Annotated[Session, Depends(get_db)],
    current_user: User | None = Depends(get_current_user_optional),
):
    """
    Create a new user. Default role is **user**.
    Only an **admin** can create a user with role **admin** (send role=admin in body when authenticated as admin).
    """
    if get_user_by_username(db, data.username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    is_admin = current_user is not None and current_user.role.value == "admin"
    try:
        user = create_user(db, data, created_by_admin=is_admin)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    return UserResponse.model_validate_user(user)


@router.post(
    "/login",
    response_model=LoginResponse,
    response_model_by_alias=True,
    summary="Login and get JWT",
    responses={
        200: {
            "description": "Success",
            "content": {
                "application/json": {
                    "example": {
                        "statusCode": 200,
                        "message": "User logged in successfully",
                        "data": {
                            "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                            "userId": 1,
                            "role": "user",
                        },
                    }
                }
            },
        },
        401: {"description": "Invalid email or password"},
    },
)
def login(
    data: UserLogin,
    db: Annotated[Session, Depends(get_db)],
    request: Request,
):
    """Verify email (or username) and password; returns a JWT access token."""
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    user, failure_reason = authenticate_user_with_reason(db, data.email, data.password)
    success = user is not None
    log_login_attempt(
        db=db,
        identifier=data.email,
        email=(user.email if user else data.email),
        success=success,
        user_id=(user.id if user else None),
        ip_address=ip_address,
        user_agent=user_agent,
        failure_reason=failure_reason,
    )
    db.commit()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    token = generate_token(user)
    return LoginResponse(
        status_code=200,
        message="User logged in successfully",
        data=LoginData(
            access_token=token,
            user_id=user.id,
            role=RoleEnum(user.role.value),
        ),
    )


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    summary="Initiate password reset (email-agnostic).",
)
def forgot_password(
    data: ForgotPasswordRequest,
    db: Annotated[Session, Depends(get_db)],
) -> MessageResponse:
    """
    Create a password reset token if the account exists.

    Response is identical regardless of whether the email is registered.
    """
    request_password_reset(db, data.email)
    return MessageResponse(
        message="If the account exists, a password reset link will be sent."
    )


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    summary="Reset password using a reset token.",
)
def reset_password(
    data: ResetPasswordRequest,
    db: Annotated[Session, Depends(get_db)],
) -> MessageResponse:
    """Validate reset token and set a new password."""
    try:
        reset_password_with_token(db, token=data.token, new_password=data.new_password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    return MessageResponse(message="Password has been reset successfully.")


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user",
    responses={
        200: {
            "description": "Current user details",
            "content": {
                "application/json": {
                    "example": {
                        "id": 1,
                        "username": "johndoe",
                        "email": "john@example.com",
                        "role": "user",
                        "created_at": "2025-03-16T12:00:00Z",
                    }
                }
            },
        },
        401: {"description": "Not authenticated"},
    },
)
def me(current_user: Annotated[User, Depends(get_current_user)]):
    """Return the currently logged-in user (requires valid JWT)."""
    return UserResponse.model_validate_user(current_user)
