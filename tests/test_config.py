"""Configuration tests."""

import os
from unittest.mock import patch

import pytest

from app.config import Config, ProviderConfig, ProvidersConfig, ServerConfig, TraceConfig


class TestConfig:
    """Tests for configuration loading."""

    def test_default_config(self):
        """Test default configuration."""
        config = Config()

        assert config.server.host == "0.0.0.0"
        assert config.server.port == 8765
        assert config.trace.enabled is True
        assert config.trace.dry_run is False

    def test_config_from_env(self):
        """Test loading config from environment."""
        with patch.dict(
            os.environ,
            {
                "HOST": "127.0.0.1",
                "PORT": "9999",
                "OPENAI_API_KEY": "test-key",
                "OPENAI_BASE_URL": "https://custom.openai.api",
                "TRACE_ENABLED": "false",
                "DRY_RUN": "true",
            },
        ):
            config = Config.from_env()

            assert config.server.host == "127.0.0.1"
            assert config.server.port == 9999
            assert config.providers.openai.api_key == "test-key"
            assert config.trace.enabled is False
            assert config.trace.dry_run is True

    def test_server_config_validation(self):
        """Test server configuration."""
        server = ServerConfig(host="localhost", port=8080)
        assert server.host == "localhost"
        assert server.port == 8080

    def test_provider_config(self):
        """Test provider configuration."""
        provider = ProviderConfig(api_key="test", base_url="https://api.test.com")
        assert provider.api_key == "test"
        assert provider.base_url == "https://api.test.com"

    def test_trace_config(self):
        """Test trace configuration."""
        trace = TraceConfig(enabled=False, dry_run=True, log_level="DEBUG")
        assert trace.enabled is False
        assert trace.dry_run is True
        assert trace.log_level == "DEBUG"
