"""Rule-related schemas for the rule engine."""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class RuleMatch(BaseModel):
    """Match conditions for a rule."""

    path: Optional[str] = Field(default=None, description="API path pattern")
    provider: Optional[str] = Field(default=None, description="Provider name")
    model: Optional[str] = Field(default=None, description="Model name pattern")
    keyword: Optional[str] = Field(default=None, description="Keyword to match")
    regex: Optional[str] = Field(default=None, description="Regex pattern")
    role: Optional[str] = Field(default=None, description="Message role")

    class Config:
        extra = "allow"


class RuleAction(BaseModel):
    """Action to take when rule matches."""

    type: Literal[
        "append_text",
        "replace_text",
        "remove_field",
        "mask_field",
        "add_header",
        "add_metadata",
        "set_model",
        "no_op",
    ]
    target: Optional[str] = Field(default=None, description="Target field for modification")
    text: Optional[str] = Field(default=None, description="Text to append")
    original: Optional[str] = Field(default=None, description="Original text for replacement")
    replacement: Optional[str] = Field(default=None, description="Replacement text")
    field: Optional[str] = Field(default=None, description="Field to remove")
    field_pattern: Optional[str] = Field(default=None, description="Field pattern to mask")
    mask_char: Optional[str] = Field(default="*", description="Character for masking")
    header_name: Optional[str] = Field(default=None, description="Header name to add")
    header_value: Optional[str] = Field(default=None, description="Header value to add")
    key: Optional[str] = Field(default=None, description="Metadata key")
    value: Optional[str] = Field(default=None, description="Metadata value")
    model: Optional[str] = Field(default=None, description="Model name to set (for set_model action)")

    class Config:
        extra = "allow"


class Rule(BaseModel):
    """A single rule definition."""

    id: str
    enabled: bool = True
    priority: int = Field(default=50, ge=0, le=1000)
    scope: Literal["request", "response", "passive"]
    description: str = ""
    match: RuleMatch
    action: RuleAction

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: int) -> int:
        """Ensure priority is in valid range."""
        if v < 0 or v > 1000:
            raise ValueError("Priority must be between 0 and 1000")
        return v


class RuleSet(BaseModel):
    """A set of rules loaded from YAML."""

    rules: List[Rule] = Field(default_factory=list)


class RuleExecutionResult(BaseModel):
    """Result of applying a single rule."""

    rule_id: str
    matched: bool
    modified: bool
    description: str
    details: Optional[str] = None


class RuleEngineResult(BaseModel):
    """Result of running the rule engine."""

    matched_rules: List[RuleExecutionResult] = Field(default_factory=list)
    modified: bool = False
    modifications: List[str] = Field(default_factory=list)

    def add_result(self, result: RuleExecutionResult) -> None:
        """Add a rule execution result."""
        self.matched_rules.append(result)
        if result.modified:
            self.modified = True
            if result.details:
                self.modifications.append(f"{result.rule_id}: {result.details}")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "matched_rules": [
                {
                    "rule_id": r.rule_id,
                    "matched": r.matched,
                    "modified": r.modified,
                    "description": r.description,
                    "details": r.details,
                }
                for r in self.matched_rules
            ],
            "modified": self.modified,
            "modifications": self.modifications,
        }
