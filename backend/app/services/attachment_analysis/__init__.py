"""Safe attachment analysis (static, structural; never executes uploaded content).

Public interface: `analyze_attachment(file_name, data, content_type)` and `AttachmentError`.
Independent of message analysis, behaviour analysis and risk scoring.
"""

from .analyzer import AttachmentError, analyze_attachment, detect_type

__all__ = ["AttachmentError", "analyze_attachment", "detect_type"]
