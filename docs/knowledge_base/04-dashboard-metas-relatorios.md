# Dashboard, metas, relatórios e insights

Versão: 1.0

## Métricas do dashboard

O dashboard apresenta total registrado, quantidade de pagamentos, pagamentos agendados, gastos por categoria, gastos por forma de pagamento, evolução no tempo e pagamentos recentes. A opção `Ver tudo` considera todo o histórico contabilizável. Ao escolher um mês, os cards e gráficos usam apenas o período selecionado.

Pagamentos do tipo `Pagamento de fatura` são excluídos das métricas. Compras individuais do cartão continuam contabilizadas no mês correspondente à data de cada parcela.

## Meta mensal de gastos

Cada meta pertence a um mês específico. O progresso compara o valor da meta com os gastos contabilizáveis daquele mês. A barra usa estados visuais progressivos para facilitar a leitura.

O usuário pode escolher alertas em 50%, 75% e 90%, inclusive mais de um limite. Cada aviso é enviado no máximo uma vez para a combinação de meta, percentual e período. A entrega depende da configuração de email e da execução do Celery.

## Relatório PDF

O relatório é mensal e reúne os principais números do dashboard, tabelas por categoria e forma de pagamento, evolução e pagamentos registrados. Parcelas aparecem com o indicador `X/Y`. Uma data agendada pode ser identificada ao lado da data na listagem.

O usuário escolhe o mês antes de gerar o arquivo. O envio automático mensal, quando ativo, ocorre no primeiro dia do mês e se refere ao mês anterior.

## Insights com inteligência artificial

Os insights analisam métricas do usuário para destacar variações e padrões. Eles são informativos, podem conter imprecisões e não substituem análise profissional. Quando a API do Gemini não está configurada ou falha, o sistema pode apresentar um fallback local ou uma mensagem de indisponibilidade controlada.
