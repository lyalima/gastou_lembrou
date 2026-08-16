import calendar
import uuid

from .models import Payment


def add_months(value, months):
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def create_installment_siblings(payment):
    if not payment.has_installment_info or not payment.payment_date:
        return []
    if not payment.installment_group:
        payment.installment_group = uuid.uuid4()
        payment.save(update_fields=["installment_group", "updated_at"])

    created = []
    for number in range(1, payment.installment_total + 1):
        if number == payment.installment_number:
            continue
        offset = number - payment.installment_number
        created.append(
            Payment.objects.create(
                user=payment.user,
                title=payment.title,
                category=payment.category,
                description=payment.description,
                kind=payment.kind,
                amount=payment.amount,
                payment_method=payment.payment_method,
                is_installment=True,
                installment_group=payment.installment_group,
                installment_number=number,
                installment_total=payment.installment_total,
                payment_date=add_months(payment.payment_date, offset),
                scheduled_date=add_months(payment.scheduled_date, offset) if payment.scheduled_date else None,
                image=payment.image,
                credit_card_statement=payment.credit_card_statement,
            )
        )
    return created
