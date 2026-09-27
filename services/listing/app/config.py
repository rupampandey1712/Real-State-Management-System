from estate_common.settings import CommonSettings


class ListingSettings(CommonSettings):
    database_url: str = "postgresql+asyncpg://estate:estate@postgres:5432/listing"
    storage_connection: str = ""
    media_container: str = "listing-media"
    max_image_mb: int = 15
    max_images_per_listing: int = 30
    max_document_mb: int = 20
    max_documents_per_listing: int = 10


settings = ListingSettings(service_name="listing")
