"""Image storage abstraction — local filesystem or S3."""

from app.services.storage.base import BaseStorage

_storage_instance: BaseStorage | None = None


def get_storage() -> BaseStorage:
    """Get the storage backend based on app mode.

    Returns LocalStorage for desktop/agent mode, S3Storage for cloud mode.
    Singleton — created once and reused.
    """
    global _storage_instance
    if _storage_instance is not None:
        return _storage_instance

    from app.config import settings

    if settings.mode == "cloud" and settings.s3.bucket:
        from app.services.storage.s3_storage import S3Storage
        _storage_instance = S3Storage(
            bucket=settings.s3.bucket,
            region=settings.s3.region,
            access_key_id=settings.s3.access_key_id,
            secret_access_key=settings.s3.secret_access_key,
            cdn_url=settings.s3.cdn_url,
        )
    else:
        from app.services.storage.local_storage import LocalStorage
        _storage_instance = LocalStorage(data_dir=str(settings.data_dir))

    return _storage_instance
