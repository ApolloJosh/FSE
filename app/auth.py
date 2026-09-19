"""Sign-in via Google and GitHub. No passwords are stored, hashed, reset or
breached, because none are ever collected.

Authlib handles the OAuth dance rather than hand-rolled redirects and token
exchanges - this is the one part of the app where a clever mistake hurts real
people, so it uses the boring library.
"""

from __future__ import annotations

import os
import secrets
from typing import Any

from authlib.integrations.starlette_client import OAuth
from fastapi import HTTPException, Request

from . import db

STARTING_CREDITS = db.cents(50.00)
SESSION_USER = "uid"
CSRF_KEY = "csrf"

oauth = OAuth()

GOOGLE_DISCOVERY = "https://accounts.google.com/.well-known/openid-configuration"


def configure() -> list[str]:
    """Register whichever providers have credentials. Returns the enabled ones,
    so the sign-in page can offer only the buttons that actually work."""
    enabled = []
    if os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"):
        oauth.register(
            name="google",
            client_id=os.environ["GOOGLE_CLIENT_ID"],
            client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
            server_metadata_url=GOOGLE_DISCOVERY,
            client_kwargs={"scope": "openid email profile"},
        )
        enabled.append("google")
    if os.environ.get("GITHUB_CLIENT_ID") and os.environ.get("GITHUB_CLIENT_SECRET"):
        oauth.register(
            name="github",
            client_id=os.environ["GITHUB_CLIENT_ID"],
            client_secret=os.environ["GITHUB_CLIENT_SECRET"],
            access_token_url="https://github.com/login/oauth/access_token",
            authorize_url="https://github.com/login/oauth/authorize",
            api_base_url="https://api.github.com/",
            client_kwargs={"scope": "read:user"},
        )
        enabled.append("github")
    return enabled


async def profile_from(provider: str, token: dict[str, Any],
                       client) -> tuple[str, str, str | None]:
    """Return (provider_id, display_name, avatar_url).

    Only what the game needs: a stable id and something to put on a leaderboard.
    No email is stored - it is never used, so keeping it is a liability.
    """
    if provider == "google":
        info = token.get("userinfo") or {}
        if not info:
            info = await client.userinfo(token=token)
        return (str(info["sub"]), info.get("name") or "Player", info.get("picture"))

    resp = await client.get("user", token=token)
    info = resp.json()
    return (str(info["id"]),
            info.get("name") or info.get("login") or "Player",
            info.get("avatar_url"))


def sign_in(request: Request, user_id: int) -> None:
    request.session[SESSION_USER] = user_id
    request.session[CSRF_KEY] = secrets.token_urlsafe(24)


def sign_out(request: Request) -> None:
    request.session.clear()


def current_user_id(request: Request) -> int | None:
    value = request.session.get(SESSION_USER)
    return int(value) if value is not None else None


def require_user_id(request: Request) -> int:
    user_id = current_user_id(request)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Sign in to do that.")
    return user_id


def csrf_token(request: Request) -> str:
    token = request.session.get(CSRF_KEY)
    if not token:
        token = secrets.token_urlsafe(24)
        request.session[CSRF_KEY] = token
    return token


def check_csrf(request: Request, submitted: str | None) -> None:
    """Every state-changing POST carries this. Without it, any page on the
    internet could spend a signed-in player's Credits with a hidden form."""
    expected = request.session.get(CSRF_KEY)
    if not expected or not submitted or not secrets.compare_digest(expected, submitted):
        raise HTTPException(status_code=403, detail="Stale form. Reload and retry.")
