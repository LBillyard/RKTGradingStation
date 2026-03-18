"""AWS S3 storage backend — uploads files to S3, serves via CloudFront."""

import logging
from pathlib import Path
from typing import Optional

from app.services.storage.base import BaseStorage

logger = logging.getLogger(__name__)


class S3Storage(BaseStorage):
    """Store files in AWS S3 with optional CloudFront CDN."""

    def __init__(
        self,
        bucket: str,
        region: str = "eu-west-2",
        access_key_id: str = "",
        secret_access_key: str = "",
        cdn_url: str = "",
    ):
        self._bucket = bucket
        self._region = region
        self._cdn_url = cdn_url.rstrip("/")
        self._client: Optional[object] = None
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key

    def _get_client(self):
        """Lazy-initialize the boto3 S3 client."""
        if self._client is None:
            import boto3

            kwargs = {"region_name": self._region}
            if self._access_key_id and self._secret_access_key:
                kwargs["aws_access_key_id"] = self._access_key_id
                kwargs["aws_secret_access_key"] = self._secret_access_key
            self._client = boto3.client("s3", **kwargs)
        return self._client

    def upload(self, file_path: str, key: str) -> str:
        """Upload a local file to S3."""
        client = self._get_client()

        # Determine content type from extension
        ext = Path(file_path).suffix.lower()
        content_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".svg": "image/svg+xml",
            ".json": "application/json",
        }
        content_type = content_types.get(ext, "application/octet-stream")

        client.upload_file(
            file_path,
            self._bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )
        logger.info(f"S3Storage: uploaded {key} to s3://{self._bucket}/{key}")
        return key

    def get_url(self, key: str) -> str:
        """Return a CloudFront or S3 URL for the file."""
        if not key:
            return ""
        if self._cdn_url:
            return f"{self._cdn_url}/{key}"
        return f"https://{self._bucket}.s3.{self._region}.amazonaws.com/{key}"

    def delete(self, key: str) -> None:
        """Delete a file from S3."""
        client = self._get_client()
        client.delete_object(Bucket=self._bucket, Key=key)
        logger.info(f"S3Storage: deleted {key}")

    def exists(self, key: str) -> bool:
        """Check if a file exists in S3."""
        client = self._get_client()
        try:
            client.head_object(Bucket=self._bucket, Key=key)
            return True
        except client.exceptions.ClientError:
            return False
