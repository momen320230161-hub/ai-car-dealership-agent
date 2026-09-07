class ApplicationError(Exception):
    """Base error for application-defined failures."""

    status_code = 500

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class ValidationError(ApplicationError):
    status_code = 400


class NotFoundError(ApplicationError):
    status_code = 404


class BusinessLogicError(ApplicationError):
    status_code = 422
