"""
MCP Notify Server — push notifications via Firebase FCM with graceful degradation.

If Firebase credentials are absent/invalid the server NEVER crashes — it logs
a structured warning and returns a success-shaped response so callers are not
broken.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from pydantic import BaseModel

from core.config import settings
from mcp_servers.base import MCPServer, MCPToolSchema

log = structlog.get_logger(__name__)

# ─────────────────────────────────────────────────────────────
# Firebase Admin SDK — lazy init, fail-safe
# ─────────────────────────────────────────────────────────────

_fcm_app: Any = None  # firebase_admin.App | None


def _get_fcm_messaging():
    """Lazily initialise Firebase Admin and return the messaging module.
    Returns None if credentials are absent or malformed.
    """
    global _fcm_app
    if _fcm_app is not None:
        try:
            import firebase_admin.messaging
            return firebase_admin.messaging
        except ImportError:
            return None

    creds_json = settings.FIREBASE_CREDENTIALS_JSON
    if not creds_json:
        log.warning("firebase.credentials_missing", hint="Set FIREBASE_CREDENTIALS_JSON in .env")
        return None

    try:
        import firebase_admin
        import firebase_admin.credentials
        import firebase_admin.messaging

        cred_dict = json.loads(creds_json)
        cred = firebase_admin.credentials.Certificate(cred_dict)
        _fcm_app = firebase_admin.initialize_app(cred)
        log.info("firebase.initialised")
        return firebase_admin.messaging
    except Exception as exc:  # noqa: BLE001
        log.warning("firebase.init_failed", error=str(exc))
        return None


# ─────────────────────────────────────────────────────────────
# Response models
# ─────────────────────────────────────────────────────────────


class NotifyResult(BaseModel):
    success: bool
    message_id: str | None = None
    channel: str
    recipient: str
    fallback_used: bool = False


class BulkNotifyResult(BaseModel):
    sent: int
    failed: int
    fallback_used: bool = False


class TopicSubscribeResult(BaseModel):
    topic: str
    tokens: list[str]
    success_count: int
    failure_count: int


# ─────────────────────────────────────────────────────────────
# MCP Notify Server
# ─────────────────────────────────────────────────────────────


class NotifyMCPServer(MCPServer):
    tools: dict[str, MCPToolSchema] = {
        "send_push_notification": MCPToolSchema(
            name="send_push_notification",
            description="Send a FCM push notification to a device token or topic.",
            parameters={
                "type": "object",
                "properties": {
                    "recipient": {
                        "type": "string",
                        "description": "FCM registration token or topic (prefix '/topics/')",
                    },
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "data": {
                        "type": "object",
                        "description": "Additional key-value pairs sent in the data payload",
                    },
                },
            },
            required=["recipient", "title", "body"],
        ),
        "send_bulk_notifications": MCPToolSchema(
            name="send_bulk_notifications",
            description="Send the same notification to multiple FCM tokens (batch up to 500).",
            parameters={
                "type": "object",
                "properties": {
                    "tokens": {"type": "array", "items": {"type": "string"}},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "data": {"type": "object"},
                },
            },
            required=["tokens", "title", "body"],
        ),
        "subscribe_to_topic": MCPToolSchema(
            name="subscribe_to_topic",
            description="Subscribe a list of FCM tokens to a topic.",
            parameters={
                "type": "object",
                "properties": {
                    "tokens": {"type": "array", "items": {"type": "string"}},
                    "topic": {"type": "string"},
                },
            },
            required=["tokens", "topic"],
        ),
        "send_topic_notification": MCPToolSchema(
            name="send_topic_notification",
            description="Send a notification to all subscribers of a topic.",
            parameters={
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "data": {"type": "object"},
                },
            },
            required=["topic", "title", "body"],
        ),
        "send_shipment_alert": MCPToolSchema(
            name="send_shipment_alert",
            description="Send a structured shipment status alert to a tenant's topic.",
            parameters={
                "type": "object",
                "properties": {
                    "shipment_id": {"type": "string"},
                    "event_type": {
                        "type": "string",
                        "enum": ["status_change", "disruption", "delay", "delivery"],
                    },
                    "message": {"type": "string"},
                    "tenant_topic": {"type": "string"},
                },
            },
            required=["shipment_id", "event_type", "message", "tenant_topic"],
        ),
    }

    async def execute_tool(
        self, name: str, params: dict[str, Any], tenant_id: str | None
    ) -> Any:
        match name:
            case "send_push_notification":
                return (
                    await self._send_push(
                        params["recipient"],
                        params["title"],
                        params["body"],
                        params.get("data", {}),
                    )
                ).model_dump()
            case "send_bulk_notifications":
                return (
                    await self._send_bulk(
                        params["tokens"],
                        params["title"],
                        params["body"],
                        params.get("data", {}),
                    )
                ).model_dump()
            case "subscribe_to_topic":
                return (
                    await self._subscribe_to_topic(params["tokens"], params["topic"])
                ).model_dump()
            case "send_topic_notification":
                return (
                    await self._send_push(
                        f"/topics/{params['topic']}",
                        params["title"],
                        params["body"],
                        params.get("data", {}),
                    )
                ).model_dump()
            case "send_shipment_alert":
                data = {
                    "shipment_id": params["shipment_id"],
                    "event_type": params["event_type"],
                }
                return (
                    await self._send_push(
                        f"/topics/{params['tenant_topic']}",
                        f"Shipment Alert: {params['event_type'].replace('_', ' ').title()}",
                        params["message"],
                        data,
                    )
                ).model_dump()
            case _:
                raise ValueError(f"Unknown tool: {name}")

    # ── Implementations ───────────────────────────────────────

    async def _send_push(
        self,
        recipient: str,
        title: str,
        body: str,
        data: dict[str, Any],
    ) -> NotifyResult:
        messaging = _get_fcm_messaging()

        if messaging is None:
            log.warning(
                "notify.push.fallback",
                recipient=recipient,
                title=title,
                reason="Firebase not configured",
            )
            return NotifyResult(
                success=True,
                message_id=None,
                channel="fcm",
                recipient=recipient,
                fallback_used=True,
            )

        try:
            # Convert data values to strings (FCM requirement)
            str_data = {k: str(v) for k, v in data.items()} if data else {}

            if recipient.startswith("/topics/"):
                topic = recipient.replace("/topics/", "")
                msg = messaging.Message(
                    notification=messaging.Notification(title=title, body=body),
                    data=str_data,
                    topic=topic,
                )
            else:
                msg = messaging.Message(
                    notification=messaging.Notification(title=title, body=body),
                    data=str_data,
                    token=recipient,
                )

            message_id = messaging.send(msg)
            log.info(
                "notify.push.sent",
                recipient=recipient,
                message_id=message_id,
                title=title,
            )
            return NotifyResult(
                success=True,
                message_id=message_id,
                channel="fcm",
                recipient=recipient,
                fallback_used=False,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("notify.push.failed", recipient=recipient, error=str(exc))
            return NotifyResult(
                success=False,
                message_id=None,
                channel="fcm",
                recipient=recipient,
                fallback_used=True,
            )

    async def _send_bulk(
        self,
        tokens: list[str],
        title: str,
        body: str,
        data: dict[str, Any],
    ) -> BulkNotifyResult:
        messaging = _get_fcm_messaging()

        if messaging is None:
            log.warning("notify.bulk.fallback", count=len(tokens), reason="Firebase not configured")
            return BulkNotifyResult(sent=0, failed=len(tokens), fallback_used=True)

        try:
            str_data = {k: str(v) for k, v in data.items()} if data else {}
            notification = messaging.Notification(title=title, body=body)
            # FCM supports up to 500 tokens per multicast
            batch = tokens[:500]
            mm = messaging.MulticastMessage(
                notification=notification, data=str_data, tokens=batch
            )
            resp = messaging.send_each_for_multicast(mm)
            log.info(
                "notify.bulk.sent",
                total=len(batch),
                success_count=resp.success_count,
                failure_count=resp.failure_count,
            )
            return BulkNotifyResult(
                sent=resp.success_count,
                failed=resp.failure_count,
                fallback_used=False,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("notify.bulk.failed", error=str(exc))
            return BulkNotifyResult(sent=0, failed=len(tokens), fallback_used=True)

    async def _subscribe_to_topic(
        self, tokens: list[str], topic: str
    ) -> TopicSubscribeResult:
        messaging = _get_fcm_messaging()

        if messaging is None:
            log.warning("notify.subscribe.fallback", topic=topic, reason="Firebase not configured")
            return TopicSubscribeResult(
                topic=topic, tokens=tokens, success_count=0, failure_count=len(tokens)
            )

        try:
            resp = messaging.subscribe_to_topic(tokens, topic)
            log.info(
                "notify.subscribed",
                topic=topic,
                success_count=resp.success_count,
                failure_count=resp.failure_count,
            )
            return TopicSubscribeResult(
                topic=topic,
                tokens=tokens,
                success_count=resp.success_count,
                failure_count=resp.failure_count,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("notify.subscribe.failed", topic=topic, error=str(exc))
            return TopicSubscribeResult(
                topic=topic, tokens=tokens, success_count=0, failure_count=len(tokens)
            )


# Singleton instance
notify_mcp = NotifyMCPServer(prefix="/mcp/notify")
