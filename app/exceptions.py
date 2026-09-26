class AppException(Exception):
    def __init__(self, message: str, code: str, status_code: int = 500):
        self.message = message
        self.code = code
        self.status_code = status_code


class NotFoundError(AppException):
    def __init__(self, resource: str):
        super().__init__(f"{resource} not found", "NOT_FOUND", 404)


class ConflictError(AppException):
    def __init__(self, message: str):
        super().__init__(message, "CONFLICT", 409)


class BadRequestError(AppException):
    def __init__(self, message: str):
        super().__init__(message, "BAD_REQUEST", 400)


class UnauthorizedError(AppException):
    def __init__(self, message: str = "Not authenticated"):
        super().__init__(message, "UNAUTHORIZED", 401)


class ForbiddenError(AppException):
    def __init__(self, message: str = "Not enough permissions"):
        super().__init__(message, "FORBIDDEN", 403)


def custom_exception_handler(exc, context):
    from rest_framework.views import exception_handler
    from rest_framework.response import Response
    from rest_framework.exceptions import NotAuthenticated, PermissionDenied
    
    if isinstance(exc, AppException):
        return Response(
            {"detail": exc.message, "code": exc.code},
            status=exc.status_code
        )
        
    if isinstance(exc, NotAuthenticated):
        return Response(
            {"detail": "Not authenticated", "code": "UNAUTHORIZED"},
            status=401
        )
        
    if isinstance(exc, PermissionDenied):
        return Response(
            {"detail": str(exc.detail), "code": "FORBIDDEN"},
            status=403
        )
        
    return exception_handler(exc, context)
