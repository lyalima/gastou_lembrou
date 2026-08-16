# Gastou Lembrou

SaaS Django para organizacao de gastos pessoais, lembretes de pagamentos,
dashboard financeiro, importacao de extratos/faturas, relatorios PDF, metas
mensais e insights com IA.

## Funcionalidades

- Cadastro e login por email/senha, com confirmacao de email obrigatoria.
- Login/cadastro social com Google OAuth.
- Redefinicao de senha para contas criadas manualmente.
- Aceite versionado de Termos de Uso e Politica de Privacidade.
- Perfil com telefone internacional, CPF opcional bloqueado apos cadastro e exclusao permanente da conta.
- CRUD de pagamentos com HTMX, filtros, busca, ordenacao e paginacao.
- Categorias globais e categorias personalizadas por usuario.
- Formas de pagamento, incluindo identificacao de gastos em cartao de credito e parcelamento.
- Upload de comprovantes/notas em JPG, PNG ou PDF.
- Importacao de extrato bancario em CSV/OFX.
- Importacao de fatura de cartao em PDF com pre-visualizacao dos lancamentos antes de criar pagamentos.
- Dashboard com filtro mensal, graficos por categoria/forma de pagamento, evolucao temporal e resumo.
- Metas mensais de gastos com barra de progresso e alertas por email.
- Relatorio PDF mensal e envio automatico no primeiro dia do mes.
- Insights financeiros com Gemini 2.5 Flash-Lite, com fallback local.
- Suporte autenticado por email com upload opcional de screenshot.
- Emails HTML padronizados com fallback texto simples.
- PWA basico com manifest/offline page.
- Modo claro/escuro na area autenticada.

## Stack

- Python 3.12 no Docker
- Django 5
- Django Allauth
- PostgreSQL via `DATABASE_URL`, SQLite como fallback local
- Redis + Celery + Celery Beat
- HTMX e JavaScript leve
- Tailwind via CDN
- Chart.js
- OpenCV, Pillow e PyMuPDF
- Gemini API
- Gunicorn e WhiteNoise

## Setup local com venv

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Em outros terminais, com Redis disponivel:

```powershell
celery -A config worker -l info -P solo
celery -A config beat -l info
```

No Windows, use `-P solo` no worker. O pool padrao do Celery usa multiprocessing
e pode falhar com `PermissionError: [WinError 5] Acesso negado`.

## Setup local com Docker

```powershell
copy .env.example .env
docker compose up --build
```

Depois, em outro terminal:

```powershell
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
```

## Variaveis de ambiente

Veja [.env.example](.env.example). Sem `DATABASE_URL`, o projeto usa SQLite local.
Sem SMTP configurado, emails sao enviados para o console.

Para enviar email real, configure:

```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=principal@seudominio.com.br
EMAIL_HOST_PASSWORD=sua-senha-de-app
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
DEFAULT_FROM_EMAIL=Gastou Lembrou <principal@seudominio.com.br>
SUPPORT_EMAIL=suporte@seudominio.com.br
```

No Gmail, use senha de app, nao a senha normal da conta.

## Google OAuth

Configure no Google Cloud o callback local:

```text
http://127.0.0.1:8000/accounts/google/login/callback/
```

E preencha no `.env`:

```env
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
```

## Testes

```powershell
python manage.py check
python manage.py test
```

Tambem e possivel testar por app:

```powershell
python manage.py test accounts
python manage.py test payments
python manage.py test dashboard
python manage.py test support
```

## Deploy

O projeto possui Dockerfile e compose de producao simulada. Veja
[docs/DOCKER_DEPLOY.md](docs/DOCKER_DEPLOY.md).

Para producao real:

- use `DEBUG=False`;
- defina `SECRET_KEY` forte;
- configure `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `SITE_URL` e `EMAIL_ASSET_BASE_URL`;
- use PostgreSQL e Redis com credenciais fortes;
- use HTTPS;
- evite servir `media/` como pasta publica.

## Seguranca e privacidade

- Nao versione `.env`, banco local, uploads ou arquivos gerados.
- Arquivos de pagamentos sao acessados por rota autenticada e filtrada pelo dono.
- Uploads validam extensao, assinatura e tamanho.
- Consultas de pagamentos sao isoladas por usuario autenticado.
- Dados enviados ao Gemini sao reduzidos ao necessario para cada funcionalidade.
