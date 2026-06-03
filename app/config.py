from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str
    SESSION_SECRET: str
    FOOTBALL_API_KEY: str = ""
    FOOTBALL_API_BASE_URL: str = "https://sports.bzzoiro.com/api/v2"
    FOOTBALL_LEAGUE_ID: int = 27
    # Optional: map date ranges to round names for leagues that return empty round_name.
    # Used in staging to simulate World Cup round structure with a live active league.
    # Format: JSON array, e.g. [{"from":"2026-06-01","to":"2026-06-07","name":"Group Stage"}]
    # Leave unset in production — World Cup provides its own round names via the API.
    ROUND_DATE_RULES: list[dict[str, str]] = []
    TASK_SECRET: str
    DEBUG: bool = False


settings = Settings()
