# Ajuda e diagnóstico de problemas

Versão: 1.1

## Email não recebido

Confira spam e lixo eletrônico, confirme se o endereço da conta está correto e aguarde o processamento em segundo plano. Em desenvolvimento, verifique se Redis, Celery worker e o backend SMTP estão ativos. Falha de credencial SMTP deve ser corrigida pelo responsável pelo ambiente, sem expor a senha ao usuário.

## Insight ou Spike indisponível

Recursos com Gemini dependem de uma chave válida, modelo disponível, limite de uso e acesso à internet. O sistema deve exibir resposta controlada quando a integração falhar. Mensagens sobre dados financeiros ainda podem usar respostas locais em fluxos compatíveis.

## Importação incompleta

Revise o formato do arquivo e a prévia. PDF digitalizado, layout desconhecido, imagem pouco legível ou colunas diferentes podem reduzir a qualidade da extração. Não confirme itens com valor ou data incorretos. Cadastre manualmente o lançamento que não puder ser reconhecido com segurança.

## Métrica diferente do esperado

Verifique o mês, a data da compra no crédito e a data prevista/pagamento nas demais formas. Dashboard, relatórios e consultas financeiras do Spike seguem essas datas. A consulta de faturas usa vencimento. Pagamentos de fatura são excluídos do total para não duplicar compras individuais.

## Google Agenda não conecta

Confirme as credenciais OAuth, a URL de redirecionamento e se a conta está autorizada como testadora enquanto o aplicativo Google estiver em modo de teste. Depois de alterar código ou tarefas, reinicie os processos web e Celery em execução.

## Suporte

Quando o problema persistir, use a página de Suporte com uma descrição objetiva, passos para reproduzir e screenshot sem dados desnecessários de terceiros. O email do formulário é o mesmo da conta autenticada e não pode ser alterado naquele envio.
