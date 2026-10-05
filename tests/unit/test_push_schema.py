"""Schema-sync ordering and relation remapping logic."""

from __future__ import annotations

from typing import Any

from scripts.push_schema import _clean_fields, order_collections


def _collection(name: str, rel_targets: list[str], *, self_target: bool = False) -> dict[str, Any]:
    fields = [
        {"type": "relation", "name": f"rel_{index}", "collectionId": target}
        for index, target in enumerate(rel_targets)
    ]
    if self_target:
        fields.append({"type": "relation", "name": "parent", "collectionId": f"id-{name}"})
    return {
        "id": f"id-{name}",
        "name": name,
        "type": "base",
        "fields": fields,
        "indexes": [],
        "rules": {},
    }


def test_dependencies_are_created_first() -> None:
    documents = _collection("documents", ["id-workspaces"])
    workspaces = _collection("workspaces", [])
    sections = _collection("document_sections", ["id-documents"])
    ordered = [c["name"] for c in order_collections([sections, documents, workspaces])]
    assert ordered.index("workspaces") < ordered.index("documents")
    assert ordered.index("documents") < ordered.index("document_sections")


def test_self_relation_deferred_until_second_pass() -> None:
    collection = _collection("document_sections", ["id-documents"], self_target=True)
    name_by_id = {"id-documents": "documents", "id-document_sections": "document_sections"}
    id_by_name = {"documents": "remote-documents", "document_sections": "remote-sections"}

    first_pass = _clean_fields(collection, name_by_id, id_by_name, include_self_relations=False)
    assert not any(field["name"] == "parent" for field in first_pass)

    second_pass = _clean_fields(collection, name_by_id, id_by_name, include_self_relations=True)
    parent = next(field for field in second_pass if field["name"] == "parent")
    assert parent["collectionId"] == "remote-sections"


def test_relation_targets_are_remapped_to_target_ids() -> None:
    collection = _collection("documents", ["id-workspaces"])
    name_by_id = {"id-workspaces": "workspaces"}
    id_by_name = {"workspaces": "remote-ws"}
    fields = _clean_fields(collection, name_by_id, id_by_name, include_self_relations=False)
    assert fields[0]["collectionId"] == "remote-ws"


def test_system_fields_are_stripped() -> None:
    collection = _collection("workspaces", [])
    collection["fields"].append({"type": "text", "name": "id", "system": True})
    fields = _clean_fields(collection, {}, {}, include_self_relations=False)
    assert all(field["name"] != "id" for field in fields)
