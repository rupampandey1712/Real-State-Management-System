"""Email one-time passcodes (local auth). Production uses Microsoft Entra External ID (ADR-0009)."""

import hashlib
import hmac
import secrets
from email.message import EmailMessage

import aiosmtplib
import redis.asyncio as redis

from app.config import settings

_redis = redis.from_url(settings.redis_url)
MAX_ATTEMPTS = 5


def _hash(code: str) -> str:
    return hashlib.sha256(f"{settings.jwt_issuer}:{code}".encode()).hexdigest()


async def create_code(email: str) -> str:
    code = f"{secrets.randbelow(1_000_000):06d}"
    await _redis.set(f"otp:{email}", _hash(code), ex=settings.otp_ttl_s)
    await _redis.delete(f"otp_attempts:{email}")
    return code


async def verify_code(email: str, code: str) -> bool:
    attempts = await _redis.incr(f"otp_attempts:{email}")
    await _redis.expire(f"otp_attempts:{email}", settings.otp_ttl_s)
    if attempts > MAX_ATTEMPTS:
        return False
    stored = await _redis.get(f"otp:{email}")
    if stored is None or not hmac.compare_digest(stored.decode(), _hash(code)):
        return False
    await _redis.delete(f"otp:{email}")
    return True


async def send_code_email(email: str, code: str) -> None:
    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = email
    message["Subject"] = f"Your EstateAI sign-in code: {code}"
    message.set_content(f"Your sign-in code is {code}. It expires in {settings.otp_ttl_s // 60} minutes.")
    await aiosmtplib.send(message, hostname=settings.smtp_host, port=settings.smtp_port)
