from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Phase 1
    llama_server_url: str = "http://localhost:8090"
    app_host: str = "0.0.0.0"
    app_port: int = 5000
    debug: bool = True

    # Phase 2
    chroma_persist_dir: str = "./data/chromadb"
    embedding_model: str = "all-MiniLM-L6-v2"
    translation_url: str = "https://mice-tires-intelligence-outlets.trycloudflare.com"

    # Phase 3
    redis_url: str = "redis://localhost:6379/0"
    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/chatagent"
    api_secret_key: str = "change-this-secret"
    rate_limit: str = "60/minute"
    max_memory_turns: int = 20

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
