"""Main rule engine that orchestrates rule loading, matching, and execution."""

from typing import Any, Dict, List, Optional, Tuple, Union

from app.rules.actions import RuleActionExecutor
from app.rules.loader import RuleLoader
from app.rules.matchers import RuleMatcher
from app.schemas.models import CanonicalRequest, CanonicalResponse
from app.schemas.rules import Rule, RuleEngineResult, RuleExecutionResult


class RuleEngine:
    """Rule engine for processing requests and responses.

    The engine:
    1. Loads rules from YAML files
    2. Matches rules against requests/responses
    3. Executes actions on matches
    4. Tracks all modifications for audit
    """

    def __init__(self, rules_dir: str, dry_run: bool = False):
        """Initialize the rule engine.

        Args:
            rules_dir: Directory containing YAML rule files
            dry_run: If True, don't actually modify anything
        """
        self.rules_dir = rules_dir
        self.dry_run = dry_run
        self.loader = RuleLoader(rules_dir)

        # Cache for loaded rules
        self._request_rules: Optional[List[Rule]] = None
        self._response_rules: Optional[List[Rule]] = None
        self._passive_rules: Optional[List[Rule]] = None

    def reload_rules(self) -> None:
        """Reload all rules from disk."""
        self._request_rules = None
        self._response_rules = None
        self._passive_rules = None

    def _get_rules(self, scope: str) -> List[Rule]:
        """Get cached rules for a scope."""
        if scope == "request" and self._request_rules is not None:
            return self._request_rules
        if scope == "response" and self._response_rules is not None:
            return self._response_rules
        if scope == "passive" and self._passive_rules is not None:
            return self._passive_rules

        rules = self.loader.get_rules_by_scope(scope)

        if scope == "request":
            self._request_rules = rules
        elif scope == "response":
            self._response_rules = rules
        elif scope == "passive":
            self._passive_rules = rules

        return rules

    def process_request(
        self, request: CanonicalRequest, raw_request: Optional[Dict[str, Any]] = None
    ) -> Tuple[CanonicalRequest, RuleEngineResult]:
        """Process a request through all matching rules.

        Args:
            request: CanonicalRequest to process
            raw_request: Optional raw request for additional context

        Returns:
            Tuple of (processed_request, rule_engine_result)
        """
        rules = self._get_rules("request")
        result = RuleEngineResult()
        current_request = request

        for rule in rules:
            matcher = RuleMatcher(rule)
            if matcher.match_request(current_request, raw_request):
                executor = RuleActionExecutor(rule)
                modified_request, was_modified, description = executor.execute_on_request(
                    current_request, dry_run=self.dry_run
                )

                execution_result = RuleExecutionResult(
                    rule_id=rule.id,
                    matched=True,
                    modified=was_modified,
                    description=rule.description,
                    details=description,
                )
                result.add_result(execution_result)

                if was_modified:
                    current_request = modified_request

        return current_request, result

    def process_response(
        self,
        response: CanonicalResponse,
        request: Optional[CanonicalRequest] = None,
    ) -> Tuple[CanonicalResponse, RuleEngineResult]:
        """Process a response through all matching rules.

        Args:
            response: CanonicalResponse to process
            request: Optional request for context

        Returns:
            Tuple of (processed_response, rule_engine_result)
        """
        rules = self._get_rules("response")
        result = RuleEngineResult()
        current_response = response

        for rule in rules:
            matcher = RuleMatcher(rule)
            if matcher.match_response(current_response, request):
                executor = RuleActionExecutor(rule)
                modified_response, was_modified, description = executor.execute_on_response(
                    current_response, dry_run=self.dry_run
                )

                execution_result = RuleExecutionResult(
                    rule_id=rule.id,
                    matched=True,
                    modified=was_modified,
                    description=rule.description,
                    details=description,
                )
                result.add_result(execution_result)

                if was_modified:
                    current_response = modified_response

        return current_response, result

    def process_passive(
        self,
        target: Union[CanonicalRequest, CanonicalResponse],
        scope: str = "request",
    ) -> RuleEngineResult:
        """Process through passive rules (logging only, no modifications).

        Args:
            target: Request or Response to process
            scope: 'request' or 'response'

        Returns:
            RuleEngineResult with matched passive rules
        """
        rules = self._get_rules("passive")
        result = RuleEngineResult()

        for rule in rules:
            matcher = RuleMatcher(rule)

            # For passive rules, we just check the match
            if scope == "request" and isinstance(target, CanonicalRequest):
                if matcher.match_request(target):
                    # Execute action for metadata collection
                    executor = RuleActionExecutor(rule)
                    if isinstance(target, CanonicalRequest):
                        executor.execute_on_request(target, dry_run=True)
                    else:
                        executor.execute_on_response(target, dry_run=True)

                    execution_result = RuleExecutionResult(
                        rule_id=rule.id,
                        matched=True,
                        modified=False,  # Passive rules don't modify
                        description=rule.description,
                        details=f"Passive match: {rule.description}",
                    )
                    result.add_result(execution_result)

            elif scope == "response" and isinstance(target, CanonicalResponse):
                if matcher.match_response(target):
                    executor = RuleActionExecutor(rule)
                    executor.execute_on_response(target, dry_run=True)

                    execution_result = RuleExecutionResult(
                        rule_id=rule.id,
                        matched=True,
                        modified=False,
                        description=rule.description,
                        details=f"Passive match: {rule.description}",
                    )
                    result.add_result(execution_result)

        return result

    def explain_rules(self, scope: str) -> List[Dict[str, Any]]:
        """Get explanation of all rules for a scope.

        Args:
            scope: Rule scope ('request', 'response', 'passive')

        Returns:
            List of rule descriptions
        """
        rules = self._get_rules(scope)
        return [
            {
                "id": rule.id,
                "enabled": rule.enabled,
                "priority": rule.priority,
                "description": rule.description,
                "match": rule.match.model_dump(exclude_none=True),
                "action": rule.action.model_dump(exclude_none=True),
            }
            for rule in rules
        ]
