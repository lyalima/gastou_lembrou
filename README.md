# Gastou Lembrou

SaaS Django para gerenciamento de gastos pessoais, upload de notas fiscais processadas, dashboard financeiro e lembretes por email.

## Stack

- Python 3.11+
- Django
- PostgreSQL em produção, SQLite como fallback local
- Tailwind via CDN para o MVP
- HTMX para interações sem reload
- Django Allauth com Google OAuth
- Celery + Redis para emails assíncronos e lembretes
- OpenCV para processamento de imagem
- Chart.js para dashboard
- Gemini 2.5 Flash-Lite para insights financeiros, com fallback local

## Setup local

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Em outro terminal, com Redis disponível:

```powershell
celery -A config worker -l info -P solo
celery -A config beat -l info
```

No Windows, use `-P solo` no worker. O pool padrao do Celery usa multiprocessing e pode falhar com `PermissionError: [WinError 5] Acesso negado`.

## Variáveis de ambiente

Veja `.env.example`. Sem `DATABASE_URL`, o projeto usa SQLite local. Sem SMTP configurado, emails são enviados para o console.

## Email de confirmação

Por padrão, `EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend`, então o email de confirmação aparece no terminal do `runserver`.

Para enviar email real, configure no `.env`:

```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=principal@gastoulembrou.com.br
EMAIL_HOST_PASSWORD=sua-senha-de-app
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=Gastou Lembrou <principal@gastoulembrou.com.br>
SUPPORT_EMAIL=suporte@gastoulembrou.com.br
```

No Gmail, use uma senha de app, não a senha normal da conta.
