from pydantic import Field, PositiveInt
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
    llm_base_url: str = "https://openrouter.ai/api/v1/"  # any OpenAI-compatible endpoint (OpenRouter, LiteLLM, ...)
    llm_model: str = "anthropic/claude-sonnet-5.5"  # in the gateway's naming
    # Sent only when set. Claude 5 models accept no temperature, and through OpenRouter a request carrying one finds no
    # endpoint, so the default leaves it to the provider. Reported on the governance model card.
    llm_temperature: float | None = None
    llm_recordings_dir: str = "data/llm_recordings"
    llm_record: bool = False  # live mode only: save each model request's reply as a recording
    llm_stream_poll_seconds: float = 1.0  # how often the Exchange stream looks for new rows
    llm_stream_max_seconds: float = 300.0  # a stream closes after this; the browser reconnects with its last event id
    # The Assistant's limits. Each description is the "Effect" column of the generated table in the architecture
    # document (docs/architecture/08-crosscutting-concepts.md), so keep it a sentence a reviewer can read.
    assistant_history_pairs: int = Field(
        default=6, description="Question/Answer pairs of earlier turns sent with each Question"
    )
    assistant_context_rows: int = Field(
        default=25, description="Rows of a list screen (the Queue) a Screen Context holds, by the screen's sort"
    )
    assistant_question_max_chars: PositiveInt = Field(default=2000, description="A longer Question is refused with 400")
    assistant_questions_per_conversation: PositiveInt = Field(
        default=50, description="Questions a Conversation takes; then 429 until the next login"
    )
    assistant_questions_per_hour: PositiveInt = Field(
        default=20, description="Questions a user may ask in any rolling hour; then 429"
    )
    assistant_request_limit: PositiveInt = Field(
        default=6, description="Model requests one Answer may make, lookups and self-correction included; then it fails"
    )
    assistant_eval_path: str = "data/assistant_eval.json"  # latest live eval results, shown on the model card
    seed_dir: str = "data/seed"
    cors_origins: list[str] = ["http://localhost:5173"]
