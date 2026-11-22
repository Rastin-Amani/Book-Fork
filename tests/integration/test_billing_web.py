"""Billing web flow: managed jobs wait for payment, free allowance queues them.

Billing is enabled here with a dummy Gumroad config; no Gumroad request is made
unless a test deliberately triggers an API lookup.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from app.config import Settings
from app.main import create_app
from app.repositories.pocketbase import PocketBaseClient
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tests.documents_fixtures import write_epub
from tests.integration.test_e2e_flow import _seed_policy
from tests.integration.test_web import FakeAuthProvider

WEBHOOK_SECRET = "test-callback-secret-with-enough-entropy"


def _billing_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "billing_enabled": True,
            "payment_provider": "gumroad",
            "gumroad_access_token": SecretStr("test-gumroad-token"),
            "gumroad_webhook_secret": SecretStr(WEBHOOK_SECRET),
            "gumroad_product_id": "prod-test",
            "gumroad_product_permalink": "book-fork",
            "pocketbase_service_credential": SecretStr("test-service-token"),
        }
    )


def _login(client: TestClient, app: Any, fake_pb: Any) -> str:
    app.state.ctx.pocketbase = PocketBaseClient("http://pb", client=fake_pb.client())
    app.state.ctx.auth = FakeAuthProvider()
    # Billing writes use the service credential; the fake PocketBase does not
    # authenticate, so a cached token is enough for these tests.
    app.state.ctx._service_token = "test-service-token"
    client.get("/login")
    csrf = client.cookies.get("book_fork_csrf") or ""
    client.get("/auth/oauth2/callback?code=good-code&state=st-google", follow_redirects=False)
    return csrf


def _upload(client: TestClient, csrf: str, connection_id: str, tmp_path: Path) -> Any:
    epub_bytes = write_epub(tmp_path / "book.epub").read_bytes()
    return client.post(
        "/app/translations",
        data={
            "source_language": "en",
            "target_language": "fa",
            "connection_id": connection_id,
            "quality_mode": "balanced",
        },
        files={"upload": ("book.epub", epub_bytes, "application/epub+zip")},
        headers={"X-CSRF-Token": csrf},
    )


def test_managed_job_waits_for_payment(settings: Settings, fake_pb: Any, tmp_path: Path) -> None:
    app = create_app(_billing_settings(settings))
    connection_id = _seed_policy(fake_pb)
    with TestClient(app) as client:
        csrf = _login(client, app, fake_pb)
        assert client.get("/app").status_code == 200

        response = _upload(client, csrf, connection_id, tmp_path)

        assert response.status_code == 200
        assert response.headers["HX-Redirect"].startswith("/app/settings/billing/invoices/")
        job = next(iter(fake_pb.collections["translation_jobs"].values()))
        assert job["status"] == "awaiting_payment"
        invoice = next(iter(fake_pb.collections["billing_invoices"].values()))
        assert invoice["status"] == "pending"
        assert invoice["amount"] == 7.0
        assert invoice["correlation_token"]

        page = client.get(response.headers["HX-Redirect"])
        assert page.status_code == 200
        assert "Continue to payment" in page.text
        assert "Payment required" in client.get(f"/app/translations/{job['id']}").text


def test_free_allowance_queues_the_job_immediately(
    settings: Settings, fake_pb: Any, tmp_path: Path
) -> None:
    fake_pb.seed(
        "system_settings",
        {"key": "billing.free_managed_books", "type": "int", "value": 1},
    )
    app = create_app(_billing_settings(settings))
    connection_id = _seed_policy(fake_pb)
    with TestClient(app) as client:
        csrf = _login(client, app, fake_pb)
        assert client.get("/app").status_code == 200

        response = _upload(client, csrf, connection_id, tmp_path)

        assert response.headers["HX-Redirect"].startswith("/app/translations/")
        job = next(iter(fake_pb.collections["translation_jobs"].values()))
        assert job["status"] == "queued"
        invoice = next(iter(fake_pb.collections["billing_invoices"].values()))
        assert invoice["status"] == "paid"
        assert invoice["provider"] == "free"
        assert len(fake_pb.collections["billing_free_claims"]) == 1

        billing = client.get("/app/settings/billing")
        assert billing.status_code == 200
        assert "Free managed allowance" in billing.text


def test_invoice_page_hides_another_workspaces_invoice(
    settings: Settings, fake_pb: Any, tmp_path: Path
) -> None:
    app = create_app(_billing_settings(settings))
    connection_id = _seed_policy(fake_pb)
    with TestClient(app) as client:
        csrf = _login(client, app, fake_pb)
        response = _upload(client, csrf, connection_id, tmp_path)
        assert response.headers["HX-Redirect"].startswith("/app/settings/billing/invoices/")

        foreign = fake_pb.seed(
            "billing_invoices",
            {
                "workspace": "someone-else",
                "reference": "BF-FOREIGN",
                "product_type": "managed_book",
                "product_name": "Foreign book",
                "amount": 7.0,
                "currency": "USD",
                "status": "pending",
                "provider": "none",
            },
        )
        page = client.get(f"/app/settings/billing/invoices/{foreign['id']}")
        assert page.status_code == 404


def test_webhook_requires_the_local_callback_secret(settings: Settings, fake_pb: Any) -> None:
    app = create_app(_billing_settings(settings))
    with TestClient(app) as client:
        _login(client, app, fake_pb)
        body = urlencode({"sale_id": "sale-1", "product_id": "prod-test"}).encode()

        forged = client.post(
            "/api/webhooks/gumroad",
            content=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert forged.status_code == 401
        assert "billing_events" not in fake_pb.collections

        wrong = client.post(
            "/api/webhooks/gumroad?secret=wrong",
            content=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert wrong.status_code == 401
        assert "billing_events" not in fake_pb.collections


def test_webhook_records_a_valid_but_unknown_delivery(settings: Settings, fake_pb: Any) -> None:
    app = create_app(_billing_settings(settings))
    with TestClient(app) as client:
        _login(client, app, fake_pb)
        body = urlencode(
            {"sale_id": "sale-1", "product_id": "prod-test", "resource_name": "sale"}
        ).encode()

        response = client.post(
            f"/api/webhooks/gumroad?secret={WEBHOOK_SECRET}",
            content=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        # Authenticated and well-formed, but no invoice matches: acknowledged
        # and kept as an operational event, never fulfilled.
        assert response.status_code == 200
        event = next(iter(fake_pb.collections["billing_events"].values()))
        assert event["event_key"] == "sale:sale-1"
        assert event["processed"] is True


def test_webhook_rejects_json_and_oversized_payloads(settings: Settings, fake_pb: Any) -> None:
    app = create_app(_billing_settings(settings))
    with TestClient(app) as client:
        _login(client, app, fake_pb)
        json_response = client.post(
            "/api/webhooks/gumroad",
            json={"sale_id": "sale-1"},
        )
        assert json_response.status_code == 415

        oversized = client.post(
            f"/api/webhooks/gumroad?secret={WEBHOOK_SECRET}",
            content=b"x" * (300 * 1024),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert oversized.status_code == 413
