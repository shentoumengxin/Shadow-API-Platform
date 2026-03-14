"""Base adapter interface for all providers."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple

import httpx

from app.schemas.models import CanonicalRequest, CanonicalResponse


class BaseAdapter(ABC):
    """Abstract base class for provider adapters.

    Each adapter is responsible for:
    - Converting incoming requests to provider-specific format
    - Converting provider responses back to canonical format
    - Handling provider-specific authentication and headers
    """

    def __init__(self, api_key: str, base_url: str):
        """Initialize the adapter.

        Args:
            api_key: API key for the provider
            base_url: Base URL for the provider API
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    @abstractmethod
    def get_provider_name(self) -> str:
        """Return the provider name."""
        pass

    @abstractmethod
    def normalize_to_canonical(self, raw_request: Dict[str, Any]) -> CanonicalRequest:
        """Convert provider-specific request to canonical format.

        Args:
            raw_request: Raw request dictionary from client

        Returns:
            CanonicalRequest object for internal processing
        """
        pass

    @abstractmethod
    def denormalize_from_canonical(
        self, canonical_request: CanonicalRequest
    ) -> Tuple[str, Dict[str, Any], Dict[str, str]]:
        """Convert canonical request to provider-specific format.

        Args:
            canonical_request: CanonicalRequest object

        Returns:
            Tuple of (endpoint_url, request_body_dict, headers_dict)
        """
        pass

    @abstractmethod
    def normalize_response(
        self, provider_response: Dict[str, Any], canonical_request: CanonicalRequest
    ) -> CanonicalResponse:
        """Convert provider response to canonical format.

        Args:
            provider_response: Raw response from provider
            canonical_request: The original canonical request (for context)

        Returns:
            CanonicalResponse object
        """
        pass

    @abstractmethod
    def denormalize_response(
        self, canonical_response: CanonicalResponse, original_request: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Convert canonical response back to provider-specific format.

        This is used when returning response to client - we want to maintain
        the format the client expects.

        Args:
            canonical_response: CanonicalResponse from internal processing
            original_request: Original request from client (for context)

        Returns:
            Response dictionary in provider-specific format
        """
        pass

    def create_http_client(self, timeout: float = 60.0) -> httpx.AsyncClient:
        """Create an HTTP client with default settings.

        Args:
            timeout: Request timeout in seconds

        Returns:
            Configured httpx.AsyncClient
        """
        return httpx.AsyncClient(timeout=timeout)

    def get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers for the provider.

        Returns:
            Dictionary of authentication headers
        """
        return {"Authorization": f"Bearer {self.api_key}"}

    def get_default_headers(self) -> Dict[str, str]:
        """Get default headers for the provider.

        Returns:
            Dictionary of default headers
        """
        return {
            "Content-Type": "application/json",
            **self.get_auth_headers(),
        }

    async def invoke(
        self,
        canonical_request: CanonicalRequest,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Tuple[CanonicalResponse, Dict[str, Any]]:
        """Invoke the provider API.

        Args:
            canonical_request: Canonical request to send
            extra_headers: Additional headers to include

        Returns:
            Tuple of (CanonicalResponse, raw_provider_response)
        """
        endpoint, body, headers = self.denormalize_from_canonical(canonical_request)

        # Merge extra headers
        if extra_headers:
            headers.update(extra_headers)

        async with self.create_http_client() as client:
            response = await client.post(endpoint, headers=headers, json=body)
            response.raise_for_status()
            provider_response = response.json()

        canonical_response = self.normalize_response(provider_response, canonical_request)
        return canonical_response, provider_response
