"""Enterprise Audit Backup Manager with cryptographic integrity verification and retention."""

from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.core.logging import logger

settings = get_settings()


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


class AuditBackupManager:
    """Manages compressed legal audit log archives and cryptographic manifests."""

    def __init__(self):
        self.logs_dir = Path(getattr(settings, "LOGS_DIR", "./data/logs"))
        self.backup_dir = Path(getattr(settings, "LOG_BACKUP_DIR", "./data/logs/backups"))
        self._ensure_directories()
        self.manifest_file = self.backup_dir / "manifest.json"

    def _ensure_directories(self) -> None:
        """Create logs and backup directories if they don't exist with safe fallbacks."""
        for candidate_logs, candidate_backup in [
            (self.logs_dir, self.backup_dir),
            (Path("./data/logs"), Path("./data/logs/backups")),
            (Path("/tmp/logs"), Path("/tmp/logs/backups")),
        ]:
            try:
                candidate_logs.mkdir(parents=True, exist_ok=True)
                candidate_backup.mkdir(parents=True, exist_ok=True)
                # Verify write permission
                probe = candidate_backup / ".probe"
                probe.touch()
                probe.unlink()
                self.logs_dir = candidate_logs
                self.backup_dir = candidate_backup
                self.manifest_file = self.backup_dir / "manifest.json"
                return
            except Exception:
                continue

    def _calculate_sha256(self, file_path: Path) -> str:
        """Calculate SHA-256 checksum of a file."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _load_manifest(self) -> Dict[str, Any]:
        """Load cryptographic manifest from disk."""
        if self.manifest_file.exists():
            try:
                with open(self.manifest_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read backup manifest: {e}")
        return {"version": "1.0", "archives": []}

    def _save_manifest(self, manifest: Dict[str, Any]) -> None:
        """Persist cryptographic manifest to disk."""
        try:
            with open(self.manifest_file, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to persist backup manifest: {e}")

    def create_backup(
        self,
        retention_days: Optional[int] = None,
        operator_username: str = "system",
        compliance_remark: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a compressed .tar.gz archive of active audit logs with SHA-256 verification."""
        self._ensure_directories()
        timestamp_str = utc_now().strftime("%Y%m%dT%H%M%SZ")
        archive_name = f"audit_archive_{timestamp_str}.tar.gz"
        archive_path = self.backup_dir / archive_name

        # Target log files to include in backup
        candidate_files = [
            self.logs_dir / "app.log",
            self.logs_dir / "audit_trail.jsonl",
            self.logs_dir / "business_risk.jsonl",
        ]
        files_to_pack = [f for f in candidate_files if f.exists() and f.stat().st_size > 0]

        if not files_to_pack:
            # If log files are empty or don't exist yet, pack empty placeholder or existing logs
            files_to_pack = [f for f in candidate_files if f.exists()]

        # Create tar.gz archive
        with tarfile.open(archive_path, "w:gz") as tar:
            for file_path in files_to_pack:
                tar.add(file_path, arcname=file_path.name)

        # Compute SHA-256 checksum
        archive_sha256 = self._calculate_sha256(archive_path)
        archive_size = archive_path.stat().st_size

        entry = {
            "filename": archive_name,
            "path": str(archive_path),
            "size_bytes": archive_size,
            "sha256": archive_sha256,
            "created_at": utc_now().isoformat(),
            "operator": operator_username,
            "compliance_remark": compliance_remark or "Automated periodic audit archive for legal preservation",
            "files_included": [f.name for f in files_to_pack],
            "verified": True,
        }

        # Update manifest
        manifest = self._load_manifest()
        manifest["archives"].insert(0, entry)

        # Enforce retention policy
        retention = retention_days or getattr(settings, "AUDIT_LOG_RETENTION_DAYS", 90)
        self._prune_expired_backups(manifest, retention)
        self._save_manifest(manifest)

        logger.info(
            f"Created legal audit backup archive '{archive_name}' (SHA-256: {archive_sha256[:16]}...)"
        )
        return entry

    def _prune_expired_backups(self, manifest: Dict[str, Any], retention_days: int) -> None:
        """Prune backup files exceeding retention threshold."""
        cutoff = utc_now() - timedelta(days=retention_days)
        surviving = []
        for arch in manifest.get("archives", []):
            try:
                created_dt = datetime.fromisoformat(arch["created_at"])
                if created_dt < cutoff:
                    target_file = self.backup_dir / arch["filename"]
                    if target_file.exists():
                        target_file.unlink()
                        logger.info(f"Pruned expired audit archive: {arch['filename']}")
                else:
                    surviving.append(arch)
            except Exception:
                surviving.append(arch)
        manifest["archives"] = surviving

    def list_backups(self) -> List[Dict[str, Any]]:
        """List all audit archives with live on-disk integrity checks."""
        manifest = self._load_manifest()
        archives = manifest.get("archives", [])
        result = []

        for arch in archives:
            item = dict(arch)
            target_path = self.backup_dir / arch["filename"]
            if target_path.exists():
                item["exists_on_disk"] = True
                item["actual_size_bytes"] = target_path.stat().st_size
                # Verify checksum consistency
                current_sha = self._calculate_sha256(target_path)
                item["integrity_verified"] = current_sha == arch["sha256"]
            else:
                item["exists_on_disk"] = False
                item["integrity_verified"] = False
            result.append(item)

        return result

    def verify_backup(self, filename: str) -> Dict[str, Any]:
        """Verify an archive against the cryptographic manifest."""
        manifest = self._load_manifest()
        entry = next((a for a in manifest.get("archives", []) if a["filename"] == filename), None)
        target_path = self.backup_dir / filename

        if not target_path.exists():
            return {
                "filename": filename,
                "verified": False,
                "error": "File not found on disk",
            }

        actual_sha = self._calculate_sha256(target_path)
        expected_sha = entry["sha256"] if entry else None

        return {
            "filename": filename,
            "manifest_entry_found": entry is not None,
            "expected_sha256": expected_sha,
            "actual_sha256": actual_sha,
            "verified": actual_sha == expected_sha,
            "size_bytes": target_path.stat().st_size,
            "verified_at": utc_now().isoformat(),
        }


audit_backup_manager = AuditBackupManager()
