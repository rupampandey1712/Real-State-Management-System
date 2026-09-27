from estate_common.settings import CommonSettings


class EngagementSettings(CommonSettings):
    cosmos_endpoint: str = "http://cosmos:8081/"
    cosmos_key: str = ""
    cosmos_database: str = "estateai"


settings = EngagementSettings(service_name="engagement")
