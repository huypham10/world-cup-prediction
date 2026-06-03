import json
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str
    SESSION_SECRET: str
    FOOTBALL_API_KEY: str = ""
    FOOTBALL_API_BASE_URL: str = "https://sports.bzzoiro.com/api/v2"
    FOOTBALL_LEAGUE_ID: int = 27
    # Optional: JSON array mapping date ranges to round names for leagues with empty round_name.
    # Stored as a raw string so pydantic-settings doesn't attempt its own list coercion.
    # Dates compared against UTC kickoff times. Leave unset in production.
    # e.g. [{"from":"2026-06-01","to":"2026-06-07","name":"Group Stage"},...]
    ROUND_DATE_RULES: str = ""
    TASK_SECRET: str
    DEBUG: bool = False

    @property
    def round_date_rules(self) -> list[dict[str, str]]:
        """Parsed ROUND_DATE_RULES — empty list when unset."""
        if not self.ROUND_DATE_RULES.strip():
            return []
        return json.loads(self.ROUND_DATE_RULES)


settings = Settings()
