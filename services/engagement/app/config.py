from estate_common.settings import CommonSettings


class EngagementSettings(CommonSettings):
    cosmos_endpoint: str = "http://cosmos:8081/"
    cosmos_key: str = ""
    cosmos_database: str = "estateai"
    enquiry_retention_days: int = 730  # NFR-10: enquiries are kept for 2 years
    retention_interval_s: int = 86400


settings = EngagementSettings(service_name="engagement")
