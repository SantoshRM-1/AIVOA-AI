from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://localhost/aivoa"
    gemini_api_key: str = ""
    gemini_model: str = ""
    ai_request_timeout_seconds: int = 60
    gemini_max_retries: int = 2
    gemini_max_retry_wait_seconds: int = 15
    max_pdf_bytes: int = 20 * 1024 * 1024
    max_text_characters: int = 200_000
    cors_origins: str = "http://localhost:5173"
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
