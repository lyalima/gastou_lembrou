# Importação de extratos e faturas

Versão: 1.0

## Importação de extrato bancário

O usuário pode importar um extrato em um formato aceito pela tela de importação. O sistema lê os lançamentos, prepara pagamentos e aplica mecanismos de detecção de duplicidade. Como bancos podem produzir descrições e formatos diferentes, os lançamentos precisam ser conferidos.

## Importação de fatura de cartão

A importação de fatura recebe um PDF, extrai o texto disponível e tenta identificar data, descrição e valor de cada compra. Quando configurado, o Gemini pode ajudar a estruturar o texto extraído. O arquivo original e o resultado da extração ficam associados à conta que fez o envio.

Antes da confirmação, a tela de revisão permite ajustar ou ignorar itens detectados. Ao confirmar, cada compra selecionada se torna um pagamento comum com origem vinculada à fatura. A forma de pagamento usada é cartão de crédito e o estado inicial de parcelamento é não parcelado, podendo ser editado depois.

## Pagamento da fatura

O débito usado para quitar a fatura pode continuar registrado como `Pagamento de fatura`, mas esse tipo não entra nos totais de gastos do dashboard. Os gastos reais são as compras individuais da fatura. Essa regra evita dupla contabilização.

## Limitações de leitura

Faturas PDF não possuem estrutura universal. PDFs com texto selecionável costumam oferecer melhor extração; documentos digitalizados ou layouts novos podem produzir itens incompletos. O sistema não deve inventar lançamentos quando não houver evidência suficiente. O usuário deve comparar a prévia com o documento original antes de confirmar.

## Privacidade dos arquivos

Extratos e faturas podem conter dados financeiros e pessoais. Eles são vinculados ao usuário autenticado e não devem ser expostos em URL pública. Partes do texto extraído podem ser enviadas ao Gemini quando isso for necessário para a funcionalidade e estiver configurado no ambiente.
