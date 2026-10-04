"""Sign-in methods besides the email code (FR-6.1, ADR-0017): email magic link and Google.

Magic link: a 256-bit random token, stored hashed in Redis for `magic_link_ttl_s`, single use. The link
puts it in the URL fragment (`#token=`), so it never reaches server or proxy access logs.

Google: the SPA gets an ID token from Google Identity Services; we verify its RS256 signature against
Google's JWKS, the audience (our client id), the issuer and `email_verified`. We never see a password.
"""

import hashlib
import secrets
from email.message import EmailMessage
from functools import lru_cache

import aiosmtplib
import jwt

from app.config import settings
from app.otp import _redis

GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


class GoogleTokenInvalid(Exception):
    pass


def _magic_key(token: str) -> str:
    return "magic:" + hashlib.sha256(token.encode()).hexdigest()


async def create_magic_token(email: str) -> str:
    token = secrets.token_urlsafe(32)
    await _redis.set(_magic_key(token), email, ex=settings.magic_link_ttl_s)
    return token


async def consume_magic_token(token: str) -> str | None:
    """Returns the email the link was sent to, or None. A token works once (GETDEL is atomic)."""
    if not 20 <= len(token) <= 100:
        return None
    email = await _redis.getdel(_magic_key(token))
    if not email:
        return None
    return email.decode() if isinstance(email, bytes) else str(email)


def magic_link(token: str) -> str:
    return f"{settings.web_base_url}/login/magic#token={token}"


async def send_sign_in_email(email: str, code: str, token: str) -> None:
    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = email
    message["Subject"] = f"Your EstateAI sign-in code: {code}"
    message.set_content(
        f"Sign in with one click:\n{magic_link(token)}\n\n"
        f"Or enter this code: {code}\n\n"
        f"The link works once and expires in {settings.magic_link_ttl_s // 60} minutes. "
        "If you didn't ask to sign in, ignore this email."
    )
    await aiosmtplib.send(message, hostname=settings.smtp_host, port=settings.smtp_port)


@lru_cache
def _google_jwks() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(settings.google_jwks_url, cache_keys=True, lifespan=3600, timeout=5)


def verify_google_id_token(credential: str, key_resolver=None) -> tuple[str, str | None]:
    """Returns (email, name). Raises GoogleTokenInvalid. `key_resolver` is injectable for tests."""
    if not settings.google_client_id:
        raise GoogleTokenInvalid("Google sign-in is not configured.")
    try:
        key = key_resolver(credential) if key_resolver else _google_jwks().get_signing_key_from_jwt(credential).key
        claims = jwt.decode(credential, key, algorithms=["RS256"], audience=settings.google_client_id,
                            options={"require": ["exp", "iat", "iss", "sub", "email"]}, leeway=30)
    except jwt.PyJWTError as exc:
        raise GoogleTokenInvalid(str(exc)) from exc
    if claims["iss"] not in GOOGLE_ISSUERS:
        raise GoogleTokenInvalid("Unexpected issuer.")
    if claims.get("email_verified") is not True:
        raise GoogleTokenInvalid("Google has not verified this email address.")
    return str(claims["email"]).lower(), claims.get("name")
