"""AI-powered message entity & financial-intent extraction.

Public interface: `analyze_message(message)`. See service.py.
"""

from .schema import ExtractionValidationError, MessageAnalysis, MessageExtraction, validate_extraction
from .service import ExtractionError, analyze_message

__all__ = [
    "analyze_message",
    "ExtractionError",
    "ExtractionValidationError",
    "MessageAnalysis",
    "MessageExtraction",
    "validate_extraction",
]
