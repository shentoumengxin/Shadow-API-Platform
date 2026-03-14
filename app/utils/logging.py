"""Logging utilities."""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Set up logging configuration.

    Args:
        level: Logging level

    Returns:
        Configured logger
    """
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    return logging.getLogger("llm_research_proxy")


class JsonlWriter:
    """Write logs to JSONL files."""

    def __init__(self, filepath: str):
        """Initialize the JSONL writer.

        Args:
            filepath: Path to the JSONL file
        """
        self.filepath = Path(filepath)
        self.filepath.parent.mkdir(parents=True, exist_ok=True)

    def write(self, data: Dict[str, Any]) -> None:
        """Write a record to the JSONL file.

        Args:
            data: Dictionary to write as JSON
        """
        with open(self.filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, default=str) + "\n")

    def read_all(self) -> list:
        """Read all records from the file.

        Returns:
            List of dictionaries
        """
        records = []
        if self.filepath.exists():
            with open(self.filepath, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        records.append(json.loads(line))
        return records
