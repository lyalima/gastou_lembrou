# 💸 Gastou Lembrou

SaaS Django para organização de gastos pessoais, lembretes de pagamentos,
dashboard financeiro, importação de extratos/faturas, relatórios PDF, metas
mensais e insights com IA.

O projeto foi pensado para uso pessoal/financeiro: cada usuário acessa apenas os
próprios dados, pode cadastrar pagamentos, importar arquivos, acompanhar metas e
receber emails automáticos de confirmação, lembretes e relatórios.

## 📌 Visão geral

O Gastou Lembrou combina controle manual de pagamentos com automações úteis:

- pagamentos comuns, agendados, parcelados e recorrentes;
- categorias globais e categorias personalizadas por usuário;
- formas de pagamento, incluindo cartão de crédito;
- importação de extrato bancário em CSV/OFX/PDF, com seleção antes de salvar;
- importação de fatura de cartão em PDF;
- dashboard mensal ou geral;
- metas mensais de gastos com alertas por email;
- relatórios PDF;
- insights financeiros e assistente Spike com Gemini;
- suporte autenticado;
- PWA básico para teste em dispositivos móveis.

## ✨ Funcionalidades

- Cadastro e login por email/senha, com confirmação de email obrigatória.
- Login/cadastro social com Google OAuth.
- Redefinição de senha para contas criadas manualmente.
- Aceite versionado de Termos de Uso e Política de Privacidade.
- Perfil com telefone internacional, CPF opcional bloqueado após cadastro e
  exclusão permanente da conta.
- CRUD de pagamentos com HTMX, filtros, busca, ordenação e paginação.
- Separação entre pagamentos comuns e lançamentos futuros de compras parceladas.
- Criação automática de parcelas anteriores/posteriores em compras parceladas.
- Categorias globais e categorias personalizadas por usuário.
- Sugestão automática de categoria quando o pagamento é criado sem categoria.
- Formas de pagamento, incluindo identificação de gastos em cartão de crédito.
- Upload de comprovantes/notas em JPG, PNG ou PDF.
- Importação de extrato bancário em CSV/OFX/PDF, com prévia, seleção e pagamentos em Pix.
- Páginas de Meus cartões e Faturas, com consulta por cartão e mês de vencimento.
- Recorrências mensais, trimestrais, semestrais ou anuais, geradas como agendamentos.
- Importação de fatura de cartão em PDF com pré-visualização dos lançamentos.
- Dashboard com filtro mensal, gráficos, evolução temporal e resumo.
- Metas mensais de gastos com barra de progresso e alertas por email em múltiplos
  percentuais.
- Relatório PDF mensal e envio automático no primeiro dia do mês.
- Insights financeiros com Gemini 2.5 Flash-Lite, com fallback local.
- Spike com LangChain/LangGraph, tools financeiras isoladas por usuário, RAG
  documental e conversa persistente entre páginas.
- Criação de gastos pelo Spike mediante pedido explícito e confirmação na janela de revisão.
- Integração opcional com Google Agenda para pagamentos agendados selecionados.
- Suporte autenticado por email com upload opcional de screenshot.
- Emails HTML padronizados com fallback texto simples.
- PWA básico com manifest e página offline.
- Modo claro/escuro na área autenticada.

## 🧱 Stack

Python e bibliotecas utilizados pelo projeto:

- Python 3.12
- Django 5
- Django Allauth
- PostgreSQL via `DATABASE_URL`, com SQLite como fallback local
- Redis + Celery + Celery Beat
- HTMX e JavaScript leve
- Tailwind via CDN
- Chart.js
- OpenCV, Pillow e PyMuPDF
- Gemini API
- LangChain, LangGraph e `langchain-google-genai`
- Gunicorn e WhiteNoise
- Docker e Docker Compose

## 📅 Regra de datas do produto

Dashboard, metas, relatórios e filtros de dia/mês/ano usam a **data da compra** no crédito.
Nas demais formas, usam a data prevista quando agendado ou a data de pagamento.
A página de faturas e a área **Cartões e faturas** continuam agrupadas pelo vencimento.
Compras no fechamento entram no ciclo seguinte; fechamento em domingo é antecipado para sábado.
Pagamento de fatura não entra novamente no total de gastos. Parcelas têm datas próprias,
mas a separação visual das parcelas futuras com cartão ainda considera o vencimento.

Consulte os [fluxos de pagamentos](docs/PAYMENT_WORKFLOWS.md) e o [guia de IA](docs/SPIKE_AI_ARCHITECTURE.md).
As consultas financeiras do Spike usam as mesmas datas do dashboard e dos relatórios.

## ✅ Pré-requisitos

Para rodar localmente com `venv`, instale:

- Git
- Python 3.12+
- PostgreSQL, se quiser usar banco igual ao ambiente Docker/produção
- Redis, necessário para Celery, emails em background, lembretes, relatórios e
  tarefas agendadas

Para rodar com Docker, instale:

- Docker
- Docker Compose

No Linux, algumas bibliotecas do sistema podem ser necessárias para PostgreSQL,
OpenCV, Pillow e processamento de PDFs:

```bash
sudo apt update
sudo apt install -y build-essential libpq-dev libglib2.0-0 libgl1 netcat-openbsd
```

No Windows, a forma mais simples de usar PostgreSQL e Redis localmente é via
Docker Desktop ou WSL.

## ⚙️ Variáveis de ambiente

Antes de rodar o projeto, crie o arquivo `.env` a partir do exemplo.
Faça essa cópia apenas no primeiro setup: não sobrescreva um `.env` já configurado.

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Linux/macOS:

```bash
cp .env.example .env
```

Depois, revise o `.env` e preencha conforme necessário:

- `SECRET_KEY`
- `DEBUG`
- `ALLOWED_HOSTS`
- `CSRF_TRUSTED_ORIGINS`
- `SITE_URL`
- `EMAIL_ASSET_BASE_URL`
- `DATABASE_URL`
- `EMAIL_*`
- `SUPPORT_EMAIL`
- `CELERY_BROKER_URL`
- `CELERY_RESULT_BACKEND`
- `CACHE_URL`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GEMINI_API_KEY`

Sem `DATABASE_URL`, o projeto usa SQLite local. O backend padrão de email é console.
Ao selecionar SMTP, credenciais ausentes ou incorretas causam falha de envio, não troca automática para console.
Defina também `SPIKE_MONTHLY_MESSAGE_LIMIT` (exemplo: `20`; `0` desativa apenas a cota local, não a do Gemini).

## 🧪 Setup local com venv

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
# Configure o .env conforme a seção anterior antes de continuar.
python manage.py migrate
python manage.py sync_spike_knowledge
python manage.py createsuperuser
python manage.py runserver
```

Se o comando `py -3.12` não estiver disponível, use:

```powershell
python -m venv .venv
```

### Linux/macOS

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
# Configure o .env conforme a seção anterior antes de continuar.
python manage.py migrate
python manage.py sync_spike_knowledge
python manage.py createsuperuser
python manage.py runserver
```

Se `python3.12` não estiver disponível, use o comando correspondente da sua
instalação, por exemplo `python3`.

Com o servidor rodando, acesse:

```text
http://127.0.0.1:8000/
```

## 🗄️ Banco de dados local

Por padrão, se `DATABASE_URL` estiver vazio, o Django usa SQLite local. Isso é
útil para testes rápidos.

Para usar PostgreSQL local, configure no `.env`:

```env
DATABASE_URL=postgres://usuario:senha@localhost:5432/gastou_lembrou
```

Depois execute:

```bash
python manage.py migrate
python manage.py createsuperuser
```

No Docker, o PostgreSQL já é iniciado pelo `docker compose`.

## 🚦 Redis, Celery e Celery Beat

O Redis é usado como broker/backend do Celery. Sem Redis, o site pode abrir, mas
as tarefas em background não funcionarão corretamente.

Essas tarefas incluem:

- envio de confirmação de email;
- emails de suporte;
- lembretes de pagamentos agendados;
- alertas de metas mensais;
- envio mensal de relatórios;
- tarefas assíncronas relacionadas a importações e automações.

### Subindo Redis com Docker

Essa é a opção mais simples no Windows:

```powershell
docker run --name gastou-redis -p 127.0.0.1:6379:6379 -d redis:7-alpine
```

Para testar se está funcionando:

```powershell
docker exec gastou-redis redis-cli ping
```

A resposta esperada é:

```text
PONG
```

### Subindo Redis no Linux

Ubuntu/Debian:

```bash
sudo apt update
sudo apt install -y redis-server
sudo systemctl enable --now redis-server
redis-cli ping
```

A resposta esperada é:

```text
PONG
```

### Configurando Redis no `.env`

Use estes valores para desenvolvimento local:

```env
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
CACHE_URL=redis://localhost:6379/2
```

### Rodando Celery

Com o Django já configurado, abra terminais separados.

Worker no Windows:

```powershell
celery -A config worker -l info -P solo
```

Worker no Linux/macOS:

```bash
celery -A config worker -l info
```

Beat, em outro terminal:

```bash
celery -A config beat -l info
```

No Windows, use `-P solo` no worker. O pool padrão do Celery usa
multiprocessing e pode falhar com `PermissionError: [WinError 5] Acesso negado`.

## 🐳 Setup local com Docker

Crie o `.env`:

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Linux/macOS:

```bash
cp .env.example .env
```

Suba os serviços:

```bash
docker compose up --build
```

Depois, em outro terminal:

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py sync_spike_knowledge
docker compose exec web python manage.py createsuperuser
```

O Docker Compose sobe os serviços principais do ambiente local, incluindo Django,
PostgreSQL, Redis, Celery e Celery Beat, conforme definido nos arquivos do
projeto.

## ✉️ Emails

Para enviar email real, configure SMTP no `.env`:

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

No Gmail, use senha de app, não a senha normal da conta.

O projeto separa:

- email principal do sistema, usado para confirmações, lembretes, alertas e
  relatórios;
- email de suporte, usado como destinatário/resposta das mensagens enviadas pelo
  formulário de suporte.

Os emails usam template HTML padronizado e fallback em texto simples.

## 🔑 Google OAuth

Configure no Google Cloud o callback local:

```text
http://127.0.0.1:8000/accounts/google/login/callback/
```

E preencha no `.env`:

```env
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
```

No admin do Django, confira o domínio configurado em `Sites`. Para ambiente
local, normalmente ele deve apontar para:

```text
127.0.0.1:8000
```

## 🤖 Gemini e IA

Para habilitar insights, classificações, o agente Spike e o RAG semântico,
configure:

```env
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash-lite
GEMINI_TIMEOUT_SECONDS=30
GEMINI_EMBEDDING_MODEL=models/gemini-embedding-001
SPIKE_RAG_ENABLED=True
SPIKE_RAG_EMBEDDINGS_ENABLED=True
```

Sem `GEMINI_API_KEY`, o projeto deve usar os fallbacks locais implementados nas
funcionalidades em que isso é possível.

Depois das migrações, sincronize a documentação do Spike:

```bash
python manage.py sync_spike_knowledge --with-embeddings
```

Sem `--with-embeddings`, a base continua funcionando com recuperação lexical.
Em produção, o container web executa essa sincronização automaticamente depois
das migrações.

## 📎 Uploads e mídias

O projeto aceita:

- notas/comprovantes de pagamentos em JPG, PNG ou PDF;
- screenshots no suporte em JPG ou PNG;
- extratos bancários em CSV/OFX/PDF;
- faturas de cartão em PDF.

Os arquivos de pagamentos devem continuar protegidos por rotas autenticadas e
filtradas pelo dono do arquivo.

Em produção, evite servir `media/` como pasta pública sem controle de acesso.

## 📱 PWA

O projeto possui manifest, ícones e página offline para teste como PWA.
O service worker guarda recursos estáticos, não páginas financeiras autenticadas.
Cadastro, consultas, chat e integrações exigem conexão; não há sincronização de gastos offline.

Para o PWA funcionar corretamente em dispositivo móvel, o ambiente de produção
precisa estar em HTTPS e com `SITE_URL` configurado com o domínio real.

## 🧾 Relatórios

O dashboard permite gerar relatório PDF mensal. Também existe envio automático
por email no primeiro dia do mês, referente ao mês anterior.

Para esse envio automático funcionar, mantenha:

- Redis ativo;
- Celery worker ativo;
- Celery Beat ativo;
- SMTP configurado.

## 🧪 Testes e checks

Checks básicos:

```bash
python manage.py check
```

Suite completa:

```bash
python manage.py test
```

Testes por app:

```bash
python manage.py test accounts
python manage.py test payments
python manage.py test dashboard
python manage.py test support
python manage.py test assistant
```

Se estiver usando Docker:

```bash
docker compose exec web python manage.py check
docker compose exec web python manage.py test
```

Alguns testes podem depender de variáveis de ambiente, banco, Redis, SMTP fake ou
serviços configurados conforme o cenário testado.

## 🚀 Deploy

O projeto possui `Dockerfile` e compose para simular produção. Veja:

[docs/DOCKER_DEPLOY.md](docs/DOCKER_DEPLOY.md)

Para produção real:

- use `DEBUG=False`;
- defina `SECRET_KEY` forte;
- configure `ALLOWED_HOSTS`;
- configure `CSRF_TRUSTED_ORIGINS`;
- configure `SITE_URL`;
- configure `EMAIL_ASSET_BASE_URL`;
- use PostgreSQL;
- use Redis;
- configure SMTP real;
- use HTTPS;
- configure armazenamento de mídia de forma segura;
- rode migrations antes de liberar o acesso;
- mantenha Celery worker e Celery Beat ativos.

## 🔐 Segurança e privacidade

- Não versione `.env`, banco local, uploads ou arquivos gerados.
- Não exponha `SECRET_KEY`, senhas de app, tokens do Google ou chave do Gemini.
- Arquivos de pagamentos são acessados por rota autenticada e filtrada pelo dono.
- Uploads validam extensão, assinatura e tamanho.
- Consultas de pagamentos, categorias personalizadas, metas e relatórios são
  isoladas por usuário autenticado.
- Dados enviados ao Gemini devem ser reduzidos ao necessário para cada
  funcionalidade.
- Para produção, configure HTTPS, cookies seguros e origens confiáveis.

## 📚 Documentação complementar

- [Guia Docker/deploy](docs/DOCKER_DEPLOY.md)
- [Guia para desenvolvedores](docs/DEV_GUIDE.md)
- [Controles e checklist de segurança (não é certificação)](docs/SECURITY_REVIEW.md)
- [Arquitetura de IA do Spike](docs/SPIKE_AI_ARCHITECTURE.md)
- [Cartões, recorrências e confirmação de alterações pelo Spike](docs/PAYMENT_WORKFLOWS.md)
- [Base de conhecimento do Spike](docs/knowledge_base/)

Documentação revisada em 13/10/2026. Após atualizar os arquivos da base do Spike,
sincronize o conteúdo no ambiente em execução (sem chamadas de embeddings):

```bash
docker compose exec web python manage.py sync_spike_knowledge
```

Essa sincronização atualiza o RAG, não treina o modelo. Os resumos documentais não
substituem os Termos de Uso e a Política de Privacidade exibidos pela aplicação.
