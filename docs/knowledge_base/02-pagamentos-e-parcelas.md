# Pagamentos, categorias e parcelas

Versão: 1.0

## Cadastro de pagamento

Um pagamento pode conter título, descrição, valor, categoria, forma de pagamento, data de pagamento, data de agendamento e nota fiscal ou comprovante. A categoria é opcional. Quando ela não é informada, o sistema pode tentar sugerir uma categoria existente com base no título; essa sugestão pode ser revisada depois.

O valor é armazenado em reais com duas casas decimais. A data de pagamento identifica o mês em que o gasto entra nas métricas. Quando existe apenas uma data de agendamento, o sistema pode usar essa data também como data de pagamento para manter os filtros e relatórios mensais coerentes.

## Categorias pessoais e personalizadas

Sim, o usuário pode cadastrar categorias personalizadas para organizar seus gastos. Na página **Meus Pagamentos**, use a ação **Nova categoria**, informe o nome e, opcionalmente, a descrição. A categoria pessoal fica disponível nos formulários e filtros da própria conta.

Também existem categorias globais, mantidas pela administração. Categorias pessoais são visíveis somente para quem as criou: um usuário não pode consultar nem utilizar categorias de outra conta. Antes de excluir uma categoria vinculada a pagamentos, é necessário revisar esses vínculos.

## Formas de pagamento

As formas de pagamento ajudam a distinguir Pix, cartão de crédito, dinheiro e outros meios cadastrados pela administração. Pagamentos classificados como pagamento de fatura de cartão não entram como gasto comum no dashboard, evitando contar a fatura e as compras individuais duas vezes.

## Compras parceladas

Ao marcar uma compra no cartão como parcelada, o usuário informa o total de parcelas e qual parcela está cadastrando. O sistema gera as parcelas anteriores e posteriores, mantendo os dados principais e ajustando o mês da data.

As parcelas futuras ficam separadas dos pagamentos comuns. A identificação aparece como `Parcelado - X/Y`. Enquanto a parcela ainda não terminou, a indicação usa estado pendente. A última parcela só muda para finalizada após a data de pagamento.

## Pesquisa, filtros e paginação

A lista pode ser pesquisada por título e filtrada por categoria, forma de pagamento, dia, mês, ano e situação de agendamento. Os filtros permanecem ativos ao trocar de página. A ordenação e a separação de lançamentos futuros seguem as datas cadastradas.

## Arquivos aceitos

Notas e comprovantes aceitam JPG, PNG ou PDF dentro do limite configurado. Fotografias JPG podem passar por tratamento de imagem. Capturas PNG são preservadas para evitar perda de legibilidade e arquivos PDF são mantidos completos. O envio de um formato permitido não garante que o conteúdo esteja correto; o usuário deve conferir o arquivo salvo.
