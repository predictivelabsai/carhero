import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

load_dotenv()

DB_URL = os.environ["DB_URL"]
SCHEMA = "carhero"

engine = create_engine(DB_URL, pool_pre_ping=True, pool_size=5, max_overflow=10)


@event.listens_for(engine, "connect")
def set_search_path(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute(f"SET search_path TO {SCHEMA}, public")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create schema and all tables."""
    with engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        conn.commit()
    Base.metadata.create_all(bind=engine)
    _init_chat_tables()
    _init_car_tables()


def _init_chat_tables():
    """Create chat tables if they don't exist."""
    ddl = [
        f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.chat_users (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )""",
        f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.chat_sessions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES {SCHEMA}.chat_users(id),
            title VARCHAR(255) DEFAULT 'New chat',
            agent_slug VARCHAR(100),
            share_token VARCHAR(64),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )""",
        f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.chat_messages (
            id SERIAL PRIMARY KEY,
            session_id INTEGER REFERENCES {SCHEMA}.chat_sessions(id),
            role VARCHAR(20) NOT NULL,
            content TEXT NOT NULL,
            agent_slug VARCHAR(100),
            tool_calls JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )""",
    ]
    with engine.connect() as conn:
        for stmt in ddl:
            conn.execute(text(stmt))
        conn.commit()


def _init_car_tables():
    """Create car listing tables if they don't exist."""
    ddl = [
        f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.car_listings (
            id SERIAL PRIMARY KEY,
            make VARCHAR(100) NOT NULL,
            model VARCHAR(100) NOT NULL,
            variant VARCHAR(200),
            generation VARCHAR(100),
            price_eur NUMERIC(12,2),
            price_original NUMERIC(12,2),
            currency VARCHAR(3) DEFAULT 'EUR',
            year INTEGER,
            mileage_km INTEGER,
            fuel_type VARCHAR(50),
            transmission VARCHAR(50),
            body_type VARCHAR(50),
            engine_size_cc INTEGER,
            power_hp INTEGER,
            power_kw INTEGER,
            torque_nm INTEGER,
            drive_type VARCHAR(20),
            steering_side VARCHAR(5),
            gears INTEGER,
            co2_grams INTEGER,
            fuel_consumption_l100km NUMERIC(4,1),
            emission_class VARCHAR(20),
            doors INTEGER,
            seats INTEGER,
            exterior_color VARCHAR(50),
            interior_color VARCHAR(50),
            interior_material VARCHAR(50),
            condition VARCHAR(20) DEFAULT 'used',
            first_registration_date DATE,
            owners_count INTEGER,
            accident_free BOOLEAN,
            service_history BOOLEAN,
            features JSONB,
            equipment_packages JSONB,
            source_url VARCHAR(500) UNIQUE,
            provider VARCHAR(50) NOT NULL,
            country VARCHAR(5),
            city VARCHAR(100),
            seller_type VARCHAR(20),
            seller_name VARCHAR(200),
            listed_date DATE,
            scraped_at TIMESTAMPTZ DEFAULT NOW(),
            image_urls JSONB,
            image_count INTEGER DEFAULT 0,
            status VARCHAR(20) DEFAULT 'active',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )""",
        f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.price_history (
            id SERIAL PRIMARY KEY,
            listing_id INTEGER REFERENCES {SCHEMA}.car_listings(id),
            price_eur NUMERIC(12,2),
            recorded_at TIMESTAMPTZ DEFAULT NOW()
        )""",
        f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.car_models (
            id SERIAL PRIMARY KEY,
            make VARCHAR(100) NOT NULL,
            model VARCHAR(100) NOT NULL,
            generation VARCHAR(100),
            body_type VARCHAR(50),
            production_start INTEGER,
            production_end INTEGER,
            segment VARCHAR(50),
            UNIQUE(make, model, generation)
        )""",
        f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.market_snapshots (
            id SERIAL PRIMARY KEY,
            make VARCHAR(100),
            model VARCHAR(100),
            country VARCHAR(5),
            avg_price_eur NUMERIC(12,2),
            median_price_eur NUMERIC(12,2),
            listing_count INTEGER,
            avg_mileage_km INTEGER,
            avg_age_years NUMERIC(4,1),
            snapshot_date DATE NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )""",
    ]
    indexes = [
        f"CREATE INDEX IF NOT EXISTS idx_car_listings_make ON {SCHEMA}.car_listings(make)",
        f"CREATE INDEX IF NOT EXISTS idx_car_listings_model ON {SCHEMA}.car_listings(make, model)",
        f"CREATE INDEX IF NOT EXISTS idx_car_listings_provider ON {SCHEMA}.car_listings(provider)",
        f"CREATE INDEX IF NOT EXISTS idx_car_listings_price ON {SCHEMA}.car_listings(price_eur)",
        f"CREATE INDEX IF NOT EXISTS idx_car_listings_year ON {SCHEMA}.car_listings(year)",
        f"CREATE INDEX IF NOT EXISTS idx_car_listings_country ON {SCHEMA}.car_listings(country)",
        f"CREATE INDEX IF NOT EXISTS idx_price_history_listing ON {SCHEMA}.price_history(listing_id)",
        f"CREATE INDEX IF NOT EXISTS idx_market_snapshots_date ON {SCHEMA}.market_snapshots(snapshot_date)",
    ]
    with engine.connect() as conn:
        for stmt in ddl:
            conn.execute(text(stmt))
        for stmt in indexes:
            conn.execute(text(stmt))
        conn.commit()
