# Cartoes, recorrencias e propostas do Spike

## Ativacao no Docker

As migrations sao aditivas: registros existentes ficam sem cartao/recorrencia.

```sh
docker compose exec web python manage.py migrate
docker compose restart web celery_worker celery_beat
docker compose exec web python manage.py sync_spike_knowledge
```

Confirme o nome do servico Beat no seu arquivo Compose. A sincronizacao documental nao faz treinamento/fine-tuning: atualiza o corpus RAG. Novas sessoes duram 24 horas absolutas; sessoes antigas sem prazo sao encerradas na primeira requisicao. Reiniciar os processos nao estende sessoes.

## Cartoes

Meus cartoes e Faturas sao paginas proprias na sidebar, em `/pagamentos/cartoes/`
e `/pagamentos/faturas/`. O dashboard oferece atalhos para o cartao/mes da fatura;
a pagina de pagamentos nao tem mais o antigo botao Meus cartoes.

Cartoes pertencem ao usuario, sem dados bancarios sensiveis. O formulario permite vincular compras e importacoes PDF. `Payment.statement_due_date` registra o vencimento calculado no cadastro/edicao. O dia de fechamento pertence ao ciclo seguinte; datas inexistentes sao limitadas ao fim do mes. Quando o fechamento cair em domingo, o corte sera antecipado para sabado, inclusive se esse sabado pertencer ao mes anterior. Compras no sabado de fechamento ja pertencem ao ciclo seguinte. O dia cadastrado e o calendario de vencimentos permanecem inalterados; vencimentos explicitos de faturas importadas continuam prevalecendo. Alterar o cadastro do cartao nao recalcula o historico automaticamente.

O dashboard mostra faturas do mes selecionado e seguinte; Ver tudo usa o mes atual. Indicadores, metas e avisos, graficos, relatorios mensais e filtros de dia/mes/ano da listagem consideram credito pela data da compra. Para os demais meios, usam data prevista quando agendados ou data de pagamento. Apenas a apuracao de Cartoes e faturas continua agrupada pelo vencimento da fatura. Os detalhes e relatorios preservam a exibicao do vencimento ao lado da data da compra. Valores de pagamentos de fatura nao sao adicionados novamente aos totais e nao indicam quitacao.

## Recorrencias

`PaymentRecurrence` guarda original, ancora, intervalo (1/3/6/12 meses), cursor e estado ativo. `generate_recurring_payments` roda a cada hora via Beat. Bloqueio transacional da serie e unicidade `(recurrence, recurrence_number)` impedem duplicacao. O cursor avanca na mesma transacao. A data sempre deriva da ancora, evitando desvio de 31 para 28 nos meses seguintes.

Ao criar, gera a proxima ocorrencia; em cada execucao recupera ocorrencias faltantes ate ter uma futura. Um lote recupera no maximo 120 ocorrencias, continuando no proximo ciclo se necessario. Emails sao enfileirados apos commit para ocorrencias nao passadas. O mecanismo de lembretes existente continua responsavel pelos avisos de vencimento.

Editar o original afeta apenas ocorrencias ainda nao geradas. Desativar/excluir o original para geracoes futuras, mas preserva os pagamentos existentes. Trocar ancora/frequencia exige uma nova serie. Recorrencia e parcelamento sao mutuamente exclusivos.

## Propostas do Spike

O chat oferece ferramentas de consulta e `preparar_gasto`, que prepara apenas novos gastos solicitados expressamente. Nao existe tool de confirmacao, edicao ou exclusao exposta ao modelo. `AssistantPaymentAction` armazena o rascunho permitido, usuario, conversa e prazo. A janela de revisao usa dialog nativo com confirmacao/cancelamento. Confirmacao exige POST, CSRF, sessao do dono e revalidacao de `PaymentForm`; propostas expiradas ou conversas encerradas nao salvam. Confirmacao repetida nao duplica. Parcelas e recorrencias solicitadas usam os mesmos servicos do formulario, dentro da transacao. A estrutura anterior de propostas permanece para preservar o historico, mas o checkbox de autorizacao e a tool antiga foram removidos.

## Correcao manual de categorias

Salvar uma categoria escolhida no formulario aplica a mesma categoria aos pagamentos do mesmo usuario com titulo identico (ignorando maiusculas e espacos nas pontas). Inclui registros sem categoria ou com outra categoria. Edicoes sem alterar categoria e categorizacao automatica nao propagam mudancas. Atualizacoes em lote invalidam o cache e atualizam o timestamp, preservando datas e outras propriedades do pagamento.

## Validacao

As consultas financeiras do Spike compartilham `spending_date_expression` com
dashboard e relatorios. A resposta de parcelas futuras do chat tambem usa a data
do lancamento; a separacao visual da lista de pagamentos continua considerando
o vencimento para parcelas com cartao, conforme sua regra propria.

```sh
docker compose exec web python manage.py test payments.test_workflows
docker compose exec web python manage.py test
```

Nao e necessario modificar credenciais ou adicionar dependencias. Gemini continua sendo necessario para interpretar pedidos livres; recorrencias dependem de worker e Beat ativos. A categorizacao por historico funciona sem chamada de IA, com fallback existente para Gemini.
