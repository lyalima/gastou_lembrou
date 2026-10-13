# Arquitetura de IA do Spike

## Objetivo

O Spike combina um agente com tools financeiras e RAG documental para responder perguntas sobre os dados do usuário autenticado e sobre o funcionamento do Gastou Lembrou. A arquitetura prioriza isolamento entre contas, previsibilidade operacional e custo compatível com uma implantação pessoal em AWS Lightsail.

## Componentes

1. **Django e sessão autenticada:** são a autoridade de identidade e autorização.
2. **LangGraph:** organiza a recuperação de contexto e a execução do agente em etapas explícitas.
3. **LangChain Agent:** permite ao Gemini escolher tools de consulta e preparar rascunhos de novos gastos expressamente solicitados no chat. A gravação é exclusiva do botão de confirmação humana na janela de revisão, com CSRF.
4. **Gemini 2.5 Flash-Lite:** interpreta a solicitação, escolhe tools e redige a resposta.
5. **RAG híbrido:** recupera documentos Markdown por relevância lexical e, quando configurado, similaridade de embeddings.
6. **PostgreSQL/Django ORM:** armazena sessões, mensagens, documentos, chunks e embeddings.
7. **Celery/Redis:** continuam responsáveis pelas operações assíncronas, como criação de eventos no Google Agenda e emails.

## Fluxo de uma pergunta

```text
Browser autenticado
  -> view Django
  -> validação local de escopo e padrões inseguros
  -> sessão ativa do Spike
  -> grafo LangGraph
       -> recuperação documental
       -> agente LangChain/Gemini
       -> tool Django de leitura
       -> resposta fundamentada
  -> persistência da troca na sessão
  -> JSON para a interface
```

Perguntas evidentemente fora do escopo são bloqueadas antes do agente. Perguntas financeiras usam tools; dúvidas de produto usam documentos recuperados. O modelo não recebe conexão com o banco nem permissão para montar consultas.

As quatro ações rápidas completas são respondidas localmente para economizar cota. Com o Gemini configurado, perguntas livres seguem para o agente mesmo quando o classificador local identifica termos como categoria, resumo ou meta. A classificação não deve impedir a interpretação da pergunta completa. Em falhas do agente, a interface informa indisponibilidade; não substitui a resposta por um resumo genérico nem gera uma nova resposta financeira sem evidências das ferramentas.

Há uma recuperação específica para resposta final vazia com encerramento normal (`STOP`) após ferramentas bem-sucedidas: uma única etapa de redação recebe a pergunta e os resultados das ferramentas da solicitação atual. Essa etapa não executa novas consultas e pode consumir uma chamada adicional ao modelo. Não é aplicada a bloqueios de segurança, chamadas pendentes ou ausência de resultados. Se a redação também vier vazia, o fluxo informa indisponibilidade, sem repetir indefinidamente.

O histórico dá contexto à conversa, mas não é fonte de valores atuais. O agente deve consultar as ferramentas novamente. Para consultas sem chave configurada, permanecem os recursos locais limitados; isso não equivale à interpretação por IA.

## Tools disponíveis

- `buscar_pagamentos`: filtros por período, título, categoria, forma, agendamento e parcelamento.
- `consultar_categorias`: catálogo de categorias globais e pessoais acessíveis; permite resolver temas antes de aplicar o nome completo da categoria, com comparação indiferente a acentos.
- `analisar_ranking`: ordena categorias ou formas de pagamento por valor ou quantidade.
- `resumir_gastos`: total, quantidade e agrupamentos por categoria e forma de pagamento.
- `evolucao_de_gastos`: totais agrupados por mês.
- `consultar_meta`: meta e progresso de um mês.
- `consultar_ajuda_do_sistema`: recuperação da base documental.
- `consultar_opcoes_de_cadastro`: categorias globais/pessoais, formas globais e cartões do usuário.
- `preparar_gasto`: rascunho de criação solicitada, sem salvar um pagamento; a confirmação ocorre fora do agente.

Todas as tools capturam o usuário no servidor. Não existe parâmetro público de `user_id`, email ou CPF que o modelo possa alterar. Os resultados possuem limite de registros e incluem somente pagamentos contabilizáveis.

Datas inválidas ou intervalos invertidos são rejeitados, sem ampliar silenciosamente a consulta. Ordenação `recentes`, filtros, resumos, rankings, evolução e metas usam `spending_date_expression`, como dashboard e relatórios: compra no crédito, data prevista nos demais agendados e pagamento nos outros. `cadastrados_recentemente` usa a criação. O campo de resposta `data_financeira` foi preservado por compatibilidade e agora representa essa data do gasto; `vencimento_fatura` permanece separado. A ação rápida de parcelas futuras usa a data do lançamento, sem deslocá-lo pelo vencimento.

Na preparação de gastos, nomes ou IDs são resolvidos apenas no catálogo autorizado.
Nomes ignoram caixa/acentos e prefixos controlados (ex.: Cartão C6/C6); nomes ambíguos
exigem esclarecimento, sem correspondência aproximada arbitrária. Erros de catálogo
retornam opções reais. O resultado da tool prevalece sobre a redação livre para revisão
ou erro de catálogo. Uma resposta que expõe certos comandos internos recebe no máximo
uma tentativa de reparo. Isso não garante acerto de todas as conversas: testes com
Gemini real ainda são necessários, além dos testes com respostas simuladas.

## Base de conhecimento

Os arquivos em `docs/knowledge_base/` são a fonte versionada. O comando abaixo sincroniza documentos e chunks:

```bash
python manage.py sync_spike_knowledge
```

Para gerar embeddings Gemini e habilitar recuperação semântica:

```bash
python manage.py sync_spike_knowledge --with-embeddings
```

Sem API ou embeddings, a recuperação lexical permanece disponível. A falha de embeddings não impede a inicialização do sistema.

## Sessões e memória

Existe no máximo uma conversa ativa por usuário. Minimizar ou navegar entre páginas mantém a sessão e o histórico. Fechar encerra a sessão; a próxima abertura cria uma nova. Conversas encerradas continuam contando para o limite mensal, evitando contorno de cota.

Apenas as mensagens mais recentes, conforme `SPIKE_HISTORY_LIMIT`, são reenviadas ao modelo. Isso limita custo e exposição de dados.

## Segurança

- Django determina a identidade a partir de `request.user`.
- Tools de consulta possuem filtros permitidos explicitamente. `preparar_gasto` cria somente rascunhos, quando o usuário pede um cadastro; não grava pagamentos. Catálogos e cartões são limitados à conta autenticada. Propostas pertencem à conta e conversa, expiram em 15 minutos e aceitam apenas campos permitidos. O endpoint de confirmação revalida o formulário, o dono e a conversa, com transação e bloqueio de linha para impedir replays. O modelo não recebe tool de confirmação, edição ou exclusão. Parcelas e recorrências só são geradas após confirmação humana.
- Pedidos para acessar outra conta, obter segredos ou ignorar instruções são recusados.
- Conteúdo recuperado é tratado como referência, não como instrução de sistema.
- O agente não executa pagamentos bancários, transferências, exclusões ou alterações de conta. Alterações de registros de pagamento exigem revisão e confirmação explícita por botão fora do agente.
- Eventos do Google Agenda continuam exigindo seleção e confirmação na interface específica.
- Exceções do provedor são registradas no servidor e viram fallback controlado na interface.

## Escolha de infraestrutura para Lightsail

Para uso pessoal, documentos, chunks e vetores ficam no PostgreSQL já utilizado pelo projeto. A busca vetorial é calculada em memória sobre uma base pequena, evitando operar um banco vetorial separado. Essa solução é suficiente enquanto a base tiver poucos documentos.

Se a documentação crescer para milhares de chunks ou houver muitos usuários simultâneos, a evolução recomendada é habilitar `pgvector` no PostgreSQL e mover a similaridade para o banco. A interface de recuperação pode ser preservada.

MCP não é necessário dentro do monólito Django: as tools Python têm menos superfície de ataque e menor custo operacional. Um servidor MCP passa a fazer sentido se as mesmas tools precisarem ser compartilhadas com agentes externos ou outros serviços. Nesse caso, ele deve ficar em rede privada e reutilizar a mesma camada de autorização.

## Variáveis de ambiente

```env
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash-lite
GEMINI_EMBEDDING_MODEL=models/gemini-embedding-001
SPIKE_MONTHLY_MESSAGE_LIMIT=20
SPIKE_RAG_ENABLED=True
SPIKE_RAG_EMBEDDINGS_ENABLED=True
SPIKE_RAG_TOP_K=4
SPIKE_HISTORY_LIMIT=12
```

No container web de produção, `SYNC_SPIKE_KNOWLEDGE=1` sincroniza a base depois das migrações. `SPIKE_BUILD_EMBEDDINGS=1` tenta gerar embeddings apenas para conteúdo novo ou ainda não indexado.

`SPIKE_MONTHLY_MESSAGE_LIMIT` precisa ser definido; `0` desabilita a cota da aplicação,
não as cotas do provedor. A ingestão documental é RAG, não treinamento/fine-tuning.
Após editar Markdown, execute `python manage.py sync_spike_knowledge` (ou o equivalente
com `docker compose exec web`). Embeddings são opcionais e podem consumir cota externa.
