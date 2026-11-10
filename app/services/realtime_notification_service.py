import asyncio
import json
import logging
from collections import defaultdict

from app.config import settings

logger = logging.getLogger(__name__)

REDIS_EVENTS_CHANNEL = "notifications:events"


def redis_bridge_url() -> str | None:
    """Redis URL used for cross-process realtime events, or None for in-process only."""
    for candidate in (settings.REDIS_URL, settings.CELERY_BROKER_URL):
        url = str(candidate or "").strip()
        if url.startswith(("redis://", "rediss://")):
            return url
    return None


class NotificationRealtimeHub:
    """In-process pub/sub hub for per-user SSE notification events."""

    def __init__(self):
        self._queues = defaultdict(set)
        self._lock = asyncio.Lock()

    async def register(self, user_id: int):
        queue = asyncio.Queue(maxsize=200)
        async with self._lock:
            self._queues[user_id].add(queue)
        return queue

    async def unregister(self, user_id: int, queue: asyncio.Queue):
        async with self._lock:
            queues = self._queues.get(user_id)
            if not queues:
                return

            queues.discard(queue)
            if not queues:
                self._queues.pop(user_id, None)

    def publish_event(self, user_id: int, event: dict):
        queues = list(self._queues.get(user_id, set()))
        if not queues:
            return

        for queue in queues:
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass

            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Drop if still full after one eviction.
                continue

    @staticmethod
    def _to_sse(event: dict) -> str:
        event_type = event.get("type", "message")
        payload = json.dumps(event, default=str)
        return f"event: {event_type}\ndata: {payload}\n\n"

    async def stream(self, user_id: int, request, heartbeat_seconds: int = 20):
        queue = await self.register(user_id)
        try:
            yield self._to_sse({"type": "connected", "ts": asyncio.get_event_loop().time()})

            while True:
                if await request.is_disconnected():
                    break

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=heartbeat_seconds)
                    yield self._to_sse(event)
                except asyncio.TimeoutError:
                    # Keep connection alive for proxies/load balancers.
                    yield ": keep-alive\n\n"
        finally:
            await self.unregister(user_id, queue)


notification_realtime_hub = NotificationRealtimeHub()


def publish_realtime_event(user_id: int, event: dict) -> str:
    """Publish an event to the user's SSE streams.

    With Redis the event goes through the `notifications:events` channel so that events
    created in a Celery worker reach the web process holding the SSE connection; the web
    process forwards it to the local hub (see `run_redis_subscriber`). Without Redis, or if
    publishing fails, the in-process hub is used directly. Returns "redis" or "local".
    """
    url = redis_bridge_url()
    if url:
        try:
            import redis

            client = redis.Redis.from_url(url, socket_connect_timeout=0.5, socket_timeout=0.5)
            try:
                client.publish(
                    REDIS_EVENTS_CHANNEL,
                    json.dumps({"user_id": user_id, "event": event}, default=str),
                )
            finally:
                client.close()
            return "redis"
        except Exception:
            logger.warning("Redis realtime publish failed; using in-process hub", exc_info=True)
    notification_realtime_hub.publish_event(user_id=user_id, event=event)
    return "local"


def forward_redis_message(raw) -> bool:
    """Deliver one Redis pub/sub payload to the local hub."""
    try:
        data = json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)
        notification_realtime_hub.publish_event(user_id=int(data["user_id"]), event=data["event"])
        return True
    except Exception:
        logger.warning("Ignoring malformed realtime message", exc_info=True)
        return False


async def run_redis_subscriber(stop_event: asyncio.Event | None = None) -> None:
    """Background task for the web process: forward Redis events to the local SSE hub."""
    url = redis_bridge_url()
    if not url:
        return
    try:
        import redis.asyncio as aioredis
    except Exception:
        logger.warning("redis.asyncio unavailable; realtime bridge disabled")
        return

    while not (stop_event and stop_event.is_set()):
        client = aioredis.from_url(url)
        try:
            pubsub = client.pubsub()
            await pubsub.subscribe(REDIS_EVENTS_CHANNEL)
            async for message in pubsub.listen():
                if message.get("type") == "message":
                    forward_redis_message(message.get("data"))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Realtime Redis subscriber disconnected; retrying in 5s", exc_info=True)
            await asyncio.sleep(5)
        finally:
            try:
                await client.close()
            except Exception:
                pass
