import asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from core.config import settings
from db.models import Shipment
from db.seed import INDIAN_CITIES

async def fix_coordinates():
    """Corrects current_lat and current_lon to match the origin city's exact coordinates."""
    engine = create_async_engine(str(settings.DATABASE_URL))
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    
    city_coords = {name: (lat, lon) for name, lon, lat in INDIAN_CITIES}
    
    print("Starting coordinate fix...")
    
    async with async_session() as session:
        result = await session.execute(select(Shipment))
        shipments = result.scalars().all()
        
        fixed_count = 0
        for s in shipments:
            if s.origin in city_coords:
                lat, lon = city_coords[s.origin]
                s.current_lat = lat
                s.current_lon = lon
                fixed_count += 1
                
        await session.commit()
        print(f"Fixed coordinates for {fixed_count} shipments.")

if __name__ == "__main__":
    asyncio.run(fix_coordinates())
