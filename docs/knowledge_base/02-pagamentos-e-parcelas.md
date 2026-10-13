# Pagamentos, categorias e parcelas

Versão: 1.3

## Cadastro de pagamento

Um pagamento pode conter título, descrição, valor, categoria, forma de pagamento, data de pagamento, data de agendamento e nota fiscal ou comprovante. A categoria é opcional. Quando ela não é informada, o sistema pode tentar sugerir uma categoria existente com base no título; essa sugestão pode ser revisada depois.

O valor é armazenado em reais com duas casas decimais. Para Pix, dinheiro e outras formas, a data prevista de agendamento ou a data de pagamento determina o mês dos gastos. Para crédito, a data da compra determina o mês no dashboard, nas metas, nos relatórios e nos filtros da lista. O vencimento continua determinando a fatura correspondente, sem mover o gasto para outro mês nessas métricas. Quando existe apenas uma data de agendamento, o sistema pode usá-la também como data de pagamento.

## Categorias pessoais e personalizadas

Sim, o usuário pode cadastrar categorias personalizadas para organizar seus gastos. Na página **Meus Pagamentos**, use a ação **Nova categoria**, informe o nome e, opcionalmente, a descrição. A categoria pessoal fica disponível nos formulários e filtros da própria conta.

Também existem categorias globais, mantidas pela administração. Categorias pessoais são visíveis somente para quem as criou: um usuário não pode consultar nem utilizar categorias de outra conta. Antes de excluir uma categoria vinculada a pagamentos, é necessário revisar esses vínculos.

## Formas de pagamento

As formas de pagamento ajudam a distinguir Pix, cartão de crédito, dinheiro e outros meios cadastrados pela administração. Pagamentos classificados como pagamento de fatura de cartão não entram como gasto comum no dashboard, evitando contar a fatura e as compras individuais duas vezes.

## Compras parceladas

Ao marcar uma compra no cartão como parcelada, o usuário informa o total de parcelas e qual parcela está cadastrando. O sistema gera as parcelas anteriores e posteriores, mantendo os dados principais e ajustando o mês da data.

As parcelas futuras ficam separadas dos pagamentos comuns. Com cartão vinculado, a separação considera o vencimento da fatura; sem cartão vinculado, considera a data cadastrada da parcela. A identificação aparece como `Parcelado - X/Y`. A última parcela só muda para o estado finalizado no dia seguinte ao vencimento da sua fatura, ou, sem cartão vinculado, no dia seguinte à data da parcela. Essa indicação temporal não comprova que a fatura foi paga.

## Cartões e faturas

Em **Meus cartões**, na sidebar, cadastre nome, descrição, dia do fechamento e dia do vencimento (de 1 a 31). Não são solicitados número, CVV ou senha do cartão. Ao escolher a forma Cartão de crédito em um pagamento, você pode vinculá-lo a um cartão cadastrado. A importação de fatura PDF também oferece essa escolha. A página **Faturas** permite escolher cartão e mês; o dashboard tem atalhos para essas consultas.

Compras feitas antes do fechamento pertencem à fatura corrente; no dia do fechamento ou depois, à próxima. Em meses sem o dia escolhido, utiliza-se o último dia do mês. Se o fechamento cair em domingo, o corte é antecipado para sábado; compras nesse sábado já entram no ciclo seguinte. Exemplo: fechamento cadastrado dia 04 em outubro de 2026 considera 03/10/2026. O vencimento e o dia cadastrado não são antecipados. A fatura importada preserva seu vencimento explícito.

A área **Cartões e faturas** do dashboard mostra os valores por vencimento no mês selecionado e no seguinte. Em **Ver tudo**, essa área considera o mês atual e o seguinte. Dashboard, metas, relatórios e análises mensais consideram a data da compra no crédito e pagamento/agendamento nos demais lançamentos. Cada parcela usa sua própria data cadastrada; o pagamento da fatura não é somado novamente como gasto. Os valores de faturas são estimativas baseadas apenas nos lançamentos cadastrados, não um saldo bancário ou comprovante de quitação. Ao editar fechamento/vencimento, as datas de faturas já calculadas são preservadas; novas compras ou compras editadas usam os dados atuais.

## Recorrências

No formulário, marque **Repetir este pagamento** e selecione Mensal, Trimestral, Semestral ou Anual. Informe a data inicial (o agendamento tem prioridade). Compras parceladas não podem também ser recorrentes.

O sistema cria a próxima ocorrência como agendada e mantém uma ocorrência futura por série. O Celery Beat verifica a sequência a cada hora. A referência é sempre o dia original: uma série iniciada dia 31 passa pelo último dia de fevereiro e volta ao dia 31 em março. Uma execução repetida não duplica ocorrências. Ao recuperar um período de indisponibilidade, pode haver geração de ocorrências passadas, sem email imediato para datas já passadas.

Edite o pagamento original para alterar título, valor ou outros dados usados nas ocorrências que ainda não foram geradas. As já criadas são independentes. Desmarcar a recorrência ou excluir o original interrompe novas gerações, sem excluir lançamentos já existentes. Para mudar data-base ou frequência, desative a série anterior e crie uma nova. Não marque uma ocorrência gerada como uma nova série; edite o original.

## Categorização pelo histórico

Sem categoria informada, o sistema tenta reutilizar a categoria do título equivalente mais recente da mesma conta, normalizando acentos e pontuação. Correspondências muito próximas são aceitas apenas sem conflito entre categorias. Sem correspondência segura, continuam as regras locais e a categorização por Gemini. Ao escolher ou alterar manualmente a categoria no formulário, essa escolha é aplicada também aos outros pagamentos da mesma conta com título idêntico (ignorando maiúsculas e espaços nas pontas), inclusive os sem categoria ou com outra categoria. Editar apenas outro campo não propaga categorias.

## Pesquisa, filtros e paginação

A lista pode ser pesquisada por título e filtrada por categoria, forma de pagamento, dia, mês, ano e situação de agendamento. Filtros, ordenação e evolução no dashboard/relatório usam a data da compra no crédito, a data prevista nos demais agendados e a data de pagamento nas demais formas. O relatório separa cartão, agendados e demais formas, mostrando as datas e os meios correspondentes, inclusive o vencimento da fatura. Os filtros permanecem ativos ao trocar de página.

## Arquivos aceitos

Notas e comprovantes aceitam JPG, PNG ou PDF dentro do limite configurado. Fotografias JPG podem passar por tratamento de imagem. Capturas PNG são preservadas para evitar perda de legibilidade e arquivos PDF são mantidos completos. O envio de um formato permitido não garante que o conteúdo esteja correto; o usuário deve conferir o arquivo salvo.
