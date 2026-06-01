"""
In-memory sliding window rate limiter middleware.

- Per-IP: 100 requests/minute on all endpoints
- Per-user: 60 requests/minute on authenticated endpoints
- Returns 429 with Retry-After header when exceeded
"""

import time
from collections import defaultdict
from threading import Lock

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# Sliding window: 60 seconds
_WINDOW_SECONDS = 60

# Limits
_IP_LIMIT = 100
_USER_LIMIT = 60

# Stores: key -> list of timestamps
_ip_hits: dict[str, list[float]] = defaultdict(list)
_user_hits: dict[str, list[float]] = defaultdict(list)

# Single lock protects both dicts (simple; contention is negligible at
# the traffic volumes this in-memory approach is designed for).
_lock = Lock()


def _prune_and_count(bucket: list[float], now: float) -> int:
    """Remove timestamps older than the window and return current count."""
    cutoff = now - _WINDOW_SECONDS
    # In-place prune: timestamps are appended in order so we can bisect,
    # but a simple filter is clear and fast enough for <=100 entries.
    bucket[:] = [t for t in bucket if t > cutoff]
    return len(bucket)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        now = time.time()

        # --- Per-IP check ---
        client_ip = request.client.host if request.client else "unknown"
        with _lock:
            ip_count = _prune_and_count(_ip_hits[client_ip], now)
            if ip_count >= _IP_LIMIT:
                retry_after = int(_WINDOW_SECONDS - (now - _ip_hits[client_ip][0])) + 1
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded (per-IP). Try again later."},
                    headers={"Retry-After": str(max(retry_after, 1))},
                )
            _ip_hits[client_ip].append(now)

        # --- Per-user check (only if an Authorization header is present) ---
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            # Extract the user id from the JWT *without* full validation here;
            # the auth dependency will do full validation later.  We just need
            # a stable key.  Decode the payload (middle segment) cheaply.
            token = auth_header[7:]
            user_key = _extract_sub(token)
            if user_key:
                with _lock:
                    user_count = _prune_and_count(_user_hits[user_key], now)
                    if user_count >= _USER_LIMIT:
                        retry_after = int(
                            _WINDOW_SECONDS - (now - _user_hits[user_key][0])
                        ) + 1
                        return JSONResponse(
                            status_code=429,
                            content={
                                "detail": "Rate limit exceeded (per-user). Try again later."
                            },
                            headers={"Retry-After": str(max(retry_after, 1))},
                        )
                    _user_hits[user_key].append(now)

        return await call_next(request)


def _extract_sub(token: str) -> str | None:
    """
    Best-effort extraction of the 'sub' claim from a JWT without
    cryptographic verification (just base64-decode the payload).
    Returns None on any failure.
    """
    import base64
    import json

    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        # Add padding
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return payload.get("sub")
    except Exception:
        return None
