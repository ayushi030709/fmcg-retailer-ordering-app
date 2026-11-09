from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """A business-rule error with a stable machine code and a human message."""

    def __init__(self, status_code: int, code: str, message: str, details: dict | list | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def not_found(what: str = "Resource") -> AppError:
    # Used for both "does not exist" and "not yours" so ownership is not leaked.
    return AppError(404, "not_found", f"{what} not found.")


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    body: dict = {"error": {"code": exc.code, "message": exc.message}}
    if exc.details is not None:
        body["error"]["details"] = exc.details
    return JSONResponse(status_code=exc.status_code, content=body)
