"""Azure Blob Storage (Azurite locally)."""

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.storage.blob import ContentSettings
from azure.storage.blob.aio import BlobServiceClient

from estate_common.errors import NotFound


class BlobStore:
    def __init__(self, connection_string: str, container: str):
        self._service = BlobServiceClient.from_connection_string(connection_string)
        self._container = self._service.get_container_client(container)

    async def ensure_container(self) -> None:
        try:
            await self._container.create_container()
        except ResourceExistsError:
            pass

    async def upload(self, key: str, data: bytes, content_type: str) -> None:
        await self._container.upload_blob(
            key, data, overwrite=True, content_settings=ContentSettings(content_type=content_type)
        )

    async def download(self, key: str) -> tuple[bytes, str]:
        try:
            downloader = await self._container.download_blob(key)
        except ResourceNotFoundError as exc:
            raise NotFound("File not found.") from exc
        data = await downloader.readall()
        return data, downloader.properties.content_settings.content_type or "application/octet-stream"

    async def delete(self, key: str) -> None:
        try:
            await self._container.delete_blob(key)
        except ResourceNotFoundError:
            pass

    async def close(self) -> None:
        await self._service.close()
