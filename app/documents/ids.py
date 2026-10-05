"""Deterministic, stable identity for canonical document nodes."""

from __future__ import annotations


def section_id(order: int) -> str:
    return f"section_{order:03d}"


def block_id(order: int) -> str:
    return f"block_{order:04d}"


def asset_id(order: int) -> str:
    return f"asset_{order:04d}"


def make_id(prefix: str, order: int) -> str:
    return f"{prefix}_{order:04d}"
