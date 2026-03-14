"""Configuration management for LLM Research Proxy."""

import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    """Server configuration."""

    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8765, description="Server port")


class ProviderConfig(BaseModel):
    """Upstream provider configuration."""

    api_key: Optional[str] = Field(default=None, description="API key")
    base_url: Optional[str] = Field(default=None, description="Base URL")


class ProvidersConfig(BaseModel):
    """All provider configurations."""

    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)


class TraceConfig(BaseModel):
    """Trace and logging configuration."""

    enabled: bool = Field(default=True, description="Enable trace logging")
    dry_run: bool = Field(default=False, description="Dry run mode - no modifications")
    log_level: str = Field(default="INFO", description="Logging level")


class Config(BaseModel):
    """Main application configuration."""

    server: ServerConfig = Field(default_factory=ServerConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    trace: TraceConfig = Field(default_factory=TraceConfig)
    rules_dir: str = Field(default="rules", description="Rules directory path")

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        return cls(
            server=ServerConfig(
                host=os.getenv("HOST", "0.0.0.0"),
                port=int(os.getenv("PORT", "8765")),
            ),
            providers=ProvidersConfig(
                openai=ProviderConfig(
                    api_key=os.getenv("OPENAI_API_KEY"),
                    base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                ),
                anthropic=ProviderConfig(
                    api_key=os.getenv("ANTHROPIC_API_KEY"),
                    base_url=os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
                ),
            ),
            trace=TraceConfig(
                enabled=os.getenv("TRACE_ENABLED", "true").lower() == "true",
                dry_run=os.getenv("DRY_RUN", "false").lower() == "true",
                log_level=os.getenv("LOG_LEVEL", "INFO"),
            ),
            rules_dir=os.getenv("RULES_DIR", "rules"),
        )

    @property
    def rules_dir_path(self) -> Path:
        """Get absolute path to rules directory."""
        return Path(self.rules_dir)
