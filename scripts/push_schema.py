"""Push the validated PocketBase schema to a remote instance via the Admin API.

PocketBase migrations only run inside the server process, so a remote instance
that cannot run this repository's migrations needs its schema applied through
the Admin API. This script reads the collections from a locally-migrated
``data.db`` and recreates them on a target instance.

Usage::

    uv run python scripts/push_schema.py \
        --source-db /path/to/pb_data/data.db \
        --target-url https://example.com \
        --identity admin@example.com --password secret

Order of operations: collections are created in dependency order with permissive
(no) rules, then a second pass restores relation fields that reference the
collection itself (e.g. ``document_sections.parent``) and the real API rules.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from typing import Any

import httpx

SKIP_COLLECTIONS = {"users"}
SKIP_PREFIX = "_"


def load_collections(db_path: str) -> list[dict[str, Any]]:
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            "select id, type, name, fields, indexes, "
            "listRule, viewRule, createRule, updateRule, deleteRule from _collections"
        ).fetchall()
    finally:
        connection.close()

    collections: list[dict[str, Any]] = []
    for (
        coll_id,
        coll_type,
        name,
        fields,
        indexes,
        list_rule,
        view_rule,
        create_rule,
        update_rule,
        delete_rule,
    ) in rows:
        if name.startswith(SKIP_PREFIX):
            continue
        collections.append(
            {
                "id": coll_id,
                "type": coll_type,
                "name": name,
                "fields": json.loads(fields),
                "indexes": json.loads(indexes or "[]"),
                "rules": {
                    "listRule": list_rule,
                    "viewRule": view_rule,
                    "createRule": create_rule,
                    "updateRule": update_rule,
                    "deleteRule": delete_rule,
                },
            }
        )
    return collections


def _relation_targets(collection: dict[str, Any], name_by_id: dict[str, str]) -> set[str]:
    targets: set[str] = set()
    for field in collection["fields"]:
        if field.get("type") == "relation" and field.get("collectionId"):
            target = name_by_id.get(field["collectionId"])
            if target and target != collection["name"]:
                targets.add(target)
    return targets


def order_collections(collections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    name_by_id = {c["id"]: c["name"] for c in collections}
    by_name = {c["name"]: c for c in collections}
    remaining = set(by_name)
    ordered: list[dict[str, Any]] = []
    while remaining:
        ready = [
            name
            for name in remaining
            if (_relation_targets(by_name[name], name_by_id) & remaining) == set()
        ]
        if not ready:
            # Cyclic relation graph: fall back to arbitrary order; self-relations
            # are handled in the second pass regardless.
            ready = sorted(remaining)
        for name in sorted(ready):
            ordered.append(by_name[name])
            remaining.discard(name)
    return ordered


def _clean_fields(
    collection: dict[str, Any],
    name_by_id: dict[str, str],
    id_by_name: dict[str, str],
    *,
    include_self_relations: bool,
) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for field in collection["fields"]:
        if field.get("system"):
            continue
        copied = {k: v for k, v in field.items() if k != "id"}
        if copied.get("type") == "relation" and copied.get("collectionId"):
            target_name = name_by_id.get(copied["collectionId"])
            if target_name == collection["name"]:
                if not include_self_relations:
                    continue
                copied["collectionId"] = id_by_name[collection["name"]]
            elif target_name and target_name in id_by_name:
                copied["collectionId"] = id_by_name[target_name]
        fields.append(copied)
    return fields


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", required=True)
    parser.add_argument("--target-url", required=True)
    parser.add_argument("--identity", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    collections = load_collections(args.source_db)
    name_by_id = {c["id"]: c["name"] for c in collections}
    pushable = [c for c in collections if c["name"] not in SKIP_COLLECTIONS]
    ordered = order_collections(pushable)

    if args.dry_run:
        print("Order:", [c["name"] for c in ordered])
        return 0

    base = args.target_url.rstrip("/")
    with httpx.Client(base_url=base, timeout=30.0) as client:
        auth = client.post(
            "/api/collections/_superusers/auth-with-password",
            json={"identity": args.identity, "password": args.password},
        )
        auth.raise_for_status()
        token = auth.json()["token"]
        client.headers["Authorization"] = token

        existing = client.get("/api/collections", params={"perPage": 200})
        existing.raise_for_status()
        id_by_name = {item["name"]: item["id"] for item in existing.json()["items"]}

        # Pass 1: create missing collections with no rules.
        for collection in ordered:
            if collection["name"] in id_by_name:
                continue
            payload = {
                "type": collection["type"],
                "name": collection["name"],
                "fields": _clean_fields(
                    collection, name_by_id, id_by_name, include_self_relations=False
                ),
                "indexes": collection["indexes"],
                "listRule": None,
                "viewRule": None,
                "createRule": None,
                "updateRule": None,
                "deleteRule": None,
            }
            response = client.post("/api/collections", json=payload)
            if response.status_code >= 400:
                print(f"FAILED create {collection['name']}: {response.text}", file=sys.stderr)
                return 1
            id_by_name[collection["name"]] = response.json()["id"]
            print(f"created {collection['name']}")

        # Pass 2: restore self-relations and real rules.
        for collection in ordered:
            coll_id = id_by_name[collection["name"]]
            payload = {
                "fields": _clean_fields(
                    collection, name_by_id, id_by_name, include_self_relations=True
                ),
                **collection["rules"],
            }
            response = client.patch(f"/api/collections/{coll_id}", json=payload)
            if response.status_code >= 400:
                print(f"FAILED update {collection['name']}: {response.text}", file=sys.stderr)
                return 1
            print(f"updated {collection['name']}")

    print("schema push complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
