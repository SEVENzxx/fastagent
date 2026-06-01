from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import operations_service, webhook_processor


@pytest.fixture
def platform():
    return SimpleNamespace(id=5, tenant_id=8)


@pytest.fixture
def message():
    return SimpleNamespace(external_userid="customer-1", msg_id="msg-1")


@pytest.mark.asyncio
async def test_process_wecom_message_routes_successfully(monkeypatch, platform, message):
    route = AsyncMock()
    monkeypatch.setattr(webhook_processor, "route_wecom_message", route)

    await webhook_processor.process_wecom_message(AsyncMock(), platform, message)

    route.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_wecom_message_creates_notification_on_failure(
    monkeypatch, platform, message
):
    route = AsyncMock(side_effect=RuntimeError("channel offline"))
    create_notification = AsyncMock()
    monkeypatch.setattr(webhook_processor, "route_wecom_message", route)
    monkeypatch.setattr(operations_service, "create_notification", create_notification)
    db = AsyncMock()

    await webhook_processor.process_wecom_message(db, platform, message)

    create_notification.assert_awaited_once()
    assert create_notification.await_args.kwargs["type"] == "channel_error"
    assert create_notification.await_args.kwargs["tenant_id"] == 8
    assert create_notification.await_args.kwargs["resource_id"] == 5
