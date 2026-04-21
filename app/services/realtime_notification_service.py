import asyncio
import json
from collections import defaultdict


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
        return f"event: {event_type}\\ndata: {payload}\\n\\n"

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
                    yield ": keep-alive\\n\\n"
        finally:
            await self.unregister(user_id, queue)


notification_realtime_hub = NotificationRealtimeHub()
