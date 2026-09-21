# Agendamentos, emails e Google Agenda

Versão: 1.0

## Pagamento agendado

Um pagamento com data de agendamento pode gerar três comunicações: confirmação imediata do agendamento, lembrete um dia antes e lembrete no dia do vencimento. O sistema mantém registros de envio para reduzir duplicidades. A confirmação e os lembretes são processados em segundo plano pelo Celery.

Na lista, um agendamento cuja data já passou aparece como finalizado. Essa indicação visual não confirma que o pagamento foi efetivamente quitado; ela informa apenas que a data cadastrada passou.

## Dependências dos lembretes

Redis, Celery worker, Celery beat e o serviço de email precisam estar ativos e corretamente configurados. O beat identifica tarefas periódicas e o worker executa os envios. Uma indisponibilidade externa pode atrasar ou impedir a mensagem, portanto o email não deve ser a única forma de acompanhar um vencimento.

## Conexão com Google Agenda

A integração é opcional e exige autorização da conta Google. O Gastou Lembrou solicita o escopo necessário para criar eventos de calendário. A conexão do Google Agenda é separada do login social.

Depois da conexão, o usuário escolhe quais pagamentos realmente agendados deseja enviar. Parcelas futuras sem data de agendamento não fazem parte dessa lista. Antes da criação dos eventos, a seleção é mostrada para confirmação.

## Desconexão e revogação

O botão `Desconectar` desativa a conexão no Gastou Lembrou. Para revogar completamente uma autorização já concedida, o usuário também pode remover o acesso do aplicativo nas configurações de segurança da Conta Google.

## Segurança da integração

Tokens de acesso e atualização são armazenados de forma criptografada. A criação de eventos sempre parte de pagamentos pertencentes ao usuário autenticado e não aceita um identificador de usuário fornecido pela conversa ou pelo navegador como fonte de autorização.
