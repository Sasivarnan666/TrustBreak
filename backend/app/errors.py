"""Application errors and the single JSON error envelope used by every endpoint.

Success:  {"success": true,  "data": ...}
Failure:  {"success": false, "error": {"code": str, "message": str, "details": [...]}}
"""

from typing import Any, Optional


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or []


class NotFoundError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__("not_found", message, status_code=404)


def error_body(
    code: str, message: str, details: Optional[list[dict[str, Any]]] = None
) -> dict[str, Any]:
    return {
        "success": False,
        "error": {"code": code, "message": message, "details": details or []},
    }
