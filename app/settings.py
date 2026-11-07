from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process settings. Secrets come from the environment (see .env.example)."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="APP_", extra="ignore")

    database_url: str = "sqlite:///./data/app.db"
    seed_user_password: str = ""
    session_ttl_hours: int = 12
    cookie_secure: bool = False
    market_data_snapshot_path: str = "data/market_snapshot.json"
    fund_lookthrough_path: str = "data/fund_lookthrough.json"
    twelve_data_api_key: str = ""  # only used by app.market_refresh
    llm_mode: str = "recorded"  # recorded | live
    llm_api_key: str = ""
    llm_base_url: str = "https://api.anthropic.com/v1/"  # any OpenAI-compatible endpoint (e.g. a LiteLLM gateway)
    llm_model: str = "claude-sonnet-5-5"
    llm_recordings_dir: str = "data/llm_recordings"
    llm_record: bool = False  # live mode only: save each response as a recording
    llm_stream_poll_seconds: float = 1.0  # how often the Exchange stream looks for new rows
    llm_stream_max_seconds: float = 300.0  # a stream closes after this; the browser reconnects with its last event id
    assistant_history_pairs: int = 6  # Question/Answer pairs of earlier turns sent with each Question
    assistant_context_rows: int = 25  # rows of a list screen (the Queue) a Screen Context holds, by the screen's sort
    seed_dir: str = "data/seed"
    cors_origins: list[str] = ["http://localhost:5173"]
