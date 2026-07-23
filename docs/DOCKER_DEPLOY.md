# Docker e Deploy

Este guia resume como rodar o Gastou Lembrou em Docker para desenvolvimento e
como preparar um deploy generico em producao.

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

Servicos locais:

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

## Producao Local Simulada

Use o compose de producao apenas para simular um ambiente mais proximo do deploy:

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

Para producao real com HTTPS, use valores seguros:

```env
DEBUG=False
SECRET_KEY=uma-chave-longa-e-aleatoria
ALLOWED_HOSTS=seu-dominio.com.br,www.seu-dominio.com.br
CSRF_TRUSTED_ORIGINS=https://seu-dominio.com.br,https://www.seu-dominio.com.br
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

## Producao em Docker

Em um deploy real, use servicos separados usando a mesma imagem Docker:

- Aplicacao web:

```bash
gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 120 --access-logfile -
```

- Worker:

```bash
celery -A config worker -l info
```

- Beat:

```bash
celery -A config beat -l info --schedule=/tmp/celerybeat-schedule
```

Configure tambem:

- PostgreSQL gerenciado e `DATABASE_URL`.
- Redis e `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `CACHE_URL`.
- SMTP real.
- Google OAuth com URLs finais do dominio.

## Arquivos Privados

Notas fiscais, comprovantes e faturas devem ser acessados pela rota autenticada:

```text
/pagamentos/<uuid>/arquivo/
```

Em producao, evite servir `media/` como pasta publica. Se usar storage externo,
prefira bucket privado ou URLs assinadas.
