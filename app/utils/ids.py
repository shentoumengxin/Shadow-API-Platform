"""ID generation utilities."""

import uuid
from datetime import datetime


def generate_trace_id() -> str:
    """Generate a unique trace ID.

    Returns:
        A unique trace ID string (format: tr_{timestamp}_{uuid})
    """
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    unique = str(uuid.uuid4())[:8]
    return f"tr_{timestamp}_{unique}"


def generate_short_id() -> str:
    """Generate a short unique ID.

    Returns:
        A short unique ID string
    """
    return uuid.uuid4().hex[:12]
