# Deploy no Render

Este guia prepara um deploy de teste do Gastou Lembrou no Render usando Docker,
PostgreSQL gerenciado, Render Key Value/Redis, Celery worker e Celery beat.

## Antes de Comecar

Garanta que o projeto esteja em um repositorio Git remoto, por exemplo GitHub.
O Render vai construir a imagem Docker a partir do `Dockerfile` do repositorio.

Arquivos importantes:

- `Dockerfile`
- `entrypoint.sh`
- `scripts/render-web.sh`
- `scripts/render-worker.sh`
- `scripts/render-beat.sh`
- `render.yaml`

## Opcao 1: Blueprint

Use esta opcao se quiser que o Render crie quase tudo a partir do `render.yaml`.

1. Faca push do projeto para o GitHub.
2. No Render, clique em `New +`.
3. Escolha `Blueprint`.
4. Conecte o repositorio do projeto.
5. Confirme o arquivo `render.yaml`.
6. Durante a criacao, preencha os valores marcados como `sync: false`.

Valores secretos solicitados:

```env
EMAIL_HOST_USER=principal@seudominio.com.br
EMAIL_HOST_PASSWORD=sua-senha-de-app
DEFAULT_FROM_EMAIL=Gastou Lembrou <principal@seudominio.com.br>
SUPPORT_EMAIL=suporte@seudominio.com.br
GOOGLE_CLIENT_ID=seu-client-id-google
GOOGLE_CLIENT_SECRET=seu-client-secret-google
GEMINI_API_KEY=sua-chave-gemini
```

Se ainda nao for testar Google OAuth ou Gemini, deixe as chaves vazias quando o
Render permitir, ou configure depois na tela `Environment` do servico web.

O Blueprint cria:

- `gastou-lembrou-web`: web service Docker.
- `gastou-lembrou-worker`: Celery worker.
- `gastou-lembrou-beat`: Celery beat.
- `gastou-lembrou-db`: PostgreSQL.
- `gastou-lembrou-redis`: Render Key Value/Redis.

## Opcao 2: Configuracao Manual

Crie os recursos manualmente se quiser mais controle sobre custos e planos.

### 1. Banco PostgreSQL

1. No Render, clique em `New +`.
2. Escolha `PostgreSQL`.
3. Nome sugerido: `gastou-lembrou-db`.
4. Copie a `Internal Database URL`.

### 2. Redis/Key Value

1. No Render, clique em `New +`.
2. Escolha `Key Value`.
3. Nome sugerido: `gastou-lembrou-redis`.
4. Copie a connection string interna.

### 3. Web Service

1. Clique em `New +`.
2. Escolha `Web Service`.
3. Conecte o repositorio.
4. Runtime: `Docker`.
5. Dockerfile: `./Dockerfile`.
6. Docker command:

```bash
/app/scripts/render-web.sh
```

Variaveis do web service:

```env
DEBUG=False
USE_WHITENOISE=True
USE_X_FORWARDED_PROTO=True
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
SECURE_HSTS_PRELOAD=False
RUN_MIGRATIONS=1
RUN_COLLECTSTATIC=1
DATABASE_URL=cole-a-internal-database-url
CELERY_BROKER_URL=cole-a-url-do-key-value
CELERY_RESULT_BACKEND=cole-a-url-do-key-value
CACHE_URL=cole-a-url-do-key-value
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
EMAIL_HOST_USER=principal@seudominio.com.br
EMAIL_HOST_PASSWORD=sua-senha-de-app
DEFAULT_FROM_EMAIL=Gastou Lembrou <principal@seudominio.com.br>
SUPPORT_EMAIL=suporte@seudominio.com.br
PROJECT_EMAIL_SITE_NAME=Gastou, Lembrou!
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash-lite
```

`SECRET_KEY` deve ser uma chave longa e aleatoria. Se usar Blueprint, o Render
gera automaticamente. Se configurar manualmente, gere e copie o mesmo valor para
web, worker e beat.

### 4. Worker

Crie um `Background Worker` com runtime Docker.

Docker command:

```bash
/app/scripts/render-worker.sh
```

Use as mesmas variaveis principais do web service:

- `DEBUG`
- `SECRET_KEY`
- `DATABASE_URL`
- `CELERY_BROKER_URL`
- `CELERY_RESULT_BACKEND`
- `CACHE_URL`
- configuracoes de email
- `GEMINI_API_KEY`
- `GEMINI_MODEL`

Nao configure `RUN_MIGRATIONS` nem `RUN_COLLECTSTATIC` no worker.

### 5. Beat

Crie outro `Background Worker`.

Docker command:

```bash
/app/scripts/render-beat.sh
```

Use:

- `DEBUG=False`
- `SECRET_KEY`
- `DATABASE_URL`
- `CELERY_BROKER_URL`
- `CELERY_RESULT_BACKEND`
- `CACHE_URL`

Nao configure `RUN_MIGRATIONS` nem `RUN_COLLECTSTATIC` no beat.

## URL, HTTPS e Emails

O Render define automaticamente:

- `RENDER_EXTERNAL_HOSTNAME`
- `RENDER_EXTERNAL_URL`

O projeto usa essas variaveis como fallback para:

- liberar o host do Render em `ALLOWED_HOSTS`;
- liberar a origem HTTPS em `CSRF_TRUSTED_ORIGINS`;
- montar `SITE_URL` e `EMAIL_ASSET_BASE_URL` quando essas variaveis nao forem
  definidas manualmente.

Se voce adicionar dominio proprio, defina manualmente:

```env
ALLOWED_HOSTS=seu-app.onrender.com,seu-dominio.com.br
CSRF_TRUSTED_ORIGINS=https://seu-app.onrender.com,https://seu-dominio.com.br
SITE_URL=https://seu-dominio.com.br
EMAIL_ASSET_BASE_URL=https://seu-dominio.com.br
```

## Google OAuth

Depois que o web service estiver publicado, configure no Google Cloud:

```text
https://seu-app.onrender.com/accounts/google/login/callback/
```

Se usar dominio proprio:

```text
https://seu-dominio.com.br/accounts/google/login/callback/
```

Depois preencha no Render:

```env
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
```

## Arquivos Enviados pelos Usuarios

No deploy de teste, arquivos enviados para `media/` podem ser perdidos em
rebuilds ou reinicios, dependendo da configuracao de disco do servico.

Para producao real, prefira storage externo privado, como S3/Cloudflare R2, ou
um volume persistente se o fluxo de teste aceitar essa limitacao.

## Checklist de Teste

Depois do primeiro deploy:

1. Abra a URL do web service.
2. Crie uma conta manual.
3. Confirme o email.
4. Teste login/logout.
5. Teste redefinicao de senha.
6. Crie um pagamento simples.
7. Teste upload de nota fiscal.
8. Teste pagamento agendado e confirme se o worker envia email.
9. Teste dashboard, relatorio PDF e insight de IA.
10. Teste suporte com screenshot.
11. Verifique logs do web, worker e beat no Render.

## Comandos Locais de Validacao

Antes de fazer push:

```powershell
python manage.py check
python manage.py test
docker compose -f docker-compose.prod.yml up --build
```
