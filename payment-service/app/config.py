from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env")

    DB_HOST: str
    DB_PORT: int
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str

    @property
    def DB_URL(self):
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}" 

    API_KEY: str

    RABBITMQ_URL: str
    PAYMENT_SUCCEEDED_ROUTING_KEY: str
    PAYMENT_EXCHANGE_NAME: str
    PAYMENT_QUEUE_NAME: str

    DLX_EXCHANGE: str
    DLQ_QUEUE: str
    DLQ_ROUTING_KEY: str

    WEBHOOK_TIMEOUT_SECONDS: float
    WEBHOOK_MAX_RETRIES: int
    BASE_DELAY: float

    GATEWAY_SUCCESS_RATE: float
    GATEWAY_MIN_DELAY_SECONDS: float
    GATEWAY_MAX_DELAY_SECONDS: float

    CONSUMER_MAX_ATTEMPTS: int
    CONSUMER_RETRY_DELAYS: tuple[int, ...]

settings = Settings()

@lru_cache
def get_settings() -> Settings:      
    return Settings()