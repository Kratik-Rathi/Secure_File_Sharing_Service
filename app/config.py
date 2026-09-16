from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str
    secret_key: str
    storage_path: str
    environment: str = "development"
    jwt_expire_minutes: int = 60

    @property
    def is_development(self) -> bool:
        return self.environment.lower() == "development"


settings = Settings()
