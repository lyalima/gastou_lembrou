# Importação de extratos e faturas

Versão: 1.1

## Importação de extrato bancário

O usuário pode importar CSV, OFX ou PDF com texto extraível. Após analisar, deve revisar e selecionar os itens antes de confirmar. A prévia expira em 30 minutos e aceita até 500 saídas; se expirar, envie novamente. A confirmação cria apenas os itens selecionados, com forma Pix, e informa criados/ignorados. A detecção de duplicidade usa dados da importação e do usuário.

Nos layouts bancários com histórico reconhecido, o parser seleciona `Pix enviado`, ignorando saques e pagamentos de fatura. Isso não é uma classificação universal: CSV/OFX genéricos e outros layouts devem ser conferidos na prévia, pois podem apresentar outras saídas. Não confirme uma saída que não deva ser registrada como Pix.

## Importação de fatura de cartão

A importação de fatura recebe um PDF, extrai o texto disponível e tenta identificar data, descrição e valor de cada compra. Quando configurado, o Gemini pode ajudar a estruturar o texto extraído. O arquivo original e o resultado da extração ficam associados à conta que fez o envio.

Antes da confirmação, a tela mostra a quantidade de lançamentos e permite ajustar ou ignorar itens. Ao confirmar, cada compra selecionada se torna um pagamento com origem vinculada à fatura e forma cartão de crédito. Indicadores reconhecidos como `2/3` preenchem o parcelamento; essa importação não gera automaticamente todas as demais parcelas. Confira cartão, data da compra e vencimento informado da fatura. Mesmo uma compra antiga aparece nas métricas pela data de compra registrada, mas permanece na fatura correspondente ao vencimento.

## Pagamento da fatura

A confirmação da fatura gera também um registro do tipo `Pagamento de fatura`, categoria Fatura de cartão de crédito, título baseado no cartão/banco, sem forma de pagamento, com total da fatura e vencimento. Não é uma confirmação de quitação nem entra nos totais de gastos: as compras individuais já são contabilizadas. Confira o total detectado antes de confirmar a importação.

## Limitações de leitura

Faturas PDF não possuem estrutura universal. PDFs com texto selecionável costumam oferecer melhor extração; documentos digitalizados ou layouts novos podem produzir itens incompletos. O sistema não deve inventar lançamentos quando não houver evidência suficiente. O usuário deve comparar a prévia com o documento original antes de confirmar.

## Privacidade dos arquivos

Extratos e faturas podem conter dados financeiros e pessoais. Eles são vinculados ao usuário autenticado e não devem ser expostos em URL pública. Partes do texto extraído podem ser enviadas ao Gemini quando isso for necessário para a funcionalidade e estiver configurado no ambiente.
