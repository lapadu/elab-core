#!/usr/bin/env python3
"""Enforce apiVersion bumps when ManifestSchema changes.

Usage:
  python tools/check_manifest_api_version.py
  python tools/check_manifest_api_version.py --update
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def parse_semver(version: str) -> tuple[int, int, int] | None:
    parts = version.split(".")
    if len(parts) != 3:
        return None
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None


def canonical_hash(data: Any) -> str:
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check ManifestSchema apiVersion bump")
    parser.add_argument("--update", action="store_true", help="Update lock file to current schema")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    schema_path = repo_root / "schemas" / "ManifestSchema.json"
    lock_path = repo_root / "schemas" / "ManifestSchema.api-lock.json"

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    properties = schema.get("properties", {})
    api_version = properties.get("apiVersion", {}).get("default")
    if not isinstance(api_version, str) or not api_version:
        print("[manifest-api-check] ERROR: properties.apiVersion.default must be a non-empty string.")
        return 2

    schema_hash = canonical_hash(schema)
    lock_data = {
        "schemaFile": "schemas/ManifestSchema.json",
        "apiVersion": api_version,
        "schemaHash": schema_hash,
    }

    if args.update:
        lock_path.write_text(json.dumps(lock_data, indent=2) + "\n", encoding="utf-8")
        print(f"[manifest-api-check] lock updated: {lock_path.relative_to(repo_root)}")
        return 0

    if not lock_path.exists():
        print("[manifest-api-check] ERROR: lock file missing.")
        print("[manifest-api-check] Run: python tools/check_manifest_api_version.py --update")
        return 2

    previous = json.loads(lock_path.read_text(encoding="utf-8"))
    old_hash = previous.get("schemaHash", "")
    old_api_version = previous.get("apiVersion", "")

    if schema_hash == old_hash:
        print("[manifest-api-check] OK: schema unchanged.")
        return 0

    if api_version == old_api_version:
        print("[manifest-api-check] ERROR: schema changed but apiVersion was not bumped.")
        print(f"[manifest-api-check] old apiVersion={old_api_version}, current apiVersion={api_version}")
        return 1

    old_semver = parse_semver(str(old_api_version))
    new_semver = parse_semver(str(api_version))
    if old_semver and new_semver and new_semver <= old_semver:
        print("[manifest-api-check] ERROR: apiVersion must increase when schema changes.")
        print(f"[manifest-api-check] old apiVersion={old_api_version}, current apiVersion={api_version}")
        return 1

    print("[manifest-api-check] OK: schema changed and apiVersion was bumped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
