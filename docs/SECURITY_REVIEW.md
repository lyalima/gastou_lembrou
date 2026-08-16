# Revisão de Segurança - Gastou Lembrou

Este documento resume os principais pontos de segurança do projeto e os cuidados
necessários antes de publicar o sistema em produção.

## Escopo analisado

- Autenticação por email/senha e Google OAuth.
- Confirmação de email e redefinição de senha.
- Isolamento de dados por usuário autenticado.
- Uploads de notas, comprovantes, extratos, faturas e screenshots.
- Emails em background com Celery.
- Integrações externas: SMTP, Google OAuth e Gemini.
- Docker, variáveis de ambiente e preparação para deploy.

## Pontos já implementados

- Usuário customizado com login por email.
- Confirmação obrigatória de email.
- Redefinição de senha apenas para contas com senha utilizável.
- Rotas autenticadas protegidas com `LoginRequiredMixin`.
- Consultas principais filtradas pelo usuário autenticado.
- Arquivos de pagamentos servidos por rota autenticada.
- Validação de extensão, assinatura e tamanho em uploads críticos.
- Proteção CSRF padrão do Django preservada nos formulários.
- `.env` ignorado pelo Git.
- Configurações sensíveis carregadas por variáveis de ambiente.
- Emails enviados em background quando Celery/Redis estão disponíveis.
- Fallback local para insights caso Gemini não esteja configurado ou falhe.
- Termos de Uso e Política de Privacidade com aceite versionado.

## Pontos de atenção antes da produção

### Variáveis de ambiente

Confirme que nenhuma credencial real foi versionada:

- `SECRET_KEY`
- `EMAIL_HOST_PASSWORD`
- `GOOGLE_CLIENT_SECRET`
- `GEMINI_API_KEY`
- senhas de banco de dados
- URLs privadas de Redis/PostgreSQL

Em produção, use:

```env
DEBUG=False
SECRET_KEY=<valor-forte-e-secreto>
ALLOWED_HOSTS=seudominio.com.br,www.seudominio.com.br
CSRF_TRUSTED_ORIGINS=https://seudominio.com.br,https://www.seudominio.com.br
SITE_URL=https://seudominio.com.br
EMAIL_ASSET_BASE_URL=https://seudominio.com.br
```

### HTTPS e cookies

Com `DEBUG=False`, mantenha:

- `SESSION_COOKIE_SECURE=True`
- `CSRF_COOKIE_SECURE=True`
- HTTPS ativo no domínio principal

Sem HTTPS, recursos como PWA, cookies seguros e fluxos OAuth ficam mais frágeis.

### Uploads e mídia

Os arquivos enviados pelos usuários podem conter dados financeiros e pessoais.
Não sirva a pasta `media/` diretamente como pública em produção.

Recomendações:

- manter acesso aos arquivos por views autenticadas;
- filtrar sempre pelo dono do arquivo;
- limitar tamanho máximo por tipo de upload;
- usar storage privado quando migrar para serviço externo;
- evitar expor URLs permanentes públicas para notas, extratos e faturas.

### Emails e Celery

Se SMTP estiver incorreto e Celery estiver ativo, a falha tende a aparecer no log
do worker, não na tela do usuário.

Recomendações:

- monitorar logs do Celery;
- testar confirmação de email, suporte, lembretes e relatórios após deploy;
- manter Redis protegido por senha/rede privada;
- não expor Redis publicamente na internet.

### Google OAuth

No Google Cloud, configure apenas callbacks esperados:

```text
https://seudominio.com.br/accounts/google/login/callback/
```

Evite deixar callbacks locais ou domínios antigos habilitados em produção.

### Gemini

O projeto usa o Gemini apenas para funcionalidades específicas. Mesmo assim:

- envie somente os dados necessários;
- não envie arquivos completos quando não for indispensável;
- mantenha fallback local para falhas;
- monitore custos e limites de uso.

## Checklist de deploy seguro

- [ ] `DEBUG=False`.
- [ ] `SECRET_KEY` forte e fora do Git.
- [ ] `.env` não versionado.
- [ ] `ALLOWED_HOSTS` configurado.
- [ ] `CSRF_TRUSTED_ORIGINS` configurado com HTTPS.
- [ ] `SITE_URL` usando domínio real com HTTPS.
- [ ] Banco PostgreSQL com senha forte.
- [ ] Redis em rede privada ou protegido.
- [ ] SMTP testado.
- [ ] Google OAuth com callback de produção correto.
- [ ] Gemini com chave válida ou fallback aceito.
- [ ] Migrations executadas.
- [ ] `collectstatic` executado.
- [ ] Uploads protegidos por autenticação.
- [ ] Logs de Django, Celery e servidor web monitorados.
- [ ] Backups do banco planejados.

## Comandos úteis

```bash
python manage.py check
python manage.py test
```

Com Docker:

```bash
docker compose exec web python manage.py check
docker compose exec web python manage.py test
```

## Observação

Esta revisão ajuda a reduzir riscos técnicos comuns, mas não substitui auditoria
profissional de segurança, pentest ou revisão jurídica completa para um produto
financeiro em produção real.
