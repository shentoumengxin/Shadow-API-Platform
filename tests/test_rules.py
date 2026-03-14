"""Rule loader tests."""

import tempfile
from pathlib import Path

import pytest
import yaml

from app.rules.loader import RuleLoader


class TestRuleLoader:
    """Tests for YAML rule loading."""

    def test_load_single_file(self):
        """Test loading a single rule file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rules_dir = Path(tmpdir)

            # Create test rule file
            rule_data = {
                "rules": [
                    {
                        "id": "test_rule",
                        "enabled": True,
                        "priority": 50,
                        "scope": "request",
                        "description": "Test rule",
                        "match": {"role": "user"},
                        "action": {"type": "no_op"},
                    }
                ]
            }

            rule_file = rules_dir / "request.yaml"
            with open(rule_file, "w") as f:
                yaml.dump(rule_data, f)

            loader = RuleLoader(str(rules_dir))
            rule_set = loader.load_file("request.yaml")

            assert rule_set is not None
            assert len(rule_set.rules) == 1
            assert rule_set.rules[0].id == "test_rule"

    def test_load_nonexistent_file(self):
        """Test loading nonexistent file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = RuleLoader(str(tmpdir))
            rule_set = loader.load_file("nonexistent.yaml")
            assert rule_set is None

    def test_get_rules_by_scope(self):
        """Test getting rules by scope."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rules_dir = Path(tmpdir)

            # Create rule files for each scope
            for scope in ["request", "response", "passive"]:
                rule_data = {
                    "rules": [
                        {
                            "id": f"{scope}_rule",
                            "enabled": True,
                            "priority": 50,
                            "scope": scope,
                            "description": f"{scope} rule",
                            "match": {"role": "user"} if scope == "request" else {},
                            "action": {"type": "no_op"},
                        }
                    ]
                }

                rule_file = rules_dir / f"{scope}.yaml"
                with open(rule_file, "w") as f:
                    yaml.dump(rule_data, f)

            loader = RuleLoader(str(rules_dir))

            request_rules = loader.get_rules_by_scope("request")
            assert len(request_rules) == 1
            assert request_rules[0].id == "request_rule"

            response_rules = loader.get_rules_by_scope("response")
            assert len(response_rules) == 1
            assert response_rules[0].id == "response_rule"

    def test_priority_sorting(self):
        """Test that rules are sorted by priority."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rules_dir = Path(tmpdir)

            rule_data = {
                "rules": [
                    {
                        "id": "low_priority",
                        "enabled": True,
                        "priority": 10,
                        "scope": "request",
                        "description": "Low priority",
                        "match": {"role": "user"},
                        "action": {"type": "no_op"},
                    },
                    {
                        "id": "high_priority",
                        "enabled": True,
                        "priority": 100,
                        "scope": "request",
                        "description": "High priority",
                        "match": {"role": "user"},
                        "action": {"type": "no_op"},
                    },
                    {
                        "id": "mid_priority",
                        "enabled": True,
                        "priority": 50,
                        "scope": "request",
                        "description": "Mid priority",
                        "match": {"role": "user"},
                        "action": {"type": "no_op"},
                    },
                ]
            }

            rule_file = rules_dir / "request.yaml"
            with open(rule_file, "w") as f:
                yaml.dump(rule_data, f)

            loader = RuleLoader(str(rules_dir))
            rules = loader.get_rules_by_scope("request")

            assert len(rules) == 3
            assert rules[0].priority == 100  # Highest first
            assert rules[1].priority == 50
            assert rules[2].priority == 10

    def test_disabled_rules_not_loaded(self):
        """Test that disabled rules are not returned."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rules_dir = Path(tmpdir)

            rule_data = {
                "rules": [
                    {
                        "id": "enabled_rule",
                        "enabled": True,
                        "priority": 50,
                        "scope": "request",
                        "description": "Enabled",
                        "match": {"role": "user"},
                        "action": {"type": "no_op"},
                    },
                    {
                        "id": "disabled_rule",
                        "enabled": False,
                        "priority": 50,
                        "scope": "request",
                        "description": "Disabled",
                        "match": {"role": "user"},
                        "action": {"type": "no_op"},
                    },
                ]
            }

            rule_file = rules_dir / "request.yaml"
            with open(rule_file, "w") as f:
                yaml.dump(rule_data, f)

            loader = RuleLoader(str(rules_dir))
            rules = loader.get_rules_by_scope("request")

            assert len(rules) == 1
            assert rules[0].id == "enabled_rule"
