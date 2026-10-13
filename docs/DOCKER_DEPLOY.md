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
docker compose exec web python manage.py sync_spike_knowledge
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
POSTGRES_DB=gastou_lembrou
POSTGRES_USER=gastou_lembrou
POSTGRES_PASSWORD=troque-esta-senha
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
- Credenciais fortes para `POSTGRES_USER` e `POSTGRES_PASSWORD` se o banco rodar
  no proprio Docker Compose.

## Arquivos Privados

Notas fiscais e comprovantes vinculados a pagamentos são acessados pela rota autenticada:

```text
/pagamentos/<uuid>/arquivo/
```

Em producao, evite servir `media/` como pasta publica. Se usar storage externo,
prefira bucket privado ou URLs assinadas.

Faturas importadas e seus itens são recursos separados; a rota acima não é um
endpoint genérico para baixar qualquer documento. Nunca exponha o volume inteiro.

## Atualizações e persistência

Não sobrescreva `.env` nem execute `docker compose down -v` para atualizar: `-v`
remove volumes, inclusive banco e mídias. Faça backup de ambos e teste restauração.
No desenvolvimento, o código é montado em `/app`; reinicie workers após alterações
Python. Na produção, reconstrua a imagem para incorporar código e documentação:

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec web python manage.py check --deploy
```

O entrypoint do web executa migrações, sincronização do RAG e collectstatic conforme
as flags do Compose. Não execute múltiplos Beats. O Compose de produção inclui banco
PostgreSQL local; banco gerenciado é uma opção que exige adaptar suas configurações.

O arquivo atual publica a porta 8000 e não configura TLS, domínio, proxy reverso,
backups automáticos nem storage S3. Em Lightsail, configure DNS no Registro.br,
proxy com certificado HTTPS e firewall, evitando acesso público direto ao app/banco/Redis.
`USE_X_FORWARDED_PROTO` exige proxy confiável que sobrescreva o cabeçalho recebido.
O volume `media_data` precisa de persistência e backup; WhiteNoise serve estáticos,
não deve tornar uploads privados públicos. O PWA requer HTTPS no celular e continua
dependente de conexão para dados financeiros, chat e gravações.
