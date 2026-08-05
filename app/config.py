from functools import lru_cache
from pathlib import Path
import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "sqlite:///./media_monitor.db"
    google_api_key: str = ""
    google_cse_id: str = ""
    instagram_access_token: str = ""
    instagram_user_id: str = ""
    instagram_graph_version: str = "v23.0"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    report_to: str = ""
    report_from: str = ""
    dashboard_user: str = "equipe"
    dashboard_password: str = ""
    dashboard_owner_username: str = ""
    dashboard_owner_email: str = ""
    dashboard_additional_admin_usernames: str = ""
    dashboard_public_url: str = "http://localhost:4200"
    dashboard_session_days: int = 7
    dashboard_cache_seconds: int = 60
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

@lru_cache
def settings() -> Settings:
    return Settings()

def yaml_config(name: str) -> dict:
    with (ROOT / "config" / name).open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)
