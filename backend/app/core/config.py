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
    # Legacy Gemini configuration. Kept for the experimental /ai-review-test
    # feature and as a future interview-provider fallback.
    google_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    # NVIDIA NIM interview evaluator (primary).
    nvidia_api_key: str | None = None
    nvidia_model: str = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
    # Groq is retained for Whisper STT; it is not an interview reasoning fallback.
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    groq_stt_model: str = "whisper-large-v3-turbo"
    # Interview LLM resilience budgets (seconds).
    interview_llm_timeout_seconds: int = 20
    interview_llm_total_budget_seconds: int = 75
    # Gemini is the primary interview reasoning provider. Groq is used only
    # as the existing reasoning fallback; NVIDIA remains TTS-only.
    # Interview TTS — NVIDIA-hosted voice (TEXT -> SPEECH only).
    # NVIDIA_API_KEY is backend-only and never reaches the frontend.
    tts_provider: str = "nvidia"
    nvidia_api_key: str | None = None
    nvidia_tts_model: str = "magpie-tts-multilingual"
    nvidia_tts_voice: str = "Magpie-Multilingual.EN-US.Aria"
    nvidia_tts_language: str = "en-US"
    nvidia_tts_function_id: str = "877104f7-e885-42b9-8de8-f6e4c6303969"
    nvidia_tts_endpoint: str = ""
    nvidia_tts_timeout_seconds: int = 30
    # Local-development TTS diagnostics (TTS_DEBUG=true). Adds safe provider
    # facts to logs and to the /interview/tts 503 response. Always false in
    # production. NEVER enables key/secret output.
    tts_debug: bool = False
    # Gemini embeddings (preferred) — uses GOOGLE_API_KEY fallback if EMBEDDING_API_KEY not set
    gemini_embedding_model: str = "gemini-embedding-001"
    # Optional server-side GitHub token. Never returned to the frontend.
    github_token: str | None = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"

    def model_post_init(self, __context):  # type: ignore
        # Treat placeholder values from .env.example as not set
        placeholders = {"your-anon-key", "your-service-role-key", "your-jwt-secret", "YOUR_JWT_SECRET", "your-project.supabase.co", "your-embedding-key", "your-google-api-key", "your-nvidia-api-key", "your-groq-api-key"}
        for field in ["supabase_url", "supabase_anon_key", "supabase_service_role_key", "supabase_jwt_secret", "embedding_api_key", "google_api_key", "nvidia_api_key", "groq_api_key", "github_token"]:
            val = getattr(self, field)
            if val and any(ph in val for ph in placeholders):
                setattr(self, field, None)
        # Normalize TTS provider (NVIDIA voice only)
        if self.tts_provider:
            self.tts_provider = self.tts_provider.strip().lower()
            if self.tts_provider in {"", "none", "disabled"}:
                self.tts_provider = "nvidia"
        # Normalize embedding provider
        if self.embedding_provider:
            self.embedding_provider = self.embedding_provider.strip().lower()
            if self.embedding_provider in {"", "none", "disabled"}:
                self.embedding_provider = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
