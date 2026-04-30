import asyncio

import structlog

from core.config import settings
from core.redis import redis_client


async def main():
    settings.PHASE_2_ENABLED = True  # ensure enabled for test

    structlog.configure(
        processors=[structlog.processors.TimeStamper(fmt="iso"), structlog.dev.ConsoleRenderer()]
    )

    print("--- Starting GDELT Scanner Isolated Test ---")

    # Inject dummy article into the test run directly via a mock or we can just mock the fetch
    # To avoid changing gdelt_scanner, let's just use redis_client to set count to 2,
    # then next run hits 3 if we add a manual article or we just run it with a mock.
    # Actually, simpler: call the scan, and then if 0 alerts, let's just manually trigger
    # the logic or mock fetch_rss in the test script.
    import agents.gdelt_scanner as scanner

    original_fetch_rss = scanner.fetch_rss

    async def mock_fetch_rss(url, source):
        if source == "toi":
            return [
                scanner.Article(
                    "Huge trucker strike in Mumbai causes port delay",
                    "http://fake.url/1",
                    "toi",
                    "now",
                ),
                scanner.Article(
                    "Transport strike in Mumbai affecting goods", "http://fake.url/2", "toi", "now"
                ),
                scanner.Article("Lorry bandh near Mumbai today", "http://fake.url/3", "toi", "now"),
            ]
        return await original_fetch_rss(url, source)

    scanner.fetch_rss = mock_fetch_rss

    alerts = await scanner.scan_gdelt_news()

    scanner.fetch_rss = original_fetch_rss

    print("\n--- Results ---")
    print(f"DisruptionAlerts Generated: {len(alerts)}")
    for alert in alerts:
        print(f" - {alert}")

    print("\n--- Redis Keys ---")
    keys = await redis_client.keys("gdelt:*")
    for key in keys:
        val = await redis_client.get(key)
        ttl = await redis_client.ttl(key)
        print(f"{key}: count={val}, TTL={ttl}s")

    await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
