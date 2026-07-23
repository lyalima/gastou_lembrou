# Guia técnico para devs - Gastou Lembrou

Este documento descreve o funcionamento interno do projeto para facilitar manutenção, onboarding e evolução do MVP.

## Visão geral

O Gastou Lembrou é um SaaS Django para gerenciamento pessoal de pagamentos. O sistema permite cadastro/login por email e Google, CRUD de pagamentos, upload de notas fiscais, dashboard com métricas financeiras, relatórios PDF, suporte por email e lembretes de pagamentos agendados.

Stack principal:

- Python 3.11+
- Django 5
- Django Allauth
- Celery + Redis
- SQLite local ou PostgreSQL via `DATABASE_URL`
- Tailwind via CDN
- HTMX para modais e CRUD sem reload completo
- Chart.js para gráficos
- PyMuPDF para geração de PDF
- OpenCV/Pillow/PyMuPDF para tratamento de uploads de nota fiscal

## Apps Django

### `accounts`

Responsável por usuário customizado, perfil, senha, validação de email e autenticação social.

Principais arquivos:

- `accounts/models.py`: define `User`, sem `username`, com login por email.
- `accounts/managers.py`: criação de usuário/superusuário.
- `accounts/forms.py`: formulários de admin/perfil.
- `accounts/views.py`: perfil e troca de senha.
- `accounts/adapters.py`: customização do Allauth para emails HTML, envio em background e ocultar mensagens de login/logout.
- `accounts/social_adapters.py`: customização do login social Google.
- `accounts/signals.py`: sincroniza `email_verified` e email primário após confirmação.

Regras importantes:

- O login padrão é por email/senha.
- `username` não existe no model.
- A confirmação de email é obrigatória para cadastro por email.
- Ao alterar email no perfil:
  - o email antigo é removido de `EmailAddress`;
  - o novo email vira primário, não verificado;
  - uma nova confirmação é enviada;
  - o usuário é deslogado até confirmar.
- CPF só pode ser cadastrado uma vez; depois disso o form preserva o CPF original.
- Telefone usa validação backend e máscara/frontend com seleção de país.
- Todo novo cadastro exige aceite dos Termos de Uso e ciência da Política de Privacidade.
- O aceite é versionado em `LegalAcceptance`, com data/hora, origem, IP e user-agent.
- Novos cadastros Google passam por `socialaccount_signup`; logins Google de contas existentes continuam diretos.
- As versões vigentes ficam centralizadas em `accounts/legal.py`.
- A página de perfil possui exclusão permanente com confirmação textual.
- A exclusão remove a conta, registros relacionados por cascade e arquivos de notas fiscais no armazenamento.

### `payments`

Responsável por categorias, formas de pagamento, pagamentos, uploads de nota fiscal e lembretes.

Principais models:

- `Category`
  - `name`
  - `description`
  - timestamps
  - não pertence a usuário; categorias são globais e administradas pelo admin/staff.
- `PaymentMethod`
  - `name`
  - timestamps
  - usado em `Payment.payment_method`.
- `Payment`
  - UUID como PK
  - FK para usuário
  - FK para categoria
  - FK opcional para forma de pagamento
  - valor
  - `payment_date`
  - `scheduled_date`
  - arquivo de nota fiscal
  - timestamps
- `PaymentNotification`
  - controla emails já enviados para evitar duplicidade.
  - tipos atuais:
    - confirmação de agendamento;
    - lembrete de 1 dia antes;
    - lembrete do dia do vencimento.

CRUD:

- Listagem em `/pagamentos/`.
- Modais HTMX para criar, editar, visualizar e excluir.
- Pagamentos sempre são filtrados pelo usuário autenticado.
- Categorias só podem ser criadas por staff/superuser.
- Usuários comuns não veem o botão de nova categoria.

Filtros da listagem:

- Busca por título/descrição.
- Categoria.
- Forma de pagamento.
- Dia exato.
- Mês.
- Ano.
- Status de agendamento.
- Ordenação.
- Paginação preserva filtros e possui primeira/anterior/próxima/última página.

Uploads de nota fiscal:

- Campo é `FileField`, não `ImageField`, para aceitar PDF.
- Tipos aceitos no backend:
  - JPG/JPEG;
  - PNG;
  - PDF.
- PDFs são salvos sem processamento.
- PNGs são salvos sem processamento para preservar screenshots/cortes.
- JPG/JPEG passam pelo processamento de imagem com OpenCV.

Signal importante:

- `payments/signals.py`
- Antes de salvar um pagamento:
  - se `scheduled_date` existir e `payment_date` estiver vazio;
  - então `payment_date` recebe o mesmo valor de `scheduled_date`.

Isso mantém relatórios, dashboard e filtros mensais coerentes para pagamentos agendados.

Categorização automática:

- `Payment.category` é opcional.
- Um `post_save` agenda `payments.tasks.categorize_payment` somente quando um novo pagamento não tem categoria.
- A seleção local tenta correspondência por nome e palavras-chave.
- Sem correspondência clara, o Gemini recebe apenas o título e a lista de categorias existentes.
- O resultado é validado contra os IDs existentes; a IA não cria categorias.
- Se o usuário escolher uma categoria, nenhuma categorização automática é executada.

### `dashboard`

Responsável pela página de métricas, gráficos, filtro mensal, relatório PDF e envio mensal automático.

Principais arquivos:

- `dashboard/views.py`: dashboard e download do PDF.
- `dashboard/metrics.py`: fonte única das métricas.
- `dashboard/reports.py`: geração do PDF com PyMuPDF.
- `dashboard/tasks.py`: envio mensal automático do relatório por email.

Métricas calculadas:

- Total registrado.
- Total de pagamentos.
- Pagamentos agendados.
- Total por categoria.
- Evolução temporal.
- Total por forma de pagamento.
- Últimos pagamentos.
- Pagamentos registrados no relatório.

Insights inteligentes:

- O painel usa o mesmo período selecionado no filtro do dashboard.
- A geração é iniciada por HTMX e executada em background pelo Celery.
- Os resultados são armazenados em `FinancialInsightSnapshot`, isolados por usuário e período.
- Com `GEMINI_API_KEY`, o backend usa o Gemini 2.5 Flash-Lite com Structured Outputs.
- Sem chave ou em caso de falha da API, o sistema usa um fallback local baseado nas mesmas métricas.
- O payload externo contém somente métricas agregadas; não envia email, CPF, telefone ou notas fiscais.

Configuração:

```env
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash-lite
GEMINI_TIMEOUT_SECONDS=30
```

O contrato de saída está definido como JSON Schema em `dashboard/insights.py`.

Filtro do dashboard:

- A página possui filtro `month=YYYY-MM`.
- Opção vazia significa "Ver tudo".
- Em "Ver tudo":
  - o gráfico de evolução agrupa por mês.
- Quando um mês específico é selecionado:
  - cards, gráficos, formas de pagamento e últimos pagamentos usam somente o mês escolhido;
  - o gráfico de evolução passa a agrupar por dia do mês.

Regra de data efetiva:

Para métricas mensais, o sistema usa:

1. `payment_date`, quando existe.
2. `scheduled_date`, quando `payment_date` está vazio.

Isso preserva pagamentos agendados antigos que ainda possam estar com `payment_date` vazio.

Relatório PDF:

- Rota: `/dashboard/relatorio.pdf?month=YYYY-MM`
- Gera PDF mensal com:
  - cabeçalho da marca;
  - resumo;
  - gastos por categoria;
  - evolução mensal;
  - gastos por forma de pagamento;
  - pagamentos registrados.
- Nome do arquivo:
  - `relatorio-gastou-lembrou-YYYY-MM.pdf`

Envio mensal automático:

- Task: `dashboard.tasks.send_previous_month_reports`
- Agendada no Celery Beat para todo dia 1, às 08:00.
- Gera relatório referente ao mês anterior.
- Envia somente para usuários ativos com pagamentos no período.
- Anexa o PDF ao email usando o template visual padrão.

### `support`

Responsável pelo formulário de suporte autenticado.

Regras:

- Usuário precisa estar logado.
- Campo email é somente leitura e usa o email do usuário autenticado.
- Formulário envia:
  - nome;
  - email;
  - problema;
  - screenshot opcional.
- Screenshot aceita somente JPG/JPEG ou PNG no backend.
- Tamanho máximo: 5 MB.
- Email é enviado em background via Celery.
- Screenshot é preservado como anexo.

### `core`

Responsável por home pública, helpers de email e tarefas compartilhadas.

Principais arquivos:

- `core/views.py`: home pública.
- `core/context_processors.py`: expõe flags como `google_oauth_configured`.
- `core/emails.py`: helper central para emails HTML com fallback texto.
- `core/tasks.py`: wrappers Celery para envio de emails.

Emails:

- Todos os emails usam template visual em `templates/emails/`.
- O helper principal é `send_branded_email`.
- Existe fallback texto simples.
- Logo é carregada por URL absoluta baseada em `EMAIL_ASSET_BASE_URL`, evitando que o PNG apareça como anexo no cliente de email.
- `queue_branded_email` tenta enviar via Celery; se o broker falhar, cai para envio síncrono.

## Autenticação

### Email e senha

Configuração principal em `config/settings.py`:

- `ACCOUNT_LOGIN_METHODS = {"email"}`
- `ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]`
- `ACCOUNT_USER_MODEL_USERNAME_FIELD = None`
- `ACCOUNT_EMAIL_VERIFICATION = "mandatory"`
- `ACCOUNT_UNIQUE_EMAIL = True`

O Allauth cuida de cadastro, login, logout e confirmação de email. Os templates foram sobrescritos em `templates/account/`.

### Google OAuth

O provider Google está configurado via Allauth.

Configuração principal:

- `allauth.socialaccount`
- `allauth.socialaccount.providers.google`
- `SOCIALACCOUNT_ADAPTER = "accounts.social_adapters.SocialAccountAdapter"`
- `SOCIALACCOUNT_PROVIDERS["google"]["EMAIL_AUTHENTICATION"] = True`

Fluxo:

1. Usuário clica em "Entrar com Google" ou "Cadastrar com Google".
2. Allauth abre `/accounts/google/login/`.
3. Template customizado em `templates/socialaccount/login.html`.
4. Usuário continua para o Google.
5. Google retorna para `/accounts/google/login/callback/`.
6. Se o Google informar email verificado:
   - usuário é criado ou vinculado;
   - `email_verified=True`;
   - `EmailAddress` é marcado como primário/verificado.

Para testar localmente, o Google Cloud deve ter redirect URI:

```text
http://127.0.0.1:8000/accounts/google/login/callback/
```

E o `.env` deve conter:

```env
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
```

## Celery e Redis

Celery é usado para:

- emails de confirmação do Allauth;
- emails de suporte;
- confirmação de pagamento agendado;
- lembretes de pagamento;
- envio mensal de relatório PDF.

Comandos locais:

```powershell
celery -A config worker -l info -P solo
celery -A config beat -l info
```

No Windows, use `-P solo` no worker. O pool padrao do Celery usa multiprocessing via `billiard` e pode falhar com `PermissionError: [WinError 5] Acesso negado`.

Agendamentos atuais:

- `payments.tasks.send_payment_reminders`
  - verifica lembretes de pagamentos agendados.
- `dashboard.tasks.send_previous_month_reports`
  - todo dia 1, 08:00, envia relatório do mês anterior.

Para testar manualmente o envio do relatório mensal:

```powershell
python manage.py shell
```

```python
from dashboard.tasks import send_previous_month_reports
send_previous_month_reports()
```

Ou via worker:

```python
send_previous_month_reports.delay()
```

## Emails do sistema

Tipos principais:

- Confirmação de email/cadastro.
- Email após alteração de email no perfil.
- Confirmação imediata de pagamento agendado.
- Lembrete 1 dia antes.
- Lembrete no dia do vencimento.
- Suporte.
- Relatório mensal PDF.

Templates:

- Base visual: `templates/emails/base.html`
- Mensagem genérica: `templates/emails/message.html`
- Allauth:
  - `templates/account/email/email_confirmation_message.html`
  - `templates/account/email/email_confirmation_signup_message.html`
  - `.txt` correspondentes como fallback.

Configurações úteis:

- `EMAIL_BACKEND`
- `DEFAULT_FROM_EMAIL`: remetente principal do sistema, usado para confirmação de conta, lembretes, relatórios, atualização de termos e notificações internas.
- `SUPPORT_EMAIL`: caixa de suporte que recebe mensagens do formulário e aparece como contato público nos documentos legais.
- `SITE_URL`
- `EMAIL_ASSET_BASE_URL`: URL pública usada pelos clientes de email para carregar a logo e assets estáticos. Em Docker local, `http://127.0.0.1:8000` funciona para clientes locais; em Gmail/Outlook, use um túnel HTTPS público ou domínio real, não `http://web:8000`.
- `PROJECT_EMAIL_SITE_NAME`

Não versionar credenciais reais em `.env.example`, README ou documentação.

## Frontend

O projeto não usa SPA. O frontend é Django templates com:

- Tailwind via CDN.
- CSS próprio em `static/css/app.css`.
- JavaScript leve em `static/js/app.js`.
- HTMX para modais de pagamentos/categorias.
- Chart.js para gráficos do dashboard.
- Font Awesome para ícones.
- `intl-tel-input` para telefone internacional no perfil.

Tema:

- Área logada possui alternância light/dark.
- O tema fica em `localStorage`.
- Modais de pagamentos têm suporte ao modo dark.

## Rotas principais

Públicas:

- `/`
- `/accounts/login/`
- `/accounts/signup/`
- `/accounts/google/login/`
- `/accounts/logout/`

Autenticadas:

- `/pagamentos/`
- `/dashboard/`
- `/dashboard/relatorio.pdf?month=YYYY-MM`
- `/suporte/`
- `/perfil/`
- `/perfil/senha/`

Admin:

- `/admin/`

## Dados e isolamento

Pagamentos sempre devem ser filtrados por `request.user`.

Categorias e formas de pagamento são globais:

- `Category`
- `PaymentMethod`

Pagamentos são privados por usuário:

- `Payment.user`

Ao criar novas consultas, manter esse padrão:

```python
Payment.objects.filter(user=request.user)
```

## Validações importantes

### CPF

- Backend: `accounts.validators.validate_cpf`
- Frontend: máscara e feedback em `static/js/app.js`

### Telefone

- Backend: `accounts.validators.validate_phone`
- Frontend:
  - `intl-tel-input`;
  - limite de caracteres;
  - feedback de validade.

### Nota fiscal em pagamentos

Aceitos:

- JPG/JPEG
- PNG
- PDF

PDF e PNG são preservados. JPG/JPEG passa por processamento.

### Screenshot no suporte

Aceitos:

- JPG/JPEG
- PNG

## Testes

Comando geral:

```powershell
python manage.py test
```

Testes por app:

```powershell
python manage.py test accounts
python manage.py test payments
python manage.py test dashboard
python manage.py test support
```

Coberturas importantes já existentes:

- Usuário sem `username`.
- Login/cadastro por email.
- Confirmação de email.
- Alteração de email no perfil.
- Google OAuth adapter e templates.
- Isolamento de pagamentos por usuário.
- CRUD/filtros/paginação de pagamentos.
- Upload de JPG/PNG/PDF em pagamentos.
- Upload de screenshot no suporte.
- Envio de email de suporte.
- Lembretes e controle de duplicidade.
- Dashboard, filtro mensal e PDF.
- Envio mensal de relatório.

## Cuidados ao evoluir

- Não remover o isolamento por usuário em consultas de pagamentos.
- Não sobrescrever `payment_date` quando já vier preenchida.
- Manter `PaymentNotification` para evitar emails duplicados.
- Ao mexer em emails, preservar fallback texto simples.
- Ao mexer em OAuth, testar login por email/senha novamente.
- Ao mexer em dashboard/relatórios, lembrar que ambos usam `dashboard/metrics.py`.
- Ao mexer em uploads de nota fiscal, preservar a regra:
  - PDF sem processamento;
  - PNG sem processamento;
  - JPG/JPEG com processamento.
- Não versionar credenciais reais.
