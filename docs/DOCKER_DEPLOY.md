# Docker e Deploy

Este guia resume como rodar o Gastou Lembrou em Docker para desenvolvimento e como preparar o deploy em produção.

## Desenvolvimento Local

Crie um `.env` baseado em `.env.example` e rode:

```powershell
docker compose up --build
```

Depois, em outro terminal:

```powershell
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
```

Serviços locais:

- Django: `http://127.0.0.1:8000`
- Postgres: container `db`
- Redis: container `redis`
- Celery worker: container `celery_worker`
- Celery beat: container `celery_beat`

Para que a logo apareca nos emails enviados pelo ambiente Docker local, defina
`EMAIL_ASSET_BASE_URL` com uma URL que o cliente de email consiga acessar. Para
clientes locais, `http://127.0.0.1:8000` funciona; para testes em Gmail/Outlook,
use um tunel HTTPS publico ou um dominio real. Nao use `web:8000` nessa variavel,
porque esse endereco so existe dentro da rede do Docker.

## Produção Local Simulada

Use o compose de produção apenas para simular um ambiente mais próximo do deploy:

```powershell
docker compose -f docker-compose.prod.yml up --build
```

Defina no `.env`:

```env
DEBUG=False
SECRET_KEY=uma-chave-longa-e-aleatoria
ALLOWED_HOSTS=127.0.0.1,localhost
CSRF_TRUSTED_ORIGINS=http://127.0.0.1:8000,http://localhost:8000
SECURE_SSL_REDIRECT=False
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
SECURE_HSTS_SECONDS=0
```

Para produção real com HTTPS, use valores seguros:

```env
DEBUG=False
SECRET_KEY=uma-chave-longa-e-aleatoria
ALLOWED_HOSTS=seu-app.onrender.com,seu-dominio.com.br
CSRF_TRUSTED_ORIGINS=https://seu-app.onrender.com,https://seu-dominio.com.br
SITE_URL=https://seu-dominio.com.br
EMAIL_ASSET_BASE_URL=https://seu-dominio.com.br
PROJECT_EMAIL_SITE_NAME=Gastou, Lembrou!
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_HSTS_SECONDS=31536000
USE_X_FORWARDED_PROTO=True
USE_WHITENOISE=True
```

## Render

Crie serviços separados usando a mesma imagem Docker:

- Web Service:

```bash
gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 3 --timeout 120
```

- Worker:

```bash
celery -A config worker -l info
```

- Beat:

```bash
celery -A config beat -l info --schedule=/tmp/celerybeat-schedule
```

Configure também:

- PostgreSQL gerenciado e `DATABASE_URL`.
- Redis/Key Value e `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `CACHE_URL`.
- SMTP real.
- Google OAuth com URLs finais do Render/domínio.

## Arquivos Privados

Notas fiscais, comprovantes e faturas devem ser acessados pela rota autenticada:

```text
/pagamentos/<uuid>/arquivo/
```

Em produção, evite servir `media/` como pasta pública. Se usar storage externo, prefira bucket privado ou URLs assinadas.
