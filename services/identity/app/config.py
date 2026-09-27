from estate_common.settings import CommonSettings


class IdentitySettings(CommonSettings):
    database_url: str = "postgresql+asyncpg://estate:estate@postgres:5432/identity"
    access_token_ttl_s: int = 900            # 15 min — short, because revocation fails open if Redis is down
    refresh_token_ttl_s: int = 30 * 86_400   # 30 days, rotated on every use
    signing_key_rotation_days: int = 30
    refresh_cookie_name: str = "estate_refresh"
    otp_ttl_s: int = 600
    smtp_host: str = "mailpit"
    smtp_port: int = 1025
    email_from: str = "no-reply@estateai.local"
    dev_admin_email: str = "admin@example.com"
    dev_agent_email: str = "agent@example.com"


settings = IdentitySettings(service_name="identity")
