from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str
    gemini_api_key: str
    openrouter_api_key: str = ""
    openai_api_key: str = ""
    hf_token: str = ""

    app_env: str = "development"
    log_level: str = "INFO"


settings = Settings()
