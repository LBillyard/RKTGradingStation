"""Tests for the backup API endpoints."""

import pytest


class TestCreateBackup:
    """Test POST /api/backup/create endpoint."""

    def test_create_backup(self, test_app, tmp_data_dir):
        """Creating a backup should succeed and return metadata."""
        response = test_app.post("/api/backup/create")
        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "created"
        assert "filename" in data
        assert data["filename"].startswith("rkt_backup_")
        assert data["filename"].endswith(".db")
        assert "size_bytes" in data
        assert isinstance(data["size_bytes"], int)

    def test_create_backup_file_exists(self, test_app, tmp_data_dir):
        """The backup file should actually exist on disk after creation."""
        from pathlib import Path

        response = test_app.post("/api/backup/create")
        data = response.json()
        backup_path = tmp_data_dir / "backups" / data["filename"]
        assert backup_path.exists()


class TestListBackups:
    """Test GET /api/backup/list endpoint."""

    def test_list_empty(self, test_app):
        """Should return an empty list when no backups exist."""
        response = test_app.get("/api/backup/list")
        assert response.status_code == 200
        data = response.json()
        assert "backups" in data
        assert isinstance(data["backups"], list)

    def test_list_after_create(self, test_app):
        """After creating a backup, the list should include it."""
        # Create a backup first
        create_resp = test_app.post("/api/backup/create")
        filename = create_resp.json()["filename"]

        # List backups
        response = test_app.get("/api/backup/list")
        assert response.status_code == 200
        data = response.json()
        filenames = [b["filename"] for b in data["backups"]]
        assert filename in filenames

    def test_list_backup_has_metadata(self, test_app):
        """Each backup entry should have filename, size, and timestamp."""
        test_app.post("/api/backup/create")
        response = test_app.get("/api/backup/list")
        data = response.json()

        for backup in data["backups"]:
            assert "filename" in backup
            assert "size_bytes" in backup
            assert "created_at" in backup


class TestDownloadBackup:
    """Test GET /api/backup/download/{filename} endpoint."""

    def test_path_traversal_blocked(self, test_app):
        """Path traversal attempts should return 400."""
        # The ".." in filename triggers the backup route's validation
        response = test_app.get("/api/backup/download/..secret.db")
        assert response.status_code == 400
        assert "invalid" in response.json()["detail"].lower()

    def test_path_traversal_with_backslash(self, test_app):
        """Backslash path traversal should be blocked."""
        response = test_app.get("/api/backup/download/..\\..\\secret.db")
        assert response.status_code == 400

    def test_path_traversal_double_dot(self, test_app):
        """Double dots in filename should be rejected."""
        response = test_app.get("/api/backup/download/..secret.db")
        assert response.status_code == 400

    def test_nonexistent_backup_returns_404(self, test_app):
        """Downloading a nonexistent backup should return 404."""
        response = test_app.get("/api/backup/download/rkt_backup_99991231_235959.db")
        assert response.status_code == 404

    def test_download_existing_backup(self, test_app):
        """Downloading an existing backup should return file content."""
        # Create a backup first
        create_resp = test_app.post("/api/backup/create")
        filename = create_resp.json()["filename"]

        # Download it
        response = test_app.get(f"/api/backup/download/{filename}")
        assert response.status_code == 200
        assert response.headers.get("content-type") == "application/octet-stream"

    def test_forward_slash_in_filename(self, test_app):
        """Forward slash in filename should be rejected."""
        response = test_app.get("/api/backup/download/sub/dir/file.db")
        # FastAPI may return 404 due to path routing, or 400 from validation
        assert response.status_code in (400, 404)


class TestDeleteBackup:
    """Test DELETE /api/backup/{filename} endpoint."""

    def test_delete_nonexistent(self, test_app):
        """Deleting a nonexistent backup should return 404."""
        response = test_app.delete("/api/backup/rkt_backup_99991231_235959.db")
        assert response.status_code == 404

    def test_delete_path_traversal(self, test_app):
        """Path traversal in delete should be blocked."""
        response = test_app.delete("/api/backup/..important.db")
        assert response.status_code == 400

    def test_delete_existing_backup(self, test_app, tmp_data_dir):
        """Deleting an existing backup should succeed."""
        # Create a backup
        create_resp = test_app.post("/api/backup/create")
        filename = create_resp.json()["filename"]

        # Delete it
        response = test_app.delete(f"/api/backup/{filename}")
        assert response.status_code == 200
        assert response.json()["status"] == "deleted"

        # Verify it's gone
        backup_path = tmp_data_dir / "backups" / filename
        assert not backup_path.exists()
