"""Rate limiting configuration using slowapi.

Protects brute-force-sensitive endpoints (login, forgot-password) by
throttling requests per IP address.  Uses an in-memory store which is
sufficient for a single-process Render deployment.

Limits:
  - /auth/login:           5 requests per minute per IP
  - /auth/forgot-password: 3 requests per minute per IP
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

# Key function: rate-limit by client IP address.
limiter = Limiter(key_func=get_remote_address)
