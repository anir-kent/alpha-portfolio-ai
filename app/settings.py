from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process settings. Secrets come from the environment (see .env.example)."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="APP_", extra="ignore")

    database_url: str = "sqlite:///./data/app.db"
    seed_user_password: str = ""
    session_ttl_hours: int = 12
    cookie_secure: bool = False
    market_data_snapshot_path: str = "data/market_snapshot.json"
    llm_mode: str = "recorded"  # recorded | live
    llm_api_key: str = ""
    cors_origins: list[str] = ["http://localhost:5173"]
