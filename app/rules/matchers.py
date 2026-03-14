"""Rule matchers for determining if a rule applies."""

import re
from typing import Any, Dict, List, Optional

from app.schemas.models import CanonicalRequest, CanonicalResponse, Message
from app.schemas.rules import Rule, RuleMatch


class RuleMatcher:
    """Evaluate rule match conditions."""

    def __init__(self, rule: Rule):
        """Initialize the matcher with a rule.

        Args:
            rule: Rule to match against
        """
        self.rule = rule
        self.match = rule.match

    def match_request(
        self,
        request: CanonicalRequest,
        raw_request: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Check if rule matches a request.

        Args:
            request: CanonicalRequest to check
            raw_request: Optional raw request dict for additional matching

        Returns:
            True if rule matches
        """
        return self._match(self.match, request)

    def match_response(
        self,
        response: CanonicalResponse,
        request: Optional[CanonicalRequest] = None,
    ) -> bool:
        """Check if rule matches a response.

        Args:
            response: CanonicalResponse to check
            request: Optional request for context

        Returns:
            True if rule matches
        """
        return self._match(self.match, response)

    def _match(self, match_condition: RuleMatch, target: Any) -> bool:
        """Evaluate match conditions against target.

        Args:
            match_condition: RuleMatch conditions
            target: Target to match against (request or response)

        Returns:
            True if all conditions match
        """
        # Check path
        if match_condition.path is not None:
            if not self._match_path(match_condition.path, target):
                return False

        # Check provider
        if match_condition.provider is not None:
            if not self._match_provider(match_condition.provider, target):
                return False

        # Check model
        if match_condition.model is not None:
            if not self._match_model(match_condition.model, target):
                return False

        # Check keyword
        if match_condition.keyword is not None:
            if not self._match_keyword(match_condition.keyword, target):
                return False

        # Check regex
        if match_condition.regex is not None:
            if not self._match_regex(match_condition.regex, target):
                return False

        # Check role
        if match_condition.role is not None:
            if not self._match_role(match_condition.role, target):
                return False

        return True

    def _match_path(self, pattern: str, target: Any) -> bool:
        """Match against API path."""
        # Path matching is typically done at routing level
        # For now, we skip this check in match_request/match_response
        return True

    def _match_provider(self, provider: str, target: Any) -> bool:
        """Match against provider name."""
        if isinstance(target, CanonicalRequest):
            return target.provider.lower() == provider.lower()
        if isinstance(target, CanonicalResponse):
            return target.provider.lower() == provider.lower()
        return False

    def _match_model(self, model: str, target: Any) -> bool:
        """Match against model name."""
        target_model = ""
        if isinstance(target, CanonicalRequest):
            target_model = target.model
        elif isinstance(target, CanonicalResponse):
            target_model = target.model

        if not target_model:
            return False

        # Case-insensitive substring match
        return model.lower() in target_model.lower()

    def _match_keyword(self, keyword: str, target: Any) -> bool:
        """Match against keyword in content."""
        content = self._extract_content(target)
        if not content:
            return False

        return keyword.lower() in content.lower()

    def _match_regex(self, pattern: str, target: Any) -> bool:
        """Match against regex pattern in content."""
        content = self._extract_content(target)
        if not content:
            return False

        try:
            return bool(re.search(pattern, content, re.IGNORECASE))
        except re.error:
            return False

    def _match_role(self, role: str, target: Any) -> bool:
        """Match against message role."""
        # For requests, check if any message has the role
        if isinstance(target, CanonicalRequest):
            for msg in target.messages:
                if msg.role.lower() == role.lower():
                    return True
            # Also check system
            if role.lower() == "system" and target.system:
                return True
            return False

        # For responses, check the role
        if isinstance(target, CanonicalResponse):
            return target.role.lower() == role.lower()

        return False

    def _extract_content(self, target: Any) -> str:
        """Extract text content from target for keyword/regex matching."""
        content_parts = []

        if isinstance(target, CanonicalRequest):
            # Extract from system
            if target.system:
                content_parts.append(target.system)

            # Extract from messages
            for msg in target.messages:
                if isinstance(msg.content, str):
                    content_parts.append(msg.content)
                elif hasattr(msg.content, "__iter__"):
                    for block in msg.content:
                        if hasattr(block, "text") and block.text:
                            content_parts.append(block.text)

        elif isinstance(target, CanonicalResponse):
            if isinstance(target.content, str):
                content_parts.append(target.content)
            elif hasattr(target.content, "__iter__"):
                for block in target.content:
                    if hasattr(block, "text") and block.text:
                        content_parts.append(block.text)

        return " ".join(content_parts)
