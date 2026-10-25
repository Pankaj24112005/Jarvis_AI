"""Configuration management for JARVIS using Pydantic Settings."""

import os
from pathlib import Path
from typing import Literal
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # Gemini API Configuration
    gemini_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias="GEMINI_API_KEY",
        description="Google Gemini API key",
    )
    gemini_primary_model: str = Field(
        default="gemini-3.8-flash",
        validation_alias="GEMINI_PRIMARY_MODEL",
        description="Default reasoning model",
    )
    gemini_fast_model: str = Field(
        default="gemini-3.6-flash",
        validation_alias="GEMINI_FAST_MODEL",
        description="Fast low-latency model",
    )
    gemini_embedding_model: str = Field(
        default="text-embedding-004",
        validation_alias="GEMINI_EMBEDDING_MODEL",
        description="Text embedding model",
    )

    # Assistant Persona
    jarvis_name: str = Field(
        default="JARVIS",
        validation_alias="JARVIS_NAME",
        description="Name of the assistant",
    )
    user_name: str = Field(
        default="Sir",
        validation_alias="USER_NAME",
        description="Name/title of the user",
    )

    # Feature Toggles
    voice_enabled: bool = Field(default=False, validation_alias="VOICE_ENABLED")
    vision_enabled: bool = Field(default=False, validation_alias="VISION_ENABLED")
    gesture_enabled: bool = Field(default=False, validation_alias="GESTURE_ENABLED")
    web_hud_enabled: bool = Field(default=False, validation_alias="WEB_HUD_ENABLED")
    web_hud_host: str = Field(
        default="127.0.0.1",
        validation_alias="WEB_HUD_HOST",
        description="Local interface host for HUD server",
    )
    web_hud_port: int = Field(
        default=8000,
        validation_alias="WEB_HUD_PORT",
        description="Port for HUD server",
    )
    web_hud_auto_open: bool = Field(
        default=True,
        validation_alias="WEB_HUD_AUTO_OPEN",
        description="Whether to automatically launch HUD in browser",
    )

    # Voice Configuration
    gemini_live_voice: str = Field(
        default="Charon",
        validation_alias="GEMINI_LIVE_VOICE",
        description="Prebuilt voice name for Gemini Live (e.g. Charon, Orus, Gacrux, Puck, Aoede)",
    )

    # Security & Permission threshold (0 to 4)
    permission_confirmation_threshold: int = Field(
        default=3,
        validation_alias="PERMISSION_CONFIRMATION_THRESHOLD",
        description="Permission level that triggers mandatory human confirmation",
    )

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO", validation_alias="LOG_LEVEL"
    )
    debug: bool = Field(default=False, validation_alias="DEBUG")

    @property
    def is_gemini_configured(self) -> bool:
        """Check whether a non-empty Gemini API key is configured."""
        val = self.gemini_api_key.get_secret_value()
        return bool(val and val.strip() and val.strip() != "your_gemini_api_key_here")

    def get_gemini_api_key(self) -> str:
        """Safely retrieve the raw API key without exposing it in logs."""
        return self.gemini_api_key.get_secret_value()


_settings_instance: Settings | None = None


def get_settings(reload: bool = False) -> Settings:
    """Get or create singleton Settings instance."""
    global _settings_instance
    if _settings_instance is None or reload:
        _settings_instance = Settings()
    return _settings_instance
