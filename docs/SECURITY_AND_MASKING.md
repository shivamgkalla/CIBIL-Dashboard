# Security and Masking

## Overview

Security in this system spans four areas:
1. **Authentication** — JWT-based with bcrypt password hashing
2. **Authorization** — Role-based access control (RBAC) with admin/user roles
3. **Data masking** — Sensitive identity fields masked in all API responses
4. **Audit logging** — Login attempts and customer views tracked

---

## Authentication

### Password Hashing

**File**: `app/core/security.py`

Passwords are hashed using **bcrypt** via passlib's `CryptContext`:

```python
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
```

#### bcrypt 72-byte Limit Handling

bcrypt has a hard limit of 72 bytes for password input. The system handles this proactively via `_truncate_for_bcrypt()`:

```python
def _truncate_for_bcrypt(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) <= 72:
        return password
    trimmed = raw[:72].decode("utf-8", errors="ignore")
    return trimmed
```

This truncates at a byte boundary and uses `errors="ignore"` to safely handle split multi-byte UTF-8 characters. Both `hash_password()` and `verify_password()` apply this truncation.

### JWT Tokens

**File**: `app/core/security.py`

Tokens are created using `python-jose` with HS256 signing:

```python
payload = {
    "sub": str(user_id),
    "user_id": user_id,
    "username": username,
    "role": role,
    "exp": expire,
    "iat": now.timestamp(),
    "last_activity": now.timestamp(),
}
```

Key fields:
- `sub` / `user_id` — User identifier (duplicated for compatibility)
- `role` — Used for RBAC checks
- `exp` — Token expiration (30 minutes from creation/refresh)
- `last_activity` — Timestamp of last authenticated request (for inactivity detection)

### Sliding-Window Token Refresh

**File**: `app/dependencies/role_checker.py`

Every authenticated request triggers a token refresh:

1. The current token's `last_activity` timestamp is checked
2. If more than 1800 seconds (30 minutes) have passed since `last_activity`, the session is expired with `401 Session expired due to inactivity`
3. If still active, a **new token** is generated with:
   - Fresh `exp` (30 minutes from now)
   - Updated `last_activity` (now)
4. The new token is returned in the `X-New-Token` response header

```python
new_token = create_access_token(
    subject=user_id,
    username=str(payload.get("username") or ""),
    role=str(payload.get("role") or ""),
    expires_delta=timedelta(minutes=30),
)
response.headers["X-New-Token"] = new_token
```

**Trade-off**: This means the server generates a new JWT on every authenticated request. The cost is minimal (JWT signing is fast), and the benefit is seamless session extension without explicit refresh endpoints.

**Failure safety**: If the refresh fails (e.g., due to an encoding error), the exception is caught silently and the original request proceeds normally. The refresh mechanism never breaks endpoint functionality.

---

## Authorization (RBAC)

**File**: `app/dependencies/role_checker.py`

### RoleChecker Class

```python
class RoleChecker:
    def __init__(self, allowed_roles: list[UserRole]):
        self.allowed_roles = allowed_roles

    def __call__(self, user=Depends(get_current_user)):
        if user.role not in self.allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
```

### Pre-built Instances

```python
admin_only = RoleChecker([UserRole.ADMIN])
admin_or_user = RoleChecker([UserRole.ADMIN, UserRole.USER])
```

### Dependency Chain

```
HTTP Request
    │
    ▼
get_current_user_id(credentials, response)
  ├── Extract Bearer token from Authorization header
  ├── Decode JWT via decode_access_token()
  ├── Check inactivity timeout (1800s)
  ├── Issue refreshed token in X-New-Token header
  └── Return user_id (int)
    │
    ▼
get_current_user(user_id, db)
  ├── Load User from database by ID
  └── Return User ORM object (or 401 if not found)
    │
    ▼
RoleChecker.__call__(user)
  ├── Check user.role against allowed_roles
  └── Return user (or 403 if role mismatch)
```

### Optional Authentication

`get_current_user_optional()` is used for the registration endpoint where an admin can optionally be authenticated to create another admin:

```python
def get_current_user_optional(credentials, db):
    if not credentials or not credentials.credentials:
        return None   # No token → anonymous, no error
    # ... attempt decode, return user or None
```

### Endpoint Protection Summary

| Endpoint | Auth Required | Role Required |
|----------|--------------|---------------|
| `POST /auth/register` | Optional | Admin (to create admin) |
| `POST /auth/login` | No | — |
| `POST /auth/forgot-password` | No | — |
| `POST /auth/reset-password` | No | — |
| `GET /auth/me` | Yes | Any |
| `GET /admin/*` | Yes | Admin |
| `POST /upload/files` | Yes | Admin |
| `GET /user/dashboard` | Yes | Admin or User |
| `GET /customers/*` | Yes | Any (some Admin or User) |
| `*/filters` | Yes | Any |
| `GET /uploads/history` | Yes | Any |

---

## Data Masking

### Philosophy

**Masking rules** (enforced via `.cursor/rules/identity-masking.mdc`):
1. Mask only at the **response construction layer** — never modify stored data
2. **Do not mask in routers** — routers call services; masking happens in services
3. **Centralize masking logic** — use `app/utils/masking.py` only

### Masking Functions

**File**: `app/utils/masking.py`

All masking functions are **defensive**: they accept `str | None`, never raise exceptions, and return `None` when input is `None`.

#### `mask_generic(value, keep_start, keep_end, mask_char="*")`

The core masking engine. All other functions delegate to it.

**Logic**:
1. `None` or non-string → return `None`
2. Empty/whitespace-only → return as-is
3. Single character → return `*`
4. If `keep_start + keep_end >= len(value)` → mask all but last character (`****F`)
5. Otherwise → `start_chars + *** + end_chars`

**Triple-layer safety**: The function has nested try/except blocks:
- Primary logic in the main try block
- Fallback: mask everything (`*` * length)
- Final fallback: return `None`

This ensures masking **never** leaks raw data, even under unexpected input conditions.

#### Specialized Masking Functions

| Function | Config | Example |
|----------|--------|---------|
| `mask_pan(value)` | `keep_start=5, keep_end=1` | `ABCDE1234F` → `ABCDE****F` |
| `mask_aadhaar(value)` | `keep_start=0, keep_end=4` | `123456789012` → `********9012` |
| `mask_passport(value)` | `keep_start=2, keep_end=2` | `A1234567` → `A1****67` |
| `mask_driving_license(value)` | `keep_start=2, keep_end=4` | `DL000000000001` → `DL********0001` |

**Note**: `mask_aadhaar()` exists in `masking.py` but is not directly used by the service layer. Instead, the service uses `mask_generic(uid, keep_start=0, keep_end=4)` directly — effectively identical behavior.

### Where Masking Is Applied

Masking is applied in **three locations** within `customer_service.py`:

1. **`get_customer_details()`** — via `_apply_identity_masking(identity_payload)` after Pydantic model validation
2. **`get_customer_timeline()`** — via `_apply_identity_masking(entry)` after constructing each timeline entry
3. **`search_customers()`** — PAN masked inline via `mask_pan(row[5])` during result construction
4. **`iter_customers_for_export()`** — All identity fields masked directly on the identity ORM row before yielding

The `_apply_identity_masking()` helper handles six fields in a single call:

```python
def _apply_identity_masking(obj):
    setattr(obj, "pan", mask_pan(getattr(obj, "pan", None)))
    setattr(obj, "uid", mask_generic(getattr(obj, "uid", None), keep_start=0, keep_end=4))
    setattr(obj, "passport", mask_passport(getattr(obj, "passport", None)))
    setattr(obj, "driving_license", mask_driving_license(getattr(obj, "driving_license", None)))
    setattr(obj, "voter_id", mask_generic(getattr(obj, "voter_id", None), keep_start=2, keep_end=2))
    setattr(obj, "ration_card", mask_generic(getattr(obj, "ration_card", None), keep_start=2, keep_end=2))
```

Each field operation is wrapped in its own `try/except` so a failure on one field does not prevent masking of the others.

### CSV Export Masking

The CSV export path (`iter_customers_for_export()`) applies masking differently — it modifies the ORM identity row attributes directly before yielding:

```python
if identity_row is not None:
    identity_row.pan = mask_pan(identity_row.pan)
    identity_row.passport = mask_passport(identity_row.passport)
    identity_row.voter_id = mask_generic(identity_row.voter_id, keep_start=2, keep_end=2)
    identity_row.uid = mask_generic(identity_row.uid, keep_start=0, keep_end=4)
    identity_row.driving_license = mask_driving_license(identity_row.driving_license)
    identity_row.ration_card = mask_generic(identity_row.ration_card, keep_start=2, keep_end=2)
```

**Important note**: This modifies the ORM object in the session. Since the session uses `autoflush=False`, these in-memory modifications are not persisted to the database. However, this is a subtle footgun — if `autoflush` were ever enabled or a commit happened during iteration, masked values could be written to the DB. The current configuration is safe.

---

## Password Reset Security

**File**: `app/services/password_reset_service.py`

### Token Generation and Storage

1. 32-byte cryptographically secure random token via `secrets.token_urlsafe(32)`
2. SHA-256 hash of the token is stored in the database (`token_hash` column)
3. The raw token is never stored — only sent to the user
4. Token expires after 15 minutes (`RESET_TOKEN_EXP_MINUTES = 15`)

### Anti-Enumeration

The `POST /auth/forgot-password` endpoint returns an identical response regardless of whether the email exists:

```json
{"message": "If the account exists, a password reset link will be sent."}
```

If no user matches the email, the function simply returns without creating a token.

### Token Invalidation

On successful password reset:
1. The used token is marked as `used = True`
2. ALL other unused tokens for that user are also invalidated

```python
db.query(PasswordResetToken)
    .filter(PasswordResetToken.user_id == user.id, PasswordResetToken.used.is_(False))
    .update({PasswordResetToken.used: True}, synchronize_session="fetch")
```

This prevents concurrent reset requests from creating lingering valid tokens.

---

## Audit Logging

### Login Activity

Every login attempt (success AND failure) is logged with:
- User identifier (email used for login)
- Resolved email (if user found)
- IP address (from `request.client.host`)
- User agent string
- Success boolean
- Failure reason (`"user_not_found"` or `"invalid_credentials"`)

The failure reason is explicitly set to `None` on success:
```python
failure_reason=failure_reason if not success else None
```

### Customer View Activity

Every time a customer detail or timeline is viewed, a record is created with:
- User ID of the viewer
- Customer ID viewed
- Timestamp

This is wrapped in a savepoint transaction — audit logging failure never prevents the customer data from being returned:
```python
try:
    with db.begin_nested():
        log_customer_view(db=db, user_id=current_user.id, customer_id=customer_id)
    db.commit()
except Exception:
    db.rollback()
```

---

## Admin Self-Protection

The user management service includes guardrails to prevent admins from shooting themselves in the foot:

1. **Cannot delete self**: `delete_user_admin()` checks `current_admin.id == user_id`
2. **Cannot demote self**: `update_user_admin()` checks if the admin is changing their own role away from admin
3. **Only admin can create admin**: Both `create_user()` and `create_user_admin()` enforce this
