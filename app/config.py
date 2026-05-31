from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str
    SESSION_SECRET: str
    FOOTBALL_API_KEY: str = ""
    FOOTBALL_API_BASE_URL: str = "https://sports.bzzoiro.com/api/v2"
    FOOTBALL_LEAGUE_ID: int = 27
    TASK_SECRET: str
    DEBUG: bool = False


settings = Settings()
