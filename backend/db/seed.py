"""
Async seed script for LogistiQ AI backend.
"""

import asyncio
import random
from datetime import datetime, timedelta

import structlog
import structlog.stdlib
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import (
    Carrier,
    DeclarativeBase,
    DisruptionEvent,
    DisruptionSeverity,
    DisruptionType,
    NewsAlert,
    PlanTier,
    RouteSegment,
    Shipment,
    ShipmentMode,
    ShipmentStatus,
    SubscriptionEvent,
    Telemetry,
    Tenant,
    User,
    UserRole,
)

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

DATABASE_URL = "postgresql+asyncpg://postgres:password@localhost:5432/logistiq"

# Indian highways as WKT LineStrings
HIGHWAYS_WKT = {
    "NH-48": "LINESTRING(72.8656 19.0144, 77.5858 12.9716, 80.2707 13.0827, 88.3639 22.5726)",
    "NH-44": "LINESTRING(72.8656 19.0144, 77.5858 12.9716, 88.3639 22.5726, 94.9221 28.6139)",
    "NH-19": "LINESTRING(72.8656 19.0144, 80.2707 13.0827, 88.3639 22.5726, 86.1350 26.4499)",
    "NH-27": "LINESTRING(72.8656 19.0144, 80.2707 13.0827, 88.3639 22.5726, 94.9221 28.6139)",
    "NH-66": "LINESTRING(72.8656 19.0144, 76.2673 10.0050, 75.7139 11.2588, 80.2707 13.0827)",
    "NH-544": "LINESTRING(76.2673 10.0050, 75.7139 11.2588, 80.2707 13.0827, 88.3639 22.5726)",
    "NH-16": "LINESTRING(80.2707 13.0827, 88.3639 22.5726, 94.9221 28.6139)",
    "NH-65": "LINESTRING(72.8656 19.0144, 77.5858 12.9716, 80.2707 13.0827)",
    "NH-8": "LINESTRING(72.8656 19.0144, 72.5713 23.0225, 72.8777 19.0760)",
    "NH-4": "LINESTRING(72.8656 19.0144, 77.5858 12.9716, 80.2707 13.0827)",
    "NH-6": "LINESTRING(72.8656 19.0144, 80.2707 13.0827, 88.3639 22.5726)",
    "NH-58": "LINESTRING(72.8656 19.0144, 77.5858 12.9716, 88.3639 22.5726, 94.9221 28.6139)",
}

# Indian cities for shipment origins/destinations
INDIAN_CITIES = [
    ("Mumbai", 72.8777, 19.0760),
    ("Delhi", 77.1025, 28.7041),
    ("Bangalore", 77.5858, 12.9716),
    ("Hyderabad", 78.4867, 17.3850),
    ("Chennai", 80.2707, 13.0827),
    ("Kolkata", 88.3639, 22.5726),
    ("Ahmedabad", 72.5713, 23.0225),
    ("Pune", 73.8567, 18.5204),
    ("Surat", 72.8777, 21.1702),
    ("Jaipur", 75.7139, 26.9124),
    ("Lucknow", 80.9462, 26.8467),
    ("Kanpur", 80.3318, 26.4499),
    ("Nagpur", 79.0882, 21.1458),
    ("Indore", 75.8577, 22.7196),
    ("Thane", 72.9780, 19.2183),
    ("Bhopal", 77.4120, 23.2599),
    ("Visakhapatnam", 83.2185, 17.6868),
    ("Pimpri-Chinchwad", 73.7949, 18.6332),
    ("Patna", 85.1376, 25.5941),
    ("Vadodara", 73.1812, 22.3072),
]

# Sectors for shipments
SECTORS = [
    "automotive",
    "pharma",
    "cold_chain",
    "retail",
    "tech",
    "electronics",
    "textiles",
    "agriculture",
]

# Indian carrier names
CARRIER_NAMES = [
    "Mahindra Logistics",
    "TCI Express",
    "Blue Dart",
    "CONCOR",
    "SCI",
    "DHL India",
    "FedEx India",
    "Spoton",
    "Rivigo",
    "Porter",
    "Gati",
    "Allcargo",
]

# Disruption events data
DISRUPTION_TYPES = [t.value for t in DisruptionType]
DISRUPTION_SEVERITIES = [s.value for s in DisruptionSeverity]


async def create_tenant(session: AsyncSession, name: str, tier: PlanTier) -> Tenant:
    """Create a tenant with default admin user."""
    tenant = Tenant(name=name, created_at=datetime.utcnow(), updated_at=datetime.utcnow())

    # Create default admin user
    admin_user = User(
        email=f"admin@{name.lower().replace(' ', '').replace(',', '')}.com",
        full_name="Admin User",
        role=UserRole.ADMIN,
        tenant_id=tenant.id,
    )

    session.add(tenant)
    session.add(admin_user)
    await session.commit()
    await session.refresh(tenant)

    logger.info("Created tenant", tenant_id=tenant.id, name=name, tier=tier.value)
    return tenant


async def create_carriers(session: AsyncSession, tenant_id: str) -> list[Carrier]:
    """Create carriers for a tenant."""
    carriers = []
    for name in random.sample(CARRIER_NAMES, 5):
        carrier = Carrier(
            name=name,
            tenant_id=tenant_id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        carriers.append(carrier)

    session.add_all(carriers)
    await session.commit()

    logger.info("Created carriers", tenant_id=tenant_id, count=len(carriers))
    return carriers


async def create_shipments(
    session: AsyncSession, tenant_id: str, carriers: list[Carrier]
) -> list[Shipment]:
    """Create shipments for a tenant."""
    shipments = []

    for _ in range(20):
        origin_city, origin_lon, origin_lat = random.choice(INDIAN_CITIES)
        dest_city, dest_lon, dest_lat = random.choice(INDIAN_CITIES)

        while origin_city == dest_city:
            dest_city, dest_lon, dest_lat = random.choice(INDIAN_CITIES)

        shipment = Shipment(
            tenant_id=tenant_id,
            carrier_id=random.choice(carriers).id if carriers else None,
            status=random.choice([s.value for s in ShipmentStatus]),
            mode=random.choice([m.value for m in ShipmentMode]),
            origin=origin_city,
            destination=dest_city,
            sector=random.choice(SECTORS),
            weight_kg=round(random.uniform(100, 10000), 2) if random.random() > 0.3 else None,
            volume_m3=round(random.uniform(1, 100), 2) if random.random() > 0.3 else None,
            temperature_c=round(random.uniform(-20, 25), 1) if random.random() > 0.7 else None,
            estimated_delivery=(datetime.utcnow() + timedelta(days=random.randint(1, 30))).date()
            if random.random() > 0.2
            else None,
            actual_delivery=(datetime.utcnow() + timedelta(days=random.randint(1, 30))).date()
            if random.random() > 0.8
            else None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        shipments.append(shipment)

    session.add_all(shipments)
    await session.commit()

    logger.info("Created shipments", tenant_id=tenant_id, count=len(shipments))
    return shipments


async def create_route_segments(
    session: AsyncSession, shipments: list[Shipment]
) -> list[RouteSegment]:
    """Create route segments for shipments."""
    route_segments = []

    for _shipment in shipments:
        # Create 2-4 route segments per shipment
        num_segments = random.randint(2, 4)
        highway_keys = list(HIGHWAYS_WKT.keys())

        for _i in range(num_segments):
            highway = random.choice(highway_keys)
            wkt = HIGHWAYS_WKT[highway]

            segment = RouteSegment(
                tenant_id=shipments[0].tenant_id if shipments else None,
                highway_code=highway,
                geom=f"SRID=4326;{wkt}",
                risk_score=round(random.uniform(0.1, 0.9), 2),
                created_at=datetime.utcnow(),
            )
            route_segments.append(segment)

    session.add_all(route_segments)
    await session.commit()

    logger.info("Created route segments", count=len(route_segments))
    return route_segments


async def create_disruption_events(session: AsyncSession, tenant_id: str) -> list[DisruptionEvent]:
    """Create disruption events."""
    disruption_events = []

    # Indian cities with coordinates for disruption centers
    disruption_cities = [
        ("Mumbai", 72.8777, 19.0760),
        ("Delhi", 77.1025, 28.7041),
        ("Bangalore", 77.5858, 12.9716),
        ("Hyderabad", 78.4867, 17.3850),
        ("Chennai", 80.2707, 13.0827),
        ("Kolkata", 88.3639, 22.5726),
        ("Ahmedabad", 72.5713, 23.0225),
    ]

    for _ in range(5):
        city, lon, lat = random.choice(disruption_cities)

        event = DisruptionEvent(
            tenant_id=tenant_id,
            type=random.choice(DISRUPTION_TYPES),
            severity=random.choice(DISRUPTION_SEVERITIES),
            status="active" if random.random() > 0.3 else "resolved",
            center_geom=f"SRID=4326;POINT({lon} {lat})",
            radius_km=round(random.uniform(10, 100), 1),
            description=f"{random.choice(DISRUPTION_TYPES).capitalize()} disruption near {city}",
            impact=f"Impacting shipments in {random.randint(10, 50)} km radius",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        disruption_events.append(event)

    session.add_all(disruption_events)
    await session.commit()

    logger.info("Created disruption events", tenant_id=tenant_id, count=len(disruption_events))
    return disruption_events


async def create_telemetry(session: AsyncSession, shipments: list[Shipment]) -> list[Telemetry]:
    """Create telemetry data for shipments."""
    telemetry_data = []

    for shipment in shipments:
        # Create 5-15 telemetry records per shipment
        num_records = random.randint(5, 15)

        for i in range(num_records):
            telemetry = Telemetry(
                shipment_id=shipment.id,
                ts=datetime.utcnow() - timedelta(minutes=i * 30),
                data={
                    "temperature_c": round(random.uniform(-10, 25), 1),
                    "humidity": round(random.uniform(20, 80), 1),
                    "location": {
                        "lat": round(random.uniform(8, 35), 6),
                        "lon": round(random.uniform(68, 97), 6),
                    },
                    "speed_kmh": round(random.uniform(0, 80), 1),
                    "door_open": random.choice([True, False]),
                    "fuel_level": round(random.uniform(0, 100), 1),
                },
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            telemetry_data.append(telemetry)

    session.add_all(telemetry_data)
    await session.commit()

    logger.info("Created telemetry records", count=len(telemetry_data))
    return telemetry_data


async def create_news_alerts(session: AsyncSession, tenant_id: str) -> list[NewsAlert]:
    """Create news alerts."""
    news_alerts = [
        NewsAlert(
            title="Major Highway Closure Due to Landslide",
            content="NH-48 closed between Mumbai and Bangalore due to landslide. Alternative routes recommended.",  # noqa: E501
            category="traffic",
            priority=2,
            created_at=datetime.utcnow(),
        ),
        NewsAlert(
            title="New Trade Agreement Benefits Exporters",
            content="New trade agreement with ASEAN countries reduces tariffs by 15% for eligible goods.",  # noqa: E501
            category="trade",
            priority=1,
            created_at=datetime.utcnow(),
        ),
        NewsAlert(
            title="Weather Alert: Heavy Rains Expected",
            content="IMD predicts heavy rainfall in coastal regions for next 48 hours. Expect delays.",  # noqa: E501
            category="weather",
            priority=3,
            created_at=datetime.utcnow(),
        ),
    ]

    session.add_all(news_alerts)
    await session.commit()

    logger.info("Created news alerts", tenant_id=tenant_id, count=len(news_alerts))
    return news_alerts


async def create_subscription_events(
    session: AsyncSession, tenant_id: str, users: list[User]
) -> list[SubscriptionEvent]:
    """Create subscription events."""
    subscription_events = []

    event_types = ["shipment_status_change", "disruption_alert", "news_alert", "system_update"]

    for _ in range(10):
        event = SubscriptionEvent(
            tenant_id=tenant_id,
            user_id=random.choice(users).id,
            event_type=random.choice(event_types),
            details={
                "message": f"Sample {random.choice(event_types)} event",
                "timestamp": datetime.utcnow().isoformat(),
            }
            if random.random() > 0.5
            else None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        subscription_events.append(event)

    session.add_all(subscription_events)
    await session.commit()

    logger.info("Created subscription events", tenant_id=tenant_id, count=len(subscription_events))
    return subscription_events


async def main():
    """Main seed script execution."""
    logger.info("Starting seed script")

    # Create database engine and session
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with async_session() as session:
        # Create all tables
        async with engine.begin() as conn:
            await conn.run_sync(DeclarativeBase.metadata.create_all)

        logger.info("Database tables created")

        # Create tenants
        tenants = [
            ("Mahindra Logistics", PlanTier.PRO),
            ("TCI Express", PlanTier.STARTER),
            ("Demo Corp", PlanTier.ENTERPRISE),
        ]

        for name, tier in tenants:
            tenant = await create_tenant(session, name, tier)

            # Create carriers
            carriers = await create_carriers(session, tenant.id)

            # Create shipments
            shipments = await create_shipments(session, tenant.id, carriers)

            # Create route segments
            await create_route_segments(session, shipments)

            # Create disruption events
            await create_disruption_events(session, tenant.id)

            # Create telemetry
            await create_telemetry(session, shipments)

            # Create news alerts
            await create_news_alerts(session, tenant.id)

            # Create subscription events
            users_result = await session.execute(select(User).where(User.tenant_id == tenant.id))
            users = list(users_result.scalars().all())
            await create_subscription_events(session, tenant.id, users)

        logger.info("Seeding completed successfully")


if __name__ == "__main__":
    asyncio.run(main())
