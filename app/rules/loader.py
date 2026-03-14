"""YAML rule loader."""

import os
from pathlib import Path
from typing import List, Optional

import yaml

from app.schemas.rules import Rule, RuleSet


class RuleLoader:
    """Load rules from YAML files."""

    def __init__(self, rules_dir: str):
        """Initialize the rule loader.

        Args:
            rules_dir: Directory containing YAML rule files
        """
        self.rules_dir = Path(rules_dir)

    def load_file(self, filename: str) -> Optional[RuleSet]:
        """Load rules from a single YAML file.

        Args:
            filename: Name of the YAML file

        Returns:
            RuleSet or None if file doesn't exist
        """
        filepath = self.rules_dir / filename

        if not filepath.exists():
            return None

        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data:
            return RuleSet(rules=[])

        return RuleSet(**data)

    def load_all(self) -> List[RuleSet]:
        """Load all rule files from the rules directory.

        Returns:
            List of RuleSet objects
        """
        rule_sets = []

        # Default rule files
        default_files = ["request.yaml", "response.yaml", "passive.yaml"]

        for filename in default_files:
            rule_set = self.load_file(filename)
            if rule_set:
                rule_sets.append(rule_set)

        # Also load any other YAML files in the directory
        if self.rules_dir.exists():
            for filepath in self.rules_dir.glob("*.yaml"):
                if filepath.name not in default_files:
                    rule_set = self.load_file(filepath.name)
                    if rule_set:
                        rule_sets.append(rule_set)

        return rule_sets

    def get_rules_by_scope(self, scope: str) -> List[Rule]:
        """Get all rules for a specific scope, sorted by priority.

        Args:
            scope: Rule scope ('request', 'response', 'passive')

        Returns:
            List of Rule objects sorted by priority (descending)
        """
        all_rules = []

        for rule_set in self.load_all():
            for rule in rule_set.rules:
                if rule.enabled and rule.scope == scope:
                    all_rules.append(rule)

        # Sort by priority (highest first)
        all_rules.sort(key=lambda r: r.priority, reverse=True)

        return all_rules

    def reload(self) -> None:
        """Reload all rules (called when rules change)."""
        # Clear any caches if implemented
        pass

    @staticmethod
    def validate_rule(rule_data: dict) -> bool:
        """Validate a rule definition.

        Args:
            rule_data: Raw rule dictionary

        Returns:
            True if valid

        Raises:
            ValueError: If rule is invalid
        """
        try:
            Rule(**rule_data)
            return True
        except Exception as e:
            raise ValueError(f"Invalid rule: {e}")
