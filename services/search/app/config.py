from estate_common.settings import CommonSettings


class SearchSettings(CommonSettings):
    database_url: str = "postgresql+asyncpg://estate:estate@postgres:5432/search"
    redis_url: str = "redis://redis:6379/0"
    embedding_dim: int = 768  # must match the ai service EMBEDDING_DIM

    feature_nl_search: bool = True
    nl_parse_timeout_s: float = 2.0
    embed_timeout_s: float = 1.5
    nl_search_cache_ttl_s: int = 86400

    rank_w_semantic: float = 0.55
    rank_w_filter: float = 0.30
    rank_w_freshness: float = 0.15
    rank_candidates: int = 200


settings = SearchSettings(service_name="search")
