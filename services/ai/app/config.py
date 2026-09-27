from estate_common.settings import CommonSettings


class AISettings(CommonSettings):
    database_url: str = "postgresql+asyncpg://estate:estate@postgres:5432/ai"
    storage_connection: str = ""
    media_container: str = "listing-media"

    # Google Gemini (ADR-0013). Model IDs come from config only — never literals in feature code.
    gemini_api_key: str = ""
    ai_fake: bool = True  # True → FakeLLMClient (no network, deterministic) for local dev & tests
    ai_model_search: str = "gemini-3.1-flash-lite"
    ai_model_describe: str = "gemini-3.8-flash"
    ai_model_qa: str = "gemini-3.8-flash"
    ai_model_judge: str = "gemini-3.1-pro-preview"
    ai_timeout_search_s: float = 1.5
    ai_timeout_describe_s: float = 30.0
    ai_timeout_qa_s: float = 30.0
    ai_max_retries: int = 2

    ai_prompt_version_nl_search: int = 1
    ai_prompt_version_describe: int = 1
    ai_prompt_version_qa: int = 1

    # Embeddings (ADR-0003)
    embedding_provider: str = "fake"  # fake | gemini (uses GEMINI_API_KEY)
    embedding_model: str = "gemini-embedding-001"
    embedding_dim: int = 768  # gemini-embedding-001 supports 128–3072; 768 is a recommended size

    # Cosmos DB — AI request telemetry (ADR-0012)
    cosmos_endpoint: str = "http://cosmos:8081/"
    cosmos_key: str = ""
    cosmos_database: str = "estateai"
    ai_log_retention_days: int = 30

    # RAG
    qa_top_k_chunks: int = 6
    qa_min_similarity: float = 0.3
    qa_max_history_turns: int = 6

    feature_ai_describe: bool = True
    feature_listing_qa: bool = True

    def model_for(self, config_key: str) -> str:
        return getattr(self, config_key.lower())


settings = AISettings(service_name="ai")
