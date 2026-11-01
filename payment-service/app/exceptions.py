from fastapi import HTTPException


class PaymentException(Exception):
    detail = "Непредвиденная ошибка"

    def __init__(self, *args, **kwargs):
        super().__init__(self.detail, *args, **kwargs)

class IdempotentException(PaymentException):
    detail = "Конфликт идемпотентности"

class PaymentNotFoundException(PaymentException):
    detail = "Платеж не найден"


class PaymentHTTPException(HTTPException):
    status_code = 500
    detail = "Внутрення ошибка сервера"

    def __init__(self):
        super().__init__(status_code=self.status_code, detail=self.detail)

class IdempotentHHTPException(PaymentHTTPException):
    status_code = 409
    detail = "Конфликт идемпотентности"

class PaymentNotFoundHTTPException(PaymentHTTPException):
    status_code = 404
    detail = "Платеж не найден"

class NotSucceededAPIKeyHTTPException(PaymentHTTPException):
    status_code = 401
    detail = "Передан неверный API-ключ, либо вы не авторизовались "
