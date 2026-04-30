import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def enable_postgis():
    db_url = os.getenv("DATABASE_URL")
    engine = create_async_engine(db_url)

    print("Connecting through VPC to enable PostGIS...")
    async with engine.begin() as conn:
        # Turn on the spatial features required for your map data
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))

    print("PostGIS enabled successfully!")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(enable_postgis())
