"""Administrative area (declarative CRUD + prompt operations).

Access is gated by :func:`require_admin` and every query runs with the superuser
service token so admins can inspect all workspaces. UI visibility is never the
authorization boundary — these dependencies enforce it server-side.
"""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any, cast

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import HTMLResponse

from app.admin.registry import (
    CATEGORY_TITLES,
    RESOURCES,
    AdminField,
    AdminResource,
    get_resource,
)
from app.api.dependencies import AdminReposDep, AdminUser, CsrfProtected
from app.api.repositories import Repositories
from app.exceptions import NotFoundError, ValidationError
from app.observability.metrics import metrics
from app.schemas.prompts import PromptStatus
from app.web.templating import render

router = APIRouter(prefix="/admin", tags=["admin"])

_READONLY = "readonly"


def _repo_for(resource: AdminResource, repos: Repositories) -> Any:
    return getattr(repos, resource.repo)


async def _get_record(resource: AdminResource, repos: Repositories, record_id: str) -> Any:
    try:
        record = await _repo_for(resource, repos).get(record_id)
    except NotFoundError as exc:
        raise NotFoundError("Record not found.") from exc
    return record


def _parse_field(field: AdminField, form: Any) -> Any:
    present = field.name in form
    raw = form.get(field.name)
    if field.kind == "bool":
        return str(raw).lower() in ("1", "true", "on", "yes") if present else False
    if field.kind in ("text", "textarea", "select", "relation"):
        text = raw.strip() if isinstance(raw, str) else ""
        if not text:
            if field.required:
                raise ValidationError(f"{field.label} is required.")
            return None
        return text
    if field.kind in ("int", "float"):
        if raw in (None, ""):
            if field.required:
                raise ValidationError(f"{field.label} is required.")
            return None
        try:
            return int(raw) if field.kind == "int" else float(raw)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{field.label} must be a number.") from exc
    if field.kind == "json":
        if raw in (None, ""):
            if field.required:
                raise ValidationError(f"{field.label} is required.")
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{field.label} must be valid JSON.") from exc
    return None


def _payload(resource: AdminResource, form: Any) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for field in resource.fields:
        if field.kind == _READONLY:
            continue
        value = _parse_field(field, form)
        if value is not None or field.kind == "bool":
            data[field.name] = value
    return data


def _display_values(resource: AdminResource, record: Any | None) -> dict[str, Any]:
    values: dict[str, Any] = {}
    dump = record.model_dump() if record is not None else {}
    for field in resource.fields:
        value = dump.get(field.name)
        if field.kind == "json" and value not in (None, "", {}):
            values[field.name] = json.dumps(value, indent=2, ensure_ascii=False)
        elif field.kind == "bool":
            values[field.name] = bool(value)
        else:
            values[field.name] = "" if value is None else value
    return values


async def _relation_options(
    resource: AdminResource, repos: Repositories
) -> dict[str, list[tuple[str, str]]]:
    options: dict[str, list[tuple[str, str]]] = {}
    relation_fields = [f for f in resource.fields if f.kind == "relation" and f.relation]
    targets = [get_resource(f.relation) for f in relation_fields]  # type: ignore[arg-type]

    async def _fetch(target: AdminResource | None) -> list[Any]:
        if target is None:
            return []
        return cast("list[Any]", await _repo_for(target, repos).list(per_page=500))

    lists = await asyncio.gather(*(_fetch(target) for target in targets))
    for field, target, records in zip(relation_fields, targets, lists, strict=True):
        if target is None:
            options[field.name] = []
            continue
        rendered: list[tuple[str, str]] = []
        for record in records:
            label_value = getattr(record, target.label, None)
            label = str(label_value) if label_value not in (None, "") else record.id
            rendered.append((record.id, label))
        options[field.name] = sorted(rendered, key=lambda item: item[1].lower())
    return options


@router.get("")
@router.get("/")
async def admin_hub(request: Request, admin: AdminUser, repos: AdminReposDep) -> Response:
    grouped: dict[str, list[AdminResource]] = {}
    for resource in RESOURCES:
        if resource.hidden:
            continue
        grouped.setdefault(resource.category, []).append(resource)
    catalog = [
        {"key": key, "title": CATEGORY_TITLES.get(key, key.title()), "resources": items}
        for key, items in grouped.items()
    ]
    return render(request, "pages/admin/hub.html", {"admin": admin, "catalog": catalog})


@router.get("/metrics")
async def admin_metrics(request: Request, admin: AdminUser) -> Response:
    snapshot = metrics.snapshot()
    return render(
        request,
        "pages/admin/metrics.html",
        {"counters": snapshot["counters"], "gauges": snapshot["gauges"]},
    )


@router.get("/prompt-versions/compare")
async def compare_prompt_versions(
    request: Request,
    admin: AdminUser,
    repos: AdminReposDep,
    left: str = "",
    right: str = "",
) -> Response:
    left_version = await repos.prompt_versions.get(left) if left else None
    right_version = await repos.prompt_versions.get(right) if right else None
    versions = await repos.prompt_versions.list(per_page=500, sort="-created")
    return render(
        request,
        "pages/admin/prompt_compare.html",
        {"left": left_version, "right": right_version, "versions": versions},
    )


@router.get("/{slug}")
async def resource_list(
    request: Request, slug: str, admin: AdminUser, repos: AdminReposDep
) -> Response:
    resource = _require(slug)
    records = await _repo_for(resource, repos).list(
        filter=resource.default_filter, sort=resource.order, per_page=200
    )
    return render(
        request,
        "pages/admin/resource_list.html",
        {
            "resource": resource,
            "records": records,
            "rows": [
                {"record": record, "values": _display_values(resource, record)}
                for record in records
            ],
        },
    )


@router.get("/{slug}/new")
async def resource_new(
    request: Request, slug: str, admin: AdminUser, repos: AdminReposDep
) -> Response:
    resource = _require(slug)
    if not resource.can_create:
        raise NotFoundError("This resource cannot be created.")
    return render(
        request,
        "pages/admin/resource_form.html",
        {
            "resource": resource,
            "record": None,
            "values": _display_values(resource, None),
            "relation_options": await _relation_options(resource, repos),
            "error": None,
        },
    )


@router.post("/{slug}")
async def resource_create(
    request: Request,
    slug: str,
    admin: AdminUser,
    repos: AdminReposDep,
    _csrf: CsrfProtected,
) -> Response:
    resource = _require(slug)
    if not resource.can_create:
        raise NotFoundError("This resource cannot be created.")
    form = await request.form()
    try:
        data = _payload(resource, form)
        await _repo_for(resource, repos).create(data)
    except ValidationError as exc:
        return render(
            request,
            "pages/admin/resource_form.html",
            {
                "resource": resource,
                "record": None,
                "values": dict(form),
                "relation_options": await _relation_options(resource, repos),
                "error": exc.message,
            },
            status_code=422,
        )
    return _redirect(f"/admin/{slug}")


@router.get("/{slug}/{record_id}/edit")
async def resource_edit(
    request: Request, slug: str, record_id: str, admin: AdminUser, repos: AdminReposDep
) -> Response:
    resource = _require(slug)
    record = await _get_record(resource, repos, record_id)
    return render(
        request,
        "pages/admin/resource_form.html",
        {
            "resource": resource,
            "record": record,
            "values": _display_values(resource, record),
            "relation_options": await _relation_options(resource, repos),
            "error": None,
        },
    )


@router.post("/{slug}/{record_id}")
async def resource_update(
    request: Request,
    slug: str,
    record_id: str,
    admin: AdminUser,
    repos: AdminReposDep,
    _csrf: CsrfProtected,
) -> Response:
    resource = _require(slug)
    if not resource.can_update:
        raise NotFoundError("This resource cannot be edited.")
    form = await request.form()
    try:
        data = _payload(resource, form)
        await _repo_for(resource, repos).update(record_id, data)
    except ValidationError as exc:
        record = await _get_record(resource, repos, record_id)
        return render(
            request,
            "pages/admin/resource_form.html",
            {
                "resource": resource,
                "record": record,
                "values": dict(form),
                "relation_options": await _relation_options(resource, repos),
                "error": exc.message,
            },
            status_code=422,
        )
    return _redirect(f"/admin/{slug}")


@router.post("/{slug}/{record_id}/delete")
async def resource_delete(
    request: Request,
    slug: str,
    record_id: str,
    admin: AdminUser,
    repos: AdminReposDep,
    _csrf: CsrfProtected,
) -> Response:
    resource = _require(slug)
    if not resource.can_delete:
        raise NotFoundError("This resource cannot be deleted.")
    await _repo_for(resource, repos).delete(record_id)
    return HTMLResponse("")


# -- prompt version operations ---------------------------------------------
@router.post("/prompt-versions/{version_id}/activate")
async def activate_prompt_version(
    request: Request,
    version_id: str,
    admin: AdminUser,
    repos: AdminReposDep,
    _csrf: CsrfProtected,
) -> Response:
    version = await repos.prompt_versions.get(version_id)
    siblings = await repos.prompt_versions.list(
        filter=f'template = "{version.template}"', per_page=500
    )
    for sibling in siblings:
        target = PromptStatus.ACTIVE if sibling.id == version.id else PromptStatus.ARCHIVED
        if sibling.status != target:
            await repos.prompt_versions.update(sibling.id, {"status": target.value})
    return _redirect("/admin/prompt-versions")


@router.post("/prompt-versions/{version_id}/archive")
async def archive_prompt_version(
    request: Request,
    version_id: str,
    admin: AdminUser,
    repos: AdminReposDep,
    _csrf: CsrfProtected,
) -> Response:
    await repos.prompt_versions.update(version_id, {"status": PromptStatus.ARCHIVED.value})
    return _redirect("/admin/prompt-versions")


@router.get("/prompt-templates/{template_id}/new-version")
async def new_prompt_version_form(
    request: Request, template_id: str, admin: AdminUser, repos: AdminReposDep
) -> Response:
    template = await repos.prompt_templates.get(template_id)
    next_version = await repos.prompt_versions.next_version_number(template.id)
    return render(
        request,
        "pages/admin/prompt_new_version.html",
        {"template": template, "next_version": next_version},
    )


@router.post("/prompt-templates/{template_id}/new-version")
async def create_prompt_version(
    request: Request,
    template_id: str,
    admin: AdminUser,
    repos: AdminReposDep,
    body: Annotated[str, Form()],
    _csrf: CsrfProtected = None,
    notes: Annotated[str, Form()] = "",
    status: Annotated[str, Form()] = PromptStatus.DRAFT.value,
) -> Response:
    template = await repos.prompt_templates.get(template_id)
    next_version = await repos.prompt_versions.next_version_number(template.id)
    await repos.prompt_versions.create(
        {
            "template": template.id,
            "version": next_version,
            "body": body,
            "status": status,
            "notes": notes or None,
        }
    )
    return _redirect("/admin/prompt-templates")


def _require(slug: str) -> AdminResource:
    resource = get_resource(slug)
    if resource is None:
        raise NotFoundError("Unknown admin resource.")
    return resource


def _redirect(location: str) -> Response:
    response = Response(status_code=200)
    response.headers["HX-Redirect"] = location
    return response
