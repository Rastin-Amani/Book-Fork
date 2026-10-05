"""Minimal in-memory PocketBase fake for hermetic repository/service tests.

Supports the subset of the REST API and filter grammar the repositories use:
equality comparisons with ``&&``/``||``/parentheses, dotted field access, and
``sort``/``page``/``perPage`` query params.
"""

from __future__ import annotations

import json
import re
from functools import partial
from typing import Any
from urllib.parse import parse_qs

import httpx

_TOKEN_RE = re.compile(
    r'\s*(?:(?P<str>"(?:\\.|[^"\\])*")|(?P<op>&&|\|\||<=|>=|!=|\(|\)|<|>|=)|'
    r"(?P<value>true|false|null|-?\d+(?:\.\d+)?)|(?P<field>[A-Za-z_][A-Za-z0-9_.]*))"
)

_COMPARISON_OPS = {"=", "!=", "<", ">", "<=", ">="}


class _Parser:
    def __init__(self, expression: str) -> None:
        self._tokens = self._tokenize(expression)
        self._index = 0

    @staticmethod
    def _tokenize(expression: str) -> list[tuple[str, str]]:
        tokens: list[tuple[str, str]] = []
        pos = 0
        while pos < len(expression):
            match = _TOKEN_RE.match(expression, pos)
            if not match or match.end() == pos:
                pos += 1
                continue
            pos = match.end()
            kind = match.lastgroup or "field"
            tokens.append((kind, match.group(kind)))
        return tokens

    def parse(self, record: dict[str, Any]) -> bool:
        return self._or(record)

    def _peek(self) -> tuple[str, str] | None:
        return self._tokens[self._index] if self._index < len(self._tokens) else None

    def _next(self) -> tuple[str, str]:
        token = self._tokens[self._index]
        self._index += 1
        return token

    def _or(self, record: dict[str, Any]) -> bool:
        value = self._and(record)
        while self._peek() == ("op", "||"):
            self._next()
            value = self._and(record) or value
        return value

    def _and(self, record: dict[str, Any]) -> bool:
        value = self._primary(record)
        while self._peek() == ("op", "&&"):
            self._next()
            value = self._primary(record) and value
        return value

    def _primary(self, record: dict[str, Any]) -> bool:
        token = self._peek()
        if token == ("op", "("):
            self._next()
            value = self._or(record)
            if self._peek() == ("op", ")"):
                self._next()
            return value
        return self._comparison(record)

    def _comparison(self, record: dict[str, Any]) -> bool:
        field_token = self._next()
        if field_token[0] != "field":
            return False
        op_token = self._peek()
        if op_token is None or op_token[0] != "op" or op_token[1] not in _COMPARISON_OPS:
            return False
        operator = op_token[1]
        self._next()
        value_token = self._next()
        actual = self._resolve(record, field_token[1])
        kind, raw = value_token
        if kind == "str":
            expected: Any = raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            left: Any = str(actual if actual is not None else "")
        elif raw == "true":
            return self._apply(operator, bool(actual) is True, True)
        elif raw == "false":
            return self._apply(operator, bool(actual) is False, True)
        elif raw == "null":
            return self._apply(operator, actual in (None, ""), True)
        else:
            try:
                left = float(actual or 0)
                expected = float(raw)
            except TypeError, ValueError:
                return False
        return self._apply(operator, left, expected)

    @staticmethod
    def _apply(operator: str, left: Any, right: Any) -> bool:
        if operator == "=":
            return bool(left == right)
        if operator == "!=":
            return bool(left != right)
        try:
            if operator == "<":
                return bool(left < right)
            if operator == ">":
                return bool(left > right)
            if operator == "<=":
                return bool(left <= right)
            if operator == ">=":
                return bool(left >= right)
        except TypeError:
            return False
        return False

    @staticmethod
    def _resolve(record: dict[str, Any], path: str) -> Any:
        current: Any = record
        for part in path.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current


def _matches(record: dict[str, Any], expression: str | None) -> bool:
    if not expression:
        return True
    return _Parser(expression).parse(record)


def _sort_key(record: dict[str, Any], field: str) -> tuple[bool, Any]:
    value = record.get(field)
    return (value is None, value)


class FakePocketBase:
    """In-memory collection store exposed as an httpx MockTransport handler."""

    def __init__(self) -> None:
        self.collections: dict[str, dict[str, dict[str, Any]]] = {}
        self._counter = 0

    def seed(self, collection: str, record: dict[str, Any]) -> dict[str, Any]:
        self._counter += 1
        stored = {"id": record.get("id") or f"rec{self._counter:04d}", **record}
        stored.setdefault("created", "2026-01-01 00:00:00Z")
        stored.setdefault("updated", "2026-01-01 00:00:00Z")
        self.collections.setdefault(collection, {})[stored["id"]] = stored
        return stored

    def client(self, *, base_url: str = "http://pb") -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self._handle), base_url=base_url)

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        parts = path.strip("/").split("/")
        # /api/collections/{collection}/records[/{id}]
        if len(parts) >= 4 and parts[0] == "api" and parts[1] == "collections":
            collection = parts[2]
            if len(parts) == 4 and parts[3] == "records":
                if request.method == "GET":
                    return self._list(collection, request)
                if request.method == "POST":
                    return self._create(collection, request)
            if len(parts) == 5 and parts[3] == "records":
                record_id = parts[4]
                if request.method == "GET":
                    return self._get(collection, record_id)
                if request.method == "PATCH":
                    return self._update(collection, record_id, request)
                if request.method == "DELETE":
                    return self._delete(collection, record_id)
        return httpx.Response(404, json={"message": "not found", "status": 404})

    def _list(self, collection: str, request: httpx.Request) -> httpx.Response:
        query = parse_qs(request.url.query.decode())
        expression = query.get("filter", [None])[0]
        items = [
            record
            for record in self.collections.get(collection, {}).values()
            if _matches(record, expression)
        ]
        sort = query.get("sort", [None])[0]
        if sort:
            for field in reversed([f.strip() for f in sort.split(",")]):
                reverse = field.startswith("-")
                key = field.lstrip("-")
                items.sort(key=partial(_sort_key, field=key), reverse=reverse)
        per_page = int(query.get("perPage", ["30"])[0])
        page = int(query.get("page", ["1"])[0])
        start = (page - 1) * per_page
        total_pages = max(1, -(-len(items) // per_page))  # ceil division
        return httpx.Response(
            200,
            json={
                "page": page,
                "perPage": per_page,
                "totalItems": len(items),
                "totalPages": total_pages,
                "items": items[start : start + per_page],
            },
        )

    def _get(self, collection: str, record_id: str) -> httpx.Response:
        record = self.collections.get(collection, {}).get(record_id)
        if record is None:
            return httpx.Response(404, json={"message": "missing", "status": 404})
        return httpx.Response(200, json=record)

    def _create(self, collection: str, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content or b"{}")
        record = self.seed(collection, payload)
        return httpx.Response(200, json=record)

    def _update(self, collection: str, record_id: str, request: httpx.Request) -> httpx.Response:
        record = self.collections.get(collection, {}).get(record_id)
        if record is None:
            return httpx.Response(404, json={"message": "missing", "status": 404})
        record.update(json.loads(request.content or b"{}"))
        return httpx.Response(200, json=record)

    def _delete(self, collection: str, record_id: str) -> httpx.Response:
        self.collections.get(collection, {}).pop(record_id, None)
        return httpx.Response(204)
