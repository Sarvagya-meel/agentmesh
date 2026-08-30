from functools import lru_cache

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AgentMesh"
    app_env: str = "local"
    database_url: str = "postgresql+asyncpg://agentmesh:agentmesh@localhost:5432/agentmesh"
    log_level: str = "INFO"
    poll_interval_seconds: float = 2.0
    agentmesh_api_url: str = "http://127.0.0.1:8000"
    worker_heartbeat_seconds: float = Field(default=60.0, gt=0)
    agent_stale_seconds: float = Field(default=180.0, gt=0)
    worker_lease_seconds: int = Field(default=300, ge=10)
    worker_request_timeout_seconds: float = Field(default=30.0, gt=0)
    agent_runtime_role: str = "combined"
    agent_max_concurrency: int = Field(default=4, ge=1)
    agent_shutdown_timeout_seconds: float = Field(default=30.0, gt=0)
    registry_backend: str = "memory"
    event_store_backend: str = "memory"
    langgraph_checkpoint_backend: str = Field(
        default="memory",
        validation_alias=AliasChoices(
            "LANGGRAPH_CHECKPOINT_BACKEND",
            "ORCHESTRATOR_CHECKPOINT_BACKEND",
            "AGENT_CHECKPOINT_BACKEND",
        ),
    )
    langgraph_store_backend: str = "memory"
    langgraph_long_term_memory_enabled: bool = False
    langgraph_memory_retention_days: int = Field(default=30, ge=1)
    langsmith_tracing: bool = False
    langsmith_project: str = "agentmesh-local"
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_api_key: SecretStr | None = None
    langsmith_workspace_id: str = ""
    google_adk_session_backend: str = "memory"

    llm_provider: str = "mock"
    bedrock_model_id: str = ""
    groq_api_key: SecretStr | None = None
    groq_model: str = "openai/gpt-oss-120b"
    groq_api_base: str = "https://api.groq.com/openai/v1"
    groq_reasoning_effort: str = "medium"
    groq_temperature: float = Field(default=0.1, ge=0, le=2)
    groq_max_completion_tokens: int = Field(default=4096, gt=0)
    groq_timeout_seconds: float = Field(default=45.0, gt=0)

    aws_agent_registry_enabled: bool = False
    agent_registry_id: str = ""
    aws_agentcore_enabled: bool = False
    aws_region: str = "us-east-1"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
