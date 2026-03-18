"""Storage interface for images and files."""

from abc import ABC, abstractmethod


class BaseStorage(ABC):
    """Abstract file storage backend."""

    @abstractmethod
    def upload(self, file_path: str, key: str) -> str:
        """Upload a local file to storage.

        Args:
            file_path: Absolute path to local file.
            key: Storage key (e.g. "scans/raw/{session_id}/front.png").

        Returns:
            URL or key for retrieving the file.
        """
        ...

    @abstractmethod
    def get_url(self, key: str) -> str:
        """Get a URL for accessing a stored file.

        Args:
            key: Storage key.

        Returns:
            URL suitable for embedding in HTML (e.g. "/data/scans/..." or "https://cdn.../scans/...").
        """
        ...

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete a file from storage."""
        ...

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if a file exists in storage."""
        ...
