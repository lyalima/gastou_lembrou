import mimetypes

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Case, IntegerField, Q, Value, When
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, FormView, ListView, UpdateView

from .credit_card_statement_import import (
    get_or_create_credit_card_method,
    parse_amount,
    parse_card_date,
    payment_duplicate_exists,
    process_credit_card_statement,
)
from .forms import BankStatementImportForm, CategoryForm, CreditCardStatementImportForm, PaymentForm
from .models import Category, CreditCardStatement, CreditCardStatementItem, Payment, PaymentMethod
from .cache import get_cached_payment_ids
from .statement_import import import_statement_payments
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
        queryset = super().get_queryset().select_related("category", "payment_method")
        query = self.request.GET.get("q")
        category = self.request.GET.get("category")
        payment_method = self.request.GET.get("payment_method")
        day = self.request.GET.get("day")
        month = self.request.GET.get("month")
        year = self.request.GET.get("year")
        schedule_status = self.request.GET.get("schedule_status")
        order = self.request.GET.get("order", "desc")

        if query:
            queryset = queryset.filter(Q(title__icontains=query) | Q(description__icontains=query))
        if category:
            queryset = queryset.filter(category_id=category, category__in=self.get_category_queryset())
        if payment_method:
            queryset = queryset.filter(payment_method_id=payment_method)
        if day:
            queryset = queryset.filter(payment_date=day)
        if month:
            queryset = queryset.filter(payment_date__month=month)
        if year:
            queryset = queryset.filter(payment_date__year=year)
        if schedule_status == "scheduled":
            queryset = queryset.filter(scheduled_date__isnull=False)
        elif schedule_status == "unscheduled":
            queryset = queryset.filter(scheduled_date__isnull=True)
        queryset = queryset.order_by("payment_date", "created_at") if order == "asc" else queryset.order_by("-payment_date", "-created_at")
        payment_ids = get_cached_payment_ids(
            self.request.user.pk,
            self.request.GET,
            lambda: queryset.values_list("pk", flat=True),
        )
        if not payment_ids:
            return Payment.objects.none()
        preserved_order = Case(
            *[When(pk=payment_id, then=Value(index)) for index, payment_id in enumerate(payment_ids)],
            output_field=IntegerField(),
        )
        return Payment.objects.filter(pk__in=payment_ids).select_related("category", "payment_method").order_by(preserved_order)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filter_querystring = self.request.GET.copy()
        filter_querystring.pop("page", None)
        context["categories"] = self.get_category_queryset()
        context["payment_methods"] = PaymentMethod.objects.all()
        context["payment_form"] = PaymentForm(user=self.request.user)
        context["category_form"] = CategoryForm(user=self.request.user)
        context["import_form"] = BankStatementImportForm()
        context["credit_card_statement_form"] = CreditCardStatementImportForm()
        context["filter_querystring"] = filter_querystring.urlencode()
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
        form.instance.user = self.request.user
        response = super().form_valid(form)
        if form.instance.scheduled_date:
            queue_payment_confirmation(form.instance.pk)
        messages.success(self.request, "Pagamento salvo.")
        return _htmx_refresh_or_response(self.request, response)


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
        response = super().form_valid(form)
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
        result = import_statement_payments(self.request.user, form.cleaned_data["statement_file"])
        if result.created:
            messages.success(self.request, f"{result.created} pagamento(s) importado(s) do extrato.")
        if result.skipped:
            messages.info(self.request, f"{result.skipped} transação(ões) duplicada(s) foram ignoradas.")
        if result.ignored_income:
            messages.info(self.request, f"{result.ignored_income} entrada(s) ou crédito(s) foram ignorados.")
        if result.errors:
            messages.error(self.request, "Algumas transações não puderam ser importadas.")
        return _htmx_refresh_or_response(self.request, super().form_valid(form))


class CreditCardStatementImportView(LoginRequiredMixin, FormView):
    form_class = CreditCardStatementImportForm
    template_name = "payments/partials/credit_card_statement_form.html"
    success_url = reverse_lazy("payments:list")

    def form_valid(self, form):
        statement = CreditCardStatement.objects.create(
            user=self.request.user,
            file=form.cleaned_data["statement_file"],
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
        card_method = get_or_create_credit_card_method()

        with transaction.atomic():
            for item in statement.items.select_for_update().filter(pk__in=item_ids, status=CreditCardStatementItem.Status.DETECTED):
                title = request.POST.get(f"title_{item.pk}", item.title).strip()[:200]
                payment_date = parse_card_date(request.POST.get(f"date_{item.pk}")) or item.payment_date
                amount = parse_amount(request.POST.get(f"amount_{item.pk}")) or item.amount
                category_id = request.POST.get(f"category_{item.pk}") or None
                category = None
                if category_id:
                    category = Category.objects.filter(Q(user__isnull=True) | Q(user=request.user), pk=category_id).first()

                if payment_duplicate_exists(request.user, title, amount, payment_date, card_method, item.import_hash):
                    item.status = CreditCardStatementItem.Status.SKIPPED
                    item.save(update_fields=["status", "updated_at"])
                    skipped_count += 1
                    continue

                payment = Payment.objects.create(
                    user=request.user,
                    title=title,
                    category=category,
                    description="Importado de fatura de cartão de crédito.",
                    kind=Payment.Kind.EXPENSE,
                    amount=amount,
                    payment_method=card_method,
                    payment_date=payment_date,
                    import_hash=item.import_hash,
                    imported_at=statement.created_at,
                    credit_card_statement=statement,
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

        if imported_count:
            messages.success(request, f"{imported_count} gasto(s) do cartão importado(s).")
        if skipped_count:
            messages.info(request, f"{skipped_count} lançamento(ões) duplicado(s) foram ignorados.")
        return _htmx_refresh_or_response(request, redirect("payments:list"))


def _htmx_refresh_or_response(request, response):
    if request.headers.get("HX-Request"):
        htmx_response = HttpResponse(status=204)
        htmx_response["HX-Refresh"] = "true"
        return htmx_response
    return response
