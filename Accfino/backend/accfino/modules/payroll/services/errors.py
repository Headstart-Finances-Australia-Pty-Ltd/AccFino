"""Payroll business-rule errors. PayrollError IS an HTTPException, so FastAPI answers {"detail": message} with the right status wherever it is raised
(no handler to register). `code` is a machine-readable reason the tests and UI can rely on."""
from fastapi import HTTPException


class PayrollError(HTTPException):
    def __init__(self, message: str, status: int = 422, code: str = "invalid"):
        super().__init__(status_code=status, detail=message)
        self.message, self.status, self.code = message, status, code

    def __str__(self):
        return self.message


class NotFound(PayrollError):
    def __init__(self, what: str = "Record"):
        super().__init__(f"{what} not found", 404, "not_found")


class Forbidden(PayrollError):
    def __init__(self, message: str = "You do not have permission to do that in Payroll"):
        super().__init__(message, 403, "forbidden")


class Conflict(PayrollError):
    def __init__(self, message: str, code: str = "conflict"):
        super().__init__(message, 409, code)
