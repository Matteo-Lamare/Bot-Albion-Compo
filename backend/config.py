"""Configuration de l'application, chargée depuis l'environnement / .env."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


class Settings:
    def __init__(self) -> None:
        self.app_name: str = os.getenv("APP_NAME", "Compos Albion Online")
        self.secret_key: str = os.getenv("SECRET_KEY", "dev-secret-change-me")
        self.database_url: str = os.getenv(
            "DATABASE_URL", f"sqlite:///{BASE_DIR / 'database' / 'compos.db'}"
        )
        # Webhook par defaut ; l'admin peut le surcharger depuis l'interface
        # (la valeur en base prend le pas sur celle-ci).
        self.discord_webhook_url: str = os.getenv("DISCORD_WEBHOOK_URL", "")
        self.admin_pseudo: str = os.getenv("ADMIN_PSEUDO", "admin")
        self.admin_password: str = os.getenv("ADMIN_PASSWORD", "admin")
        self.session_max_age: int = int(os.getenv("SESSION_MAX_AGE", "604800"))
        self.cookie_secure: bool = os.getenv("COOKIE_SECURE", "false").lower() == "true"

    @property
    def base_dir(self) -> Path:
        return BASE_DIR


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
