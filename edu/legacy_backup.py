"""Run inside the legacy API container to make a read-only migration archive.

Example: python /tmp/legacy_backup.py /app/reports/weknora-backup-<timestamp>
Requires sibling migration.py. Never removes or updates legacy data.
"""
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

# A script launched from /tmp has /tmp (not the API workdir) on sys.path.
sys.path.insert(0, "/app")
from backend.app.config import get_settings
import migration


def main():
    root = Path(sys.argv[1]).resolve()
    parent = Path("/app/reports").resolve()
    if parent not in root.parents or not root.name.startswith("weknora-backup-"):
        raise ValueError("Backup target must be a new weknora-backup directory under /app/reports")
    root.mkdir(mode=0o700, exist_ok=False)
    settings = get_settings()
    with migration.source_connection(settings.database_url) as (connection, kind):
        snapshot = migration.export_snapshot(connection, kind)
    migration.validate_snapshot(snapshot)
    migration.save_json(root / "legacy.json", snapshot)
    # Copy file versions and rule images sequentially, including soft-deleted data.
    references = {}
    for version in snapshot["tables"]["document_versions"]:
        references[version["object_key"]] = version.get("checksum_sha256")
        if version.get("preview_object_key"):
            references.setdefault(version["preview_object_key"], None)
    for rule in snapshot["tables"]["rules"]:
        if rule.get("image_object_key"):
            references.setdefault(rule["image_object_key"], None)
    store = None
    if settings.storage_backend == "minio":
        from minio import Minio
        store = Minio(settings.minio_endpoint, access_key=settings.minio_access_key,
                      secret_key=settings.minio_secret_key, secure=settings.minio_secure)
    assets = []
    for index, (key, expected_hash) in enumerate(sorted(references.items()), 1):
        target = root / "assets" / (sha256(key.encode()).hexdigest() + ".bin")
        target.parent.mkdir(mode=0o700, exist_ok=True)
        digest = sha256()
        count = 0
        try:
            if store:
                response = store.get_object(settings.minio_bucket, key)
            else:
                local_root = Path(settings.local_storage_path).resolve()
                source = (local_root / key).resolve()
                if local_root not in source.parents:
                    raise ValueError("Unsafe legacy file path")
                response = source.open("rb")
            try:
                descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as output:
                    while data := response.read(1024 * 1024):
                        digest.update(data)
                        output.write(data)
                        count += len(data)
            finally:
                response.close()
                if hasattr(response, "release_conn"):
                    response.release_conn()
            actual = digest.hexdigest()
            status = "ok" if not expected_hash or expected_hash == actual else "checksum_mismatch"
            assets.append({"object_key": key, "backup_file": str(target.relative_to(root)),
                           "sha256": actual, "bytes": count, "status": status})
        except Exception as error:
            assets.append({"object_key": key, "status": "unavailable", "error_type": type(error).__name__})
        print(json.dumps({"asset": index, "total": len(references), "status": assets[-1]["status"]}), flush=True)
    migration.save_json(root / "assets.json", {"schema_version": 1, "assets": assets})
    migration.save_json(root / "inventory.json", migration.inventory(snapshot))
    unavailable = sum(asset["status"] != "ok" for asset in assets)
    print(json.dumps({"backup_complete": unavailable == 0, "assets": len(assets), "unavailable": unavailable}), flush=True)
    if unavailable:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
