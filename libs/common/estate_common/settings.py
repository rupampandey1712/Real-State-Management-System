from pydantic_settings import BaseSettings, SettingsConfigDict


class CommonSettings(BaseSettings):
    """Settings every service needs. Services subclass this and add their own fields."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "unknown"
    app_env: str = "local"
    log_level: str = "INFO"

    # JWT (ADR-0015): RS256 tokens signed by the identity service, verified everywhere via JWKS.
    jwt_issuer: str = "estateai-identity"
    jwt_audience: str = "estateai"

    redis_url: str = "redis://redis:6379/0"
    servicebus_connection: str = ""
    otel_exporter_otlp_endpoint: str = ""

    # Internal service URLs (Azure Container Apps internal ingress in prod)
    identity_url: str = "http://identity:8000"
    listing_url: str = "http://listing:8000"
    search_url: str = "http://search:8000"
    ai_url: str = "http://ai:8000"
    engagement_url: str = "http://engagement:8000"

    # Resilience defaults for service-to-service HTTP (estate_common.http)
    http_timeout_s: float = 5.0
    http_retries: int = 2
    breaker_failure_threshold: int = 5
    breaker_reset_s: float = 30.0

    @property
    def is_local(self) -> bool:
        return self.app_env == "local"

    @property
    def jwks_url(self) -> str:
        return f"{self.identity_url}/.well-known/jwks.json"
