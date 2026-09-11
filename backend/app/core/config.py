from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    supabase_url: str | None = None
    supabase_anon_key: str | None = None
    supabase_service_role_key: str | None = None
    supabase_jwt_secret: str | None = None
    frontend_url: str = "http://localhost:5173"
    api_v1_prefix: str = "/api/v1"
    embedding_provider: str | None = None
    embedding_api_key: str | None = None
    embedding_model: str | None = None
    embedding_dimension: int | None = None
    # Experimental AI review (isolated /ai-review-test feature only)
    google_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    # Gemini embeddings (preferred) — uses GOOGLE_API_KEY fallback if EMBEDDING_API_KEY not set
    gemini_embedding_model: str = "gemini-embedding-001"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"

    def model_post_init(self, __context):  # type: ignore
        # Treat placeholder values from .env.example as not set
        placeholders = {"your-anon-key", "your-service-role-key", "your-jwt-secret", "YOUR_JWT_SECRET", "your-project.supabase.co", "your-embedding-key", "your-google-api-key"}
        for field in ["supabase_url", "supabase_anon_key", "supabase_service_role_key", "supabase_jwt_secret", "embedding_api_key", "google_api_key"]:
            val = getattr(self, field)
            if val and any(ph in val for ph in placeholders):
                setattr(self, field, None)
        # Normalize embedding provider
        if self.embedding_provider:
            self.embedding_provider = self.embedding_provider.strip().lower()
            if self.embedding_provider in {"", "none", "disabled"}:
                self.embedding_provider = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
