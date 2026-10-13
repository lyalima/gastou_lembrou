import mimetypes
import uuid
from collections import Counter
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Case, IntegerField, Q, Sum, Value, When
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, FormView, ListView, TemplateView, UpdateView

from .credit_card_statement_import import (
    extract_installment_info,
    get_or_create_credit_card_method,
    parse_amount,
    parse_card_date,
    payment_duplicate_exists,
    process_credit_card_statement,
)
from .forms import BankStatementImportForm, CategoryForm, CreditCardForm, CreditCardStatementImportForm, PaymentForm
from .recurrences import configure_recurrence
from .installments import create_installment_siblings
from .models import Category, CreditCard, CreditCardStatement, CreditCardStatementItem, Payment, PaymentMethod
from .cache import get_cached_payment_ids
from .statement_import import confirm_statement_preview, get_statement_preview, prepare_statement_preview
from .tasks import queue_payment_confirmation


class UserScopedMixin(LoginRequiredMixin):
    def get_queryset(self):
        return super().get_queryset().filter(user=self.request.user)


class PaymentListView(UserScopedMixin, ListView):
    model = Payment
    template_name = "payments/payment_list.html"
    context_object_name = "payments"
    paginate_by = 6

    def get_queryset(self):
        queryset = self.apply_filters(super().get_queryset().select_related("category", "payment_method", "credit_card", "credit_card_statement"))
        queryset = queryset.exclude(self.future_installment_filter())
        queryset = self.apply_ordering(queryset)
        payment_ids = get_cached_payment_ids(
            self.request.user.pk,
            self.request.GET,
            lambda: queryset.values_list("pk", flat=True),
            scope="current-purchase-date-v3",
        )
        if not payment_ids:
            return Payment.objects.none()
        preserved_order = Case(
            *[When(pk=payment_id, then=Value(index)) for index, payment_id in enumerate(payment_ids)],
            output_field=IntegerField(),
        )
        return Payment.objects.filter(user=self.request.user, pk__in=payment_ids).select_related("category", "payment_method", "credit_card", "credit_card_statement").order_by(preserved_order)

    def apply_filters(self, queryset):
        from dashboard.metrics import spending_date_expression

        queryset = queryset.annotate(financial_date=spending_date_expression())
        query = self.request.GET.get("q")
        category = self.request.GET.get("category")
        payment_method = self.request.GET.get("payment_method")
        day = self.request.GET.get("day")
        month = self.request.GET.get("month")
        year = self.request.GET.get("year")
        schedule_status = self.request.GET.get("schedule_status")

        if query:
            queryset = queryset.filter(Q(title__icontains=query) | Q(description__icontains=query))
        if category:
            queryset = queryset.filter(category_id=category, category__in=self.get_category_queryset())
        if payment_method:
            queryset = queryset.filter(payment_method_id=payment_method)
        if day:
            queryset = queryset.filter(financial_date=day)
        if month:
            queryset = queryset.filter(financial_date__month=month)
        if year:
            queryset = queryset.filter(financial_date__year=year)
        if schedule_status == "scheduled":
            queryset = queryset.filter(scheduled_date__isnull=False)
        elif schedule_status == "unscheduled":
            queryset = queryset.filter(scheduled_date__isnull=True)
        return queryset

    def apply_ordering(self, queryset):
        from dashboard.metrics import activity_date_expression
        order = self.request.GET.get("order", "desc")
        queryset = queryset.annotate(activity_date=activity_date_expression())
        return queryset.order_by("activity_date", "created_at", "pk") if order == "asc" else queryset.order_by("-activity_date", "-created_at", "-pk")

    def future_installment_filter(self):
        today = timezone.localdate()
        return Q(is_installment=True) & (
            Q(statement_due_date__gt=today)
            | Q(statement_due_date__isnull=True, payment_date__gt=today)
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filter_querystring = self.request.GET.copy()
        filter_querystring.pop("page", None)
        future_installments = self.apply_filters(
            Payment.objects.filter(user=self.request.user).select_related("category", "payment_method", "credit_card", "credit_card_statement")
        ).filter(self.future_installment_filter())
        context["categories"] = self.get_category_queryset()
        context["payment_methods"] = PaymentMethod.objects.all()
        context["payment_form"] = PaymentForm(user=self.request.user)
        context["category_form"] = CategoryForm(user=self.request.user)
        context["import_form"] = BankStatementImportForm()
        context["credit_card_statement_form"] = CreditCardStatementImportForm(user=self.request.user)
        context["filter_querystring"] = filter_querystring.urlencode()
        from dashboard.metrics import activity_date_expression
        context["future_installments"] = future_installments.annotate(activity_date=activity_date_expression()).order_by("activity_date", "created_at", "pk")
        return context

    def get_category_queryset(self):
        return Category.objects.filter(Q(user__isnull=True) | Q(user=self.request.user))


class PaymentDetailView(UserScopedMixin, DetailView):
    model = Payment
    template_name = "payments/partials/payment_detail.html"


class PaymentReceiptView(UserScopedMixin, View):
    def get(self, request, pk):
        payment = get_object_or_404(Payment, pk=pk, user=request.user)
        if not payment.image:
            raise Http404("Arquivo não encontrado.")
        content_type, _ = mimetypes.guess_type(payment.image.name)
        return FileResponse(payment.image.open("rb"), content_type=content_type or "application/octet-stream")


class PaymentCreateView(LoginRequiredMixin, CreateView):
    model = Payment
    form_class = PaymentForm
    template_name = "payments/partials/payment_form.html"
    success_url = reverse_lazy("payments:list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        with transaction.atomic():
            form.instance.user = self.request.user
            if form.instance.is_installment:
                form.instance.installment_group = uuid.uuid4()
            self.object = form.save()
            sibling_payments = create_installment_siblings(self.object)
            configure_recurrence(self.object, form.cleaned_data)
        if self.object.scheduled_date:
            queue_payment_confirmation(self.object.pk)
        messages.success(self.request, self._success_message(sibling_payments))
        response = redirect(self.get_success_url())
        return _htmx_refresh_or_response(self.request, response)

    @staticmethod
    def _success_message(sibling_payments):
        if sibling_payments:
            return f"Pagamento salvo e {len(sibling_payments)} parcela(s) criada(s)."
        return "Pagamento salvo."


class PaymentUpdateView(UserScopedMixin, UpdateView):
    model = Payment
    form_class = PaymentForm
    template_name = "payments/partials/payment_form.html"
    success_url = reverse_lazy("payments:list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        with transaction.atomic():
            response = super().form_valid(form)
            configure_recurrence(self.object, form.cleaned_data)
        if form.instance.scheduled_date:
            queue_payment_confirmation(form.instance.pk)
        messages.success(self.request, "Pagamento atualizado.")
        return _htmx_refresh_or_response(self.request, response)


class PaymentDeleteView(UserScopedMixin, DeleteView):
    model = Payment
    template_name = "payments/partials/payment_confirm_delete.html"
    success_url = reverse_lazy("payments:list")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Pagamento excluído.")
        return _htmx_refresh_or_response(self.request, response)


class CategoryCreateView(LoginRequiredMixin, CreateView):
    model = Category
    form_class = CategoryForm
    template_name = "payments/partials/category_form.html"
    success_url = reverse_lazy("payments:list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.user = self.request.user
        response = super().form_valid(form)
        messages.success(self.request, "Categoria criada.")
        return _htmx_refresh_or_response(self.request, response)


class BankStatementImportView(LoginRequiredMixin, FormView):
    form_class = BankStatementImportForm
    template_name = "payments/partials/statement_import_form.html"
    success_url = reverse_lazy("payments:list")

    def form_valid(self, form):
        try:
            token, preview = prepare_statement_preview(self.request.user, form.cleaned_data["statement_file"])
        except ValueError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        if not preview["rows"] and not preview["skipped"]:
            if preview["ignored_income"]:
                form.add_error(None, f"Nenhuma despesa encontrada. {preview['ignored_income']} entrada(s) ou crédito(s) foram ignorados.")
            else:
                form.add_error(None, "Nenhum lançamento de despesa foi reconhecido. Confira as colunas de data, descrição e valor do extrato.")
            return self.form_invalid(form)
        return render(self.request, "payments/partials/statement_import_preview.html", {"token": token, **preview})


class BankStatementConfirmView(LoginRequiredMixin, View):
    def post(self, request):
        token = request.POST.get("token", "")
        try:
            result = confirm_statement_preview(request.user, token, request.POST.getlist("items"))
        except ValueError as exc:
            preview = get_statement_preview(request.user, token)
            if preview is not None:
                return render(request, "payments/partials/statement_import_preview.html", {"token": token, "selection_error": str(exc), **preview})
            return render(request, "payments/partials/statement_import_form.html", {"form": BankStatementImportForm(), "import_error": str(exc)})
        if result.created:
            messages.success(request, f"{result.created} pagamento(s) importado(s) do extrato.")
        if result.skipped:
            messages.info(request, f"{result.skipped} transação(ões) duplicada(s) foram ignoradas.")
        if result.ignored_income:
            messages.info(request, f"{result.ignored_income} entrada(s) ou crédito(s) foram ignorados.")
        return _htmx_refresh_or_response(request, redirect("payments:list"))


class CreditCardStatementImportView(LoginRequiredMixin, FormView):
    form_class = CreditCardStatementImportForm
    template_name = "payments/partials/credit_card_statement_form.html"
    success_url = reverse_lazy("payments:list")

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "user": self.request.user}

    def form_valid(self, form):
        statement = CreditCardStatement.objects.create(
            user=self.request.user,
            file=form.cleaned_data["statement_file"],
            credit_card=form.cleaned_data["credit_card"],
        )
        process_credit_card_statement(statement)
        statement.refresh_from_db()
        context = self.get_preview_context(statement)
        if statement.status == CreditCardStatement.Status.FAILED:
            messages.error(self.request, statement.error_message)
        return render(self.request, "payments/partials/credit_card_statement_preview.html", context)

    def get_preview_context(self, statement):
        return {
            "statement": statement,
            "items": statement.items.all(),
            "categories": Category.objects.filter(Q(user__isnull=True) | Q(user=self.request.user)),
        }


class CreditCardStatementConfirmView(LoginRequiredMixin, View):
    def post(self, request, pk):
        statement = get_object_or_404(CreditCardStatement, pk=pk, user=request.user)
        if statement.status == CreditCardStatement.Status.CONFIRMED:
            messages.info(request, "Esta fatura já foi importada.")
            return _htmx_refresh_or_response(request, redirect("payments:invoices"))
        due_date = parse_card_date(request.POST.get("due_date"))
        if not due_date:
            return render(
                request,
                "payments/partials/credit_card_statement_preview.html",
                {
                    "statement": statement,
                    "items": statement.items.all(),
                    "categories": Category.objects.filter(Q(user__isnull=True) | Q(user=request.user)),
                    "due_date_error": "Informe a data de vencimento desta fatura.",
                },
            )
        item_ids = request.POST.getlist("items")
        if not item_ids:
            messages.error(request, "Selecione pelo menos um lançamento para importar.")
            return render(
                request,
                "payments/partials/credit_card_statement_preview.html",
                {
                    "statement": statement,
                    "items": statement.items.all(),
                    "categories": Category.objects.filter(Q(user__isnull=True) | Q(user=request.user)),
                },
            )

        imported_count = 0
        skipped_count = 0
        invoice_total = Decimal("0.00")
        card_method = get_or_create_credit_card_method()
        occurrence_counts = Counter()
        prior_occurrences = {}
        for statement_item in statement.items.order_by("pk"):
            key = (statement_item.title.casefold(), statement_item.amount, statement_item.payment_date)
            prior_occurrences[statement_item.pk] = occurrence_counts[key]
            occurrence_counts[key] += 1

        with transaction.atomic():
            statement = CreditCardStatement.objects.select_for_update().get(pk=statement.pk, user=request.user)
            if statement.status == CreditCardStatement.Status.CONFIRMED:
                messages.info(request, "Esta fatura já foi importada.")
                return _htmx_refresh_or_response(request, redirect("payments:invoices"))
            if statement.due_date != due_date:
                statement.due_date = due_date
                statement.save(update_fields=["due_date", "updated_at"])
            for item in statement.items.select_for_update().filter(pk__in=item_ids, status=CreditCardStatementItem.Status.DETECTED):
                title = request.POST.get(f"title_{item.pk}", item.title).strip()[:200]
                payment_date = parse_card_date(request.POST.get(f"date_{item.pk}")) or item.payment_date
                amount = parse_amount(request.POST.get(f"amount_{item.pk}")) or item.amount
                invoice_total += amount
                category_id = request.POST.get(f"category_{item.pk}") or None
                category = None
                if category_id:
                    category = Category.objects.filter(Q(user__isnull=True) | Q(user=request.user), pk=category_id).first()

                if payment_duplicate_exists(
                    request.user, title, amount, payment_date, card_method, item.import_hash,
                    statement.pk, prior_occurrences[item.pk],
                ):
                    item.status = CreditCardStatementItem.Status.SKIPPED
                    item.save(update_fields=["status", "updated_at"])
                    skipped_count += 1
                    continue

                installment = extract_installment_info(title)
                payment = Payment.objects.create(
                    user=request.user,
                    title=title,
                    category=category,
                    description="Importado de fatura de cartão de crédito.",
                    kind=Payment.Kind.EXPENSE,
                    amount=amount,
                    payment_method=card_method,
                    payment_date=payment_date,
                    is_installment=bool(installment),
                    installment_number=installment[0] if installment else None,
                    installment_total=installment[1] if installment else None,
                    import_hash=item.import_hash,
                    imported_at=statement.created_at,
                    credit_card_statement=statement,
                    credit_card=statement.credit_card,
                )
                item.title = title
                item.amount = amount
                item.payment_date = payment_date
                item.category = category
                item.payment = payment
                item.status = CreditCardStatementItem.Status.IMPORTED
                item.save(update_fields=["title", "amount", "payment_date", "category", "payment", "status", "updated_at"])
                imported_count += 1

            statement.status = CreditCardStatement.Status.CONFIRMED
            statement.save(update_fields=["status", "updated_at"])
            if invoice_total > 0:
                bill_category = Category.objects.filter(
                    user=request.user, name="Fatura de cartão de crédito",
                ).first()
                if bill_category is None:
                    bill_category = Category.objects.create(user=request.user, name="Fatura de cartão de crédito")
                Payment.objects.create(
                    user=request.user,
                    title=f"Fatura {statement.credit_card.name}" if statement.credit_card else "Fatura Cartão de crédito",
                    category=bill_category,
                    kind=Payment.Kind.CREDIT_CARD_BILL,
                    amount=invoice_total,
                    payment_date=due_date,
                    credit_card=statement.credit_card,
                    credit_card_statement=statement,
                )

        if imported_count:
            messages.success(request, f"{imported_count} gasto(s) do cartão importado(s).")
        if skipped_count:
            messages.info(request, f"{skipped_count} lançamento(ões) duplicado(s) foram ignorados.")
        return _htmx_refresh_or_response(request, redirect("payments:list"))


class CreditCardListView(UserScopedMixin, ListView):
    model = CreditCard
    template_name = "payments/credit_cards.html"
    context_object_name = "cards"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["recent_card_payments"] = (
            Payment.objects.filter(user=self.request.user, credit_card__user=self.request.user, kind=Payment.Kind.EXPENSE)
            .select_related("credit_card")
            .order_by("-created_at")[:8]
        )
        return context


class CreditCardInvoiceListView(LoginRequiredMixin, TemplateView):
    template_name = "payments/credit_card_invoices.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cards = CreditCard.objects.filter(user=self.request.user)
        card_id = self.request.GET.get("card")
        month_value = self.request.GET.get("month", "")
        selected_card = cards.filter(pk=card_id).first() if card_id and card_id.isdigit() else None
        from dashboard.metrics import parse_report_month

        selected_month = parse_report_month(month_value) if month_value else None
        month_value = selected_month.strftime("%Y-%m") if selected_month else ""
        month_value = selected_month.strftime("%Y-%m") if selected_month else ""
        periods = Payment.objects.filter(
            user=self.request.user, kind=Payment.Kind.EXPENSE, credit_card__user=self.request.user,
            statement_due_date__isnull=False,
        ).dates("statement_due_date", "month", order="DESC")
        current_month = timezone.localdate().replace(day=1)
        month_options = {month.strftime("%Y-%m"): month for month in periods}
        month_options.setdefault(current_month.strftime("%Y-%m"), current_month)
        from .installments import add_months

        next_month = add_months(current_month, 1)
        month_options.setdefault(next_month.strftime("%Y-%m"), next_month)
        if selected_month:
            month_options.setdefault(month_value, selected_month)
        context.update({
            "cards": cards,
            "selected_card": selected_card,
            "selected_month": month_value if selected_month else "",
            "month_options": sorted(month_options.items(), reverse=True),
            "has_selection": bool(selected_card and selected_month),
        })
        if selected_card and selected_month:
            following_month = add_months(selected_month, 1)
            payments = Payment.objects.filter(
                user=self.request.user,
                kind=Payment.Kind.EXPENSE,
                credit_card=selected_card,
                statement_due_date__gte=selected_month,
                statement_due_date__lt=following_month,
            ).select_related("category", "credit_card").order_by("statement_due_date", "payment_date", "created_at")
            context["invoice_payments"] = payments
            context["invoice_total"] = payments.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
            context["invoice_count"] = payments.count()
        return context


class CreditCardCreateView(LoginRequiredMixin, CreateView):
    model = CreditCard
    form_class = CreditCardForm
    template_name = "payments/partials/credit_card_form.html"
    success_url = reverse_lazy("payments:cards")

    def form_valid(self, form):
        form.instance.user = self.request.user
        return _htmx_refresh_or_response(self.request, super().form_valid(form))


class CreditCardUpdateView(UserScopedMixin, UpdateView):
    model = CreditCard
    form_class = CreditCardForm
    template_name = "payments/partials/credit_card_form.html"
    success_url = reverse_lazy("payments:cards")

    def form_valid(self, form):
        # Existing statement dates are snapshots; editing a card affects new/edited purchases only.
        return _htmx_refresh_or_response(self.request, super().form_valid(form))


def _htmx_refresh_or_response(request, response):
    if request.headers.get("HX-Request"):
        htmx_response = HttpResponse(status=204)
        htmx_response["HX-Refresh"] = "true"
        return htmx_response
    return response
