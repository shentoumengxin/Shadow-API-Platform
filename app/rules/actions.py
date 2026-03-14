"""Rule actions for modifying requests and responses."""

import re
from typing import Any, Dict, List, Optional, Tuple, Union

from app.schemas.models import CanonicalRequest, CanonicalResponse, Message
from app.schemas.rules import Rule, RuleAction


class RuleActionExecutor:
    """Execute rule actions on requests and responses."""

    def __init__(self, rule: Rule):
        """Initialize the executor with a rule.

        Args:
            rule: Rule containing the action to execute
        """
        self.rule = rule
        self.action = rule.action

    def execute_on_request(
        self, request: CanonicalRequest, dry_run: bool = False
    ) -> Tuple[CanonicalRequest, bool, Optional[str]]:
        """Execute action on a request.

        Args:
            request: CanonicalRequest to modify
            dry_run: If True, don't actually modify

        Returns:
            Tuple of (modified_request, was_modified, description)
        """
        if self.action.type == "no_op":
            return request, False, None

        if dry_run:
            return request, True, f"[DRY_RUN] Would apply {self.action.type}"

        modified_request = request.model_copy(deep=True)
        modified, description = self._execute(self.action, modified_request)

        return modified_request, modified, description

    def execute_on_response(
        self, response: CanonicalResponse, dry_run: bool = False
    ) -> Tuple[CanonicalResponse, bool, Optional[str]]:
        """Execute action on a response.

        Args:
            response: CanonicalResponse to modify
            dry_run: If True, don't actually modify

        Returns:
            Tuple of (modified_response, was_modified, description)
        """
        if self.action.type == "no_op":
            return response, False, None

        if dry_run:
            return response, True, f"[DRY_RUN] Would apply {self.action.type}"

        modified_response = response.model_copy(deep=True)
        modified, description = self._execute(self.action, modified_response)

        return modified_response, modified, description

    def _execute(
        self, action: RuleAction, target: Union[CanonicalRequest, CanonicalResponse]
    ) -> Tuple[bool, Optional[str]]:
        """Execute the action on the target.

        Args:
            action: RuleAction to execute
            target: Target to modify

        Returns:
            Tuple of (was_modified, description)
        """
        action_type = action.type

        if action_type == "append_text":
            return self._append_text(action, target)

        elif action_type == "replace_text":
            return self._replace_text(action, target)

        elif action_type == "remove_field":
            return self._remove_field(action, target)

        elif action_type == "mask_field":
            return self._mask_field(action, target)

        elif action_type == "add_header":
            return self._add_header(action, target)

        elif action_type == "add_metadata":
            return self._add_metadata(action, target)

        elif action_type == "set_model":
            return self._set_model(action, target)

        elif action_type == "no_op":
            return False, None

        return False, None

    def _append_text(
        self, action: RuleAction, target: Union[CanonicalRequest, CanonicalResponse]
    ) -> Tuple[bool, Optional[str]]:
        """Append text to content."""
        text_to_append = action.text or ""
        target_field = action.target or "content"

        if isinstance(target, CanonicalRequest):
            # Append to system message
            if target_field == "system" and target.system:
                original = target.system
                target.system = original + text_to_append
                return True, f"Appended to system prompt"

            # Append to messages
            if target_field == "content":
                modified_count = 0
                for msg in target.messages:
                    if isinstance(msg.content, str):
                        msg.content = msg.content + text_to_append
                        modified_count += 1
                if modified_count > 0:
                    return True, f"Appended to {modified_count} message(s)"

        elif isinstance(target, CanonicalResponse):
            if isinstance(target.content, str):
                target.content = target.content + text_to_append
                return True, "Appended to response content"

        return False, None

    def _replace_text(
        self, action: RuleAction, target: Union[CanonicalRequest, CanonicalResponse]
    ) -> Tuple[bool, Optional[str]]:
        """Replace text in content."""
        original = action.original or ""
        replacement = action.replacement or ""

        if isinstance(target, CanonicalRequest):
            # Replace in system message
            if target.system and original in target.system:
                target.system = target.system.replace(original, replacement)
                return True, f"Replaced '{original}' in system prompt"

            # Replace in messages
            modified_count = 0
            for msg in target.messages:
                if isinstance(msg.content, str) and original in msg.content:
                    msg.content = msg.content.replace(original, replacement)
                    modified_count += 1
            if modified_count > 0:
                return True, f"Replaced '{original}' in {modified_count} message(s)"

        elif isinstance(target, CanonicalResponse):
            if isinstance(target.content, str) and original in target.content:
                target.content = target.content.replace(original, replacement)
                return True, f"Replaced '{original}' in response"

        return False, None

    def _remove_field(
        self, action: RuleAction, target: Union[CanonicalRequest, CanonicalResponse]
    ) -> Tuple[bool, Optional[str]]:
        """Remove a field from the target."""
        field = action.field

        if not field:
            return False, None

        # For response, we can remove from metadata or usage
        if isinstance(target, CanonicalResponse):
            if field == "usage" and target.usage:
                target.usage = None
                return True, "Removed usage field"
            if field in target.metadata:
                del target.metadata[field]
                return True, f"Removed metadata field '{field}'"

        # For request, we can remove from metadata
        if isinstance(target, CanonicalRequest):
            if field in target.metadata:
                del target.metadata[field]
                return True, f"Removed metadata field '{field}'"

        return False, None

    def _mask_field(
        self, action: RuleAction, target: Union[CanonicalRequest, CanonicalResponse]
    ) -> Tuple[bool, Optional[str]]:
        """Mask a field value."""
        field_pattern = action.field_pattern or "api_key"
        mask_char = action.mask_char or "*"

        if isinstance(target, CanonicalRequest):
            # Search for field pattern in content
            modified_count = 0
            for msg in target.messages:
                if isinstance(msg.content, str):
                    # Simple masking - replace values after field pattern
                    pattern = rf"({field_pattern}['\"]?\s*[:=]\s*['\"]?)([^'\"\\s,}}]+)"
                    masked = re.sub(
                        pattern,
                        lambda m: m.group(1) + mask_char * 8,
                        msg.content,
                        flags=re.IGNORECASE,
                    )
                    if masked != msg.content:
                        msg.content = masked
                        modified_count += 1

            if modified_count > 0:
                return True, f"Masked {modified_count} field(s) matching '{field_pattern}'"

        return False, None

    def _add_header(
        self, action: RuleAction, target: Union[CanonicalRequest, CanonicalResponse]
    ) -> Tuple[bool, Optional[str]]:
        """Add a header to the request."""
        header_name = action.header_name
        header_value = action.header_value

        if not header_name:
            return False, None

        if isinstance(target, CanonicalRequest):
            target.headers[header_name] = header_value or ""
            return True, f"Added header '{header_name}'"

        return False, None

    def _add_metadata(
        self, action: RuleAction, target: Union[CanonicalRequest, CanonicalResponse]
    ) -> Tuple[bool, Optional[str]]:
        """Add metadata to the target."""
        key = action.key
        value = action.value

        if not key:
            return False, None

        # Replace ${model} placeholder if present
        if value and "${model}" in value:
            if isinstance(target, CanonicalRequest):
                value = value.replace("${model}", target.model)
            elif isinstance(target, CanonicalResponse):
                value = value.replace("${model}", target.model)

        target.metadata[key] = value or ""
        return True, f"Added metadata '{key}={value}'"

    def _set_model(
        self, action: RuleAction, target: Union[CanonicalRequest, CanonicalResponse]
    ) -> Tuple[bool, Optional[str]]:
        """Set/replace the model name."""
        new_model = action.model

        if not new_model:
            return False, None

        # Only applies to CanonicalRequest
        if isinstance(target, CanonicalRequest):
            original_model = target.model
            target.model = new_model
            return True, f"Changed model from '{original_model}' to '{new_model}'"

        return False, None
