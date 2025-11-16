from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application runtime configuration."""

    database_url: str = Field(
        default=f"sqlite:///{(Path(__file__).resolve().parents[2] / 'data' / 'ai_teacher.db')}"
    )
    api_prefix: str = "/api"
    storage_root: Path = Field(
        default=Path(__file__).resolve().parents[2] / "data" / "storage"
    )
    asr_model_size: str = Field(default="small")
    asr_device: str = Field(default="cpu")
    asr_compute_type: str = Field(default="int8")
    embedding_model_name: str = Field(default="qwen3-embedding-0.6b")
    embedding_model_path: Path = Field(
        default=Path(__file__).resolve().parents[2] / "models" / "qwen3-embedding-0.6b"
    )
    embedding_device: str = Field(default="auto")  # cuda 优先，失败回退 cpu
    embedding_max_tokens: int = Field(default=512)
    embedding_batch_size: int = Field(default=64)
    internal_api_token: str = Field(default="ai-teacher-internal-token")
    chroma_db_dir: Path = Field(default=Path(__file__).resolve().parents[2] / "data" / "chroma")

    model_config = SettingsConfigDict(env_file=".env", env_prefix="AI_TEACHER_")


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance."""
    settings = Settings()
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    settings.chroma_db_dir.mkdir(parents=True, exist_ok=True)
    settings.embedding_model_path.parent.mkdir(parents=True, exist_ok=True)
    return settings


class PaginationParams(BaseModel):
    """Common pagination parameters."""

    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
