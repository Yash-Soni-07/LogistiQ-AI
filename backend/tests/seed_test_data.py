import asyncio
import uuid

from sqlalchemy import select, text

from db.database import AsyncSessionLocal
from db.models import RouteSegment, Shipment, Tenant

ROUTE_SEGMENTS = [
    {
        "highway_code": "NH-48",
        "name": "Mumbai–Pune Expressway",
        "geom": "LINESTRING(72.877 19.076, 73.856 18.520)",  # Mumbai→Pune
        "risk_score": 0.0,
        "elevation_avg_m": 18.0,
    },
    {
        "highway_code": "NH-44",
        "name": "Nagpur–Hyderabad Corridor",
        "geom": "LINESTRING(79.082 21.145, 78.486 17.385)",  # Nagpur→Hyderabad
        "risk_score": 0.0,
        "elevation_avg_m": 310.0,
    },
    {
        "highway_code": "NH-27",
        "name": "Ahmedabad–Rajkot Corridor",
        "geom": "LINESTRING(72.571 23.022, 70.801 22.291)",  # Ahmedabad→Rajkot
        "risk_score": 0.0,
        "elevation_avg_m": 45.0,
    },
    {
        "highway_code": "NH-19",
        "name": "Delhi–Kolkata Highway",
        "geom": "LINESTRING(77.213 28.679, 88.363 22.572)",  # Delhi→Kolkata
        "risk_score": 0.0,
        "elevation_avg_m": 120.0,
    },
    {
        "highway_code": "NH-66",
        "name": "Mumbai–Chennai Coastal",
        "geom": "LINESTRING(72.877 19.076, 80.270 13.082)",  # Mumbai→Chennai
        "risk_score": 0.0,
        "elevation_avg_m": 22.0,
    },
]


async def seed():
    async with AsyncSessionLocal() as db:
        # Seed Tenant
        res = await db.execute(select(Tenant).where(Tenant.name == "LogistiQ Demo"))
        tenant = res.scalar_one_or_none()
        if not tenant:
            tenant_id = uuid.uuid4()
            tenant = Tenant(id=tenant_id, name="LogistiQ Demo", plan_tier="pro", is_active=True)
            db.add(tenant)
            await db.commit()
            print("* Inserted 1 Tenant")
        else:
            tenant_id = tenant.id
            print("* Tenant already seeded")

        # Seed Route Segments
        res = await db.execute(
            select(RouteSegment).where(
                RouteSegment.highway_code.in_([s["highway_code"] for s in ROUTE_SEGMENTS])
            )
        )
        existing_segs = res.scalars().all()
        existing_codes = {s.highway_code for s in existing_segs}

        inserted_segs = 0
        seg_ids = []
        for s in ROUTE_SEGMENTS:
            if s["highway_code"] not in existing_codes:
                sid = uuid.uuid4()
                seg_ids.append(sid)
                stmt = text("""
                    INSERT INTO route_segments (id, tenant_id, highway_code, risk_score, elevation_avg_m, geom)
                    VALUES (:id, :t_id, :code, :rs, :elev, ST_GeomFromText(:wkt, 4326))
                """)
                await db.execute(
                    stmt,
                    {
                        "id": sid,
                        "t_id": tenant_id,
                        "code": s["highway_code"],
                        "rs": s["risk_score"],
                        "elev": s["elevation_avg_m"],
                        "wkt": s["geom"],
                    },
                )
                inserted_segs += 1
            else:
                seg_ids.append(
                    [x.id for x in existing_segs if x.highway_code == s["highway_code"]][0]
                )

        if inserted_segs > 0:
            await db.commit()
            print(f"* Inserted {inserted_segs} RouteSegments")
        else:
            print("* RouteSegments already seeded")

        # Seed Shipments
        res = await db.execute(select(Shipment).where(Shipment.tenant_id == tenant_id))
        existing_ships = res.scalars().all()
        if not existing_ships:
            sectors = ["automotive", "pharma", "retail"]
            for i in range(3):
                sid = uuid.uuid4()
                stmt = text("""
                    INSERT INTO shipments (id, tenant_id, route_id, status, mode, sector, origin, destination, tracking_num, current_lat, current_lon, risk_score, co2_kg)
                    VALUES (:id, :t_id, :r_id, 'in_transit', 'road', :sec, 'Origin', 'Dest', :trk, 0.0, 0.0, 0.0, 0.0)
                """)
                await db.execute(
                    stmt,
                    {
                        "id": sid,
                        "t_id": tenant_id,
                        "r_id": seg_ids[i],
                        "sec": sectors[i],
                        "trk": f"TRK-DEMO-{i}",
                    },
                )
            await db.commit()
            print("* Inserted 3 Shipments")
        else:
            print("* Shipments already seeded")


if __name__ == "__main__":
    asyncio.run(seed())
