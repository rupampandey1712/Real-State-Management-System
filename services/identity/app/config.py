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
    web_base_url: str = "http://localhost:3000"
    magic_link_ttl_s: int = 900
    # Google sign-in (FR-6.1). Empty = the Google button is hidden. OAuth client of type "Web application".
    google_client_id: str = ""
    google_jwks_url: str = "https://www.googleapis.com/oauth2/v3/certs"
    # Account deletion (FR-6.4, NFR-10): scrubbed at once, row purged after this many days.
    account_purge_days: int = 30
    purge_interval_s: int = 3600
    dev_admin_email: str = "admin@example.com"
    dev_agent_email: str = "agent@example.com"


settings = IdentitySettings(service_name="identity")
