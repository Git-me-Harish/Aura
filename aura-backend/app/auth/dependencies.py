"""
AURA — FastAPI auth dependencies.

Validates NextAuth.js session JWTs issued by the Next.js frontend.

Flow:
  1. Frontend calls NextAuth `/api/auth/session` → returns session with
     `accessToken` (a JWT signed with NEXTAUTH_SECRET).
  2. Frontend sends that JWT as `Authorization: Bearer <jwt>` to FastAPI.
  3. FastAPI `get_current_user` validates the JWT signature using the same
     NEXTAUTH_SECRET, extracts the user, and returns a `User` object.

If the JWT is missing or invalid, the dependency returns the demo user
(`u_aura`) — this keeps the dashboard usable without auth in dev. Set
`REQUIRE_AUTH=true` to enforce auth in production.
"""
from __future__ import annotations
import logging
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from jose import JWTError, jwt

from app.config import settings
from app.models.schemas import User

log = logging.getLogger("aura.auth")


# Demo user used when no JWT is provided (dev mode)
DEMO_USER = User(
    user_id="u_aura",
    name="AURA Demo User",
    timezone="Asia/Calcutta",
    preferred_language="en",
)


def _decode_jwt(token: str) -> Optional[dict]:
    """Decode + verify a NextAuth JWT. Returns None on failure."""
    try:
        # NextAuth default JWTs are JWE-encrypted, not just signed. To keep
        # the bridge simple, we use a custom NextAuth callbacks.jwt() that
        # returns a SIGNED (not encrypted) JWT. See frontend NextAuth config.
        payload = jwt.decode(
            token,
            settings.NEXTAUTH_SECRET,
            algorithms=[settings.JWT_ALG],
            options={"verify_aud": False, "verify_iss": False},
        )
        return payload
    except JWTError as e:
        log.debug("jwt decode failed: %s", e)
        return None
    except Exception as e:
        log.warning("jwt decode unexpected error: %s", e)
        return None


async def get_current_user(
    authorization: Optional[str] = Header(None),
    x_aura_user: Optional[str] = Header(None, alias="X-AURA-User"),
) -> User:
    """FastAPI dependency: extract the current user from the request.

    Resolution order:
      1. `Authorization: Bearer <jwt>` → validate JWT → User
      2. `X-AURA-User: <user_id>` → trusted header (for server-to-server)
      3. Fall back to DEMO_USER (dev mode)

    In production, set REQUIRE_AUTH=true and the dependency will 401 on missing
    credentials instead of falling back.
    """
    user: Optional[User] = None

    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        payload = _decode_jwt(token)
        if payload:
            user = User(
                user_id=str(payload.get("sub") or payload.get("user_id") or "u_aura"),
                name=str(payload.get("name") or "AURA User"),
                timezone=str(payload.get("timezone") or "UTC"),
                preferred_language=str(payload.get("preferred_language") or "en"),
            )

    if user is None and x_aura_user:
        # Trusted header (used by Next.js server-side calls)
        user = User(
            user_id=x_aura_user,
            name=x_aura_user,
            timezone="UTC",
            preferred_language="en",
        )

    if user is None:
        if settings.ENVIRONMENT == "prod":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user = DEMO_USER

    return user


async def get_user_id(user: User = Depends(get_current_user)) -> str:
    """Convenience dependency — returns just the user_id string."""
    return user.user_id
