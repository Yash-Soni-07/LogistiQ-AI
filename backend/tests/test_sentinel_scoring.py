import asyncio
import json

import structlog
from sqlalchemy import select

from agents.sentinel_agent import SentinelAgent
from core.config import settings
from core.redis import redis_client
from db.database import AsyncSessionLocal
from db.models import RouteSegment


async def listen_for_disruptions():
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("disruptions")
    messages = []
    # listen for 10 seconds or until cancelled
    try:
        while True:
            msg = await asyncio.wait_for(
                pubsub.get_message(ignore_subscribe_messages=True), timeout=1.0
            )
            if msg:
                messages.append(msg)
    except TimeoutError:
        pass
    except asyncio.CancelledError:
        pass
    finally:
        await pubsub.unsubscribe("disruptions")
    return messages


async def main():
    settings.PHASE_2_ENABLED = True
    structlog.configure(
        processors=[structlog.processors.TimeStamper(fmt="iso"), structlog.dev.ConsoleRenderer()]
    )
    print("--- Starting Sentinel Scoring Isolated Test ---")

    # 1. Start Redis Listener
    listener_task = asyncio.create_task(listen_for_disruptions())
    await asyncio.sleep(0.5)  # Give it time to subscribe

    # 2. Fetch RouteSegments
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(RouteSegment.id, RouteSegment.highway_code, RouteSegment.risk_score)
        )
        segments_before = res.all()
        print(f"Total RouteSegments before scoring: {len(segments_before)}")
        old_risks = {str(r.id): r.risk_score for r in segments_before}

    # 3. Run score_all_routes
    sentinel = SentinelAgent()
    await sentinel.score_all_routes()

    # 4. Fetch RouteSegments after
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(RouteSegment.id, RouteSegment.highway_code, RouteSegment.risk_score)
        )
        segments_after = res.all()

    print("\n--- Scoring Results ---")
    for r in segments_after:
        sid = str(r.id)
        old_val = old_risks.get(sid, 0.0)
        new_val = r.risk_score
        tripped = new_val > 0.75 and old_val < 0.75
        print(
            f"[{r.highway_code}]  prev_risk={old_val:.2f}  new_risk={new_val:.2f}  threshold_tripped={tripped}"
        )

    # 5. Check Redis messages
    print("\n--- Redis 'disruptions' Channel Messages ---")
    listener_task.cancel()
    messages = await asyncio.gather(listener_task, return_exceptions=True)
    if isinstance(messages[0], list) and messages[0]:
        for msg in messages[0]:
            try:
                data = json.loads(msg["data"])
                print(f"Message received: {json.dumps(data, indent=2)}")
            except Exception:
                print(f"Raw message: {msg['data']}")
    else:
        print("No messages published to 'disruptions' channel.")

    await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
