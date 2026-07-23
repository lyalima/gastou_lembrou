import re

from django.core.exceptions import ValidationError


def only_digits(value):
    return re.sub(r"\D", "", value or "")


def validate_cpf(value):
    cpf = only_digits(value)
    if not cpf:
        return
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        raise ValidationError("CPF inválido.")

    for size in (9, 10):
        total = sum(int(cpf[index]) * ((size + 1) - index) for index in range(size))
        digit = (total * 10) % 11
        digit = 0 if digit == 10 else digit
        if digit != int(cpf[size]):
            raise ValidationError("CPF inválido.")


def validate_phone(value):
    if not value:
        return
    if re.fullmatch(r"\(\d{2}\) \d{5}-\d{4}", value):
        return
    if re.fullmatch(r"\+\d{8,15}", value):
        return
    raise ValidationError("Informe um telefone válido com código do país.")
