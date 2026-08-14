from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AgentMesh"
    app_env: str = "local"
    database_url: str = "postgresql+asyncpg://agentmesh:agentmesh@localhost:5432/agentmesh"
    log_level: str = "INFO"
    poll_interval_seconds: float = 2.0

    llm_provider: str = "mock"
    bedrock_model_id: str = ""

    aws_agent_registry_enabled: bool = False
    agent_registry_id: str = ""
    aws_agentcore_enabled: bool = False
    aws_region: str = "us-east-1"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
