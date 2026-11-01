import sys
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

sys.path.append(str(Path(__file__).parent.parent))

from testcontainers.postgres import PostgresContainer

from app.config import Settings, get_settings
from app.dependencies import get_db
from app.main import app
from app.models.payments import Base

#1. Контейнер PostgreSQL (один на всю сессию)

@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:
        yield pg


#2. Настройки конфигурации для тестов 

@pytest.fixture(scope="session")
def test_settings(postgres_container) -> Settings:
    return Settings(
            _env_file=None,
            
            DB_HOST=postgres_container.get_container_host_ip(),
            DB_PORT=int(postgres_container.get_exposed_port(5432)),
            DB_USER=postgres_container.username,
            DB_PASSWORD=postgres_container.password,
            DB_NAME=postgres_container.dbname,
            
            API_KEY="lD9sq1I1A7IM9Egvu6HFj9EZPrN1V1obs_CTlSm6egc",
            
            RABBITMQ_URL="amqp://guest:guest@127.0.0.1:5672/",
            PAYMENT_EXCHANGE_NAME="payments",
            PAYMENT_QUEUE_NAME="payments.new",
            PAYMENT_SUCCEEDED_ROUTING_KEY="payment.succeeded",
            DLX_EXCHANGE="payments.dlx",
            DLQ_QUEUE="payments.dlq",
            DLQ_ROUTING_KEY="payment.failed",
            
            WEBHOOK_TIMEOUT_SECONDS=10.0,
            WEBHOOK_MAX_RETRIES=3,
            BASE_DELAY=1.0,
            
            GATEWAY_SUCCESS_RATE=0.9,
            GATEWAY_MIN_DELAY_SECONDS=2.0,
            GATEWAY_MAX_DELAY_SECONDS=5.0,
            
            CONSUMER_MAX_ATTEMPTS=3,
            CONSUMER_RETRY_DELAYS=(1, 4, 16),
        )

#3. Асинхронный движок и схема

@pytest.fixture(scope="session")
async def engine(test_settings: Settings):
    eng = create_async_engine(
        test_settings.DB_URL,
        poolclass=NullPool,       
        future=True,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


#4. Сессия БД на каждый тест 

@pytest.fixture
async def db_session(engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        try:
            yield session
        finally:
            await session.rollback()


#5. HTTP-клиент с подменой зависимостей 

@pytest.fixture
async def client(test_settings: Settings, db_session: AsyncSession) -> AsyncGenerator[Any, Any]:
    async def _override_get_session():
        yield db_session

    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_db] = _override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


#6. Очистка таблиц перед каждым тестом 

@pytest.fixture(autouse=True)
async def clean_tables(engine):
    """TRUNCATE payments и outbox перед каждым тестом для изоляции."""
    async with engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE TABLE payments, outbox RESTART IDENTITY CASCADE")
        )
    yield