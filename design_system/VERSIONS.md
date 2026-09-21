# Versoes do design

Este diretorio versiona apenas a especificacao visual produzida para o Gastou
Lembrou. Capturas brutas e bundles dos sites usados como referencia ficam em
`design_system/refs/`, que e uma pasta local ignorada pelo Git. A aplicacao nao
depende desses arquivos para funcionar.

## V2 - Interface anterior

- Classe raiz: `ds-ui-v2`.
- Implementacao: bloco `DESIGN SYSTEM V2 - REVERSIBLE TEST LAYER` em
  `static/css/app.css`.
- Home correspondente: camada `home-design-test`, preservada no CSS.
- Status: preservada como base de retorno.

## V3 - Aura financeiro

- Classe raiz: `ds-aura-v3`, usada junto de `ds-ui-v2`.
- Especificacao visual: `design_system/design_system.html`.
- Implementacao: bloco `DESIGN SYSTEM V3 - AURA FINANCIAL` em
  `static/css/app.css`.
- Home correspondente: `home-adcoach-test`.
- Status: versao anterior preservada. Na home, ainda funciona como camada base
  sob o V5; nao e mais a identidade visual principal.

## V4 - Growth Ledger (descartada)

- Classe da home: `home-growth-v4`, aplicada junto de `home-adcoach-test`.
- Especificacao: `design_system/design_system.html`.
- Implementacao: bloco `HOME V4 - GROWTH LEDGER` em `static/css/app.css`.
- Escopo: somente a home publica.
- Status: descartada; a classe e os estilos nao estao ativos.

## V5 - Quiet Fintech

- Classes ativas:
  - `home-fintech-v5`, aplicada junto de `home-adcoach-test` na home publica;
  - `ds-fintech-v5`, aplicada junto de `ds-ui-v2` nas paginas autenticadas, de
    autenticacao, legais e demais paginas publicas.
- Especificacao: `design_system/design_system.html`.
- Origem visual: especificacao derivada de referencias externas, sem dependencia
  dos arquivos brutos usados durante a analise.
- Paleta: base em preto, branco e cinzas neutros, com cores semanticas para
  graficos, sucesso, alerta, informacao e erro.
- Implementacao: blocos `HOME V5 - QUIET FINTECH` e
  `DESIGN SYSTEM V5 - QUIET FINTECH / APPLICATION` em `static/css/app.css`.
- Escopo: home, area autenticada, autenticacao, paginas legais, modais, dashboard
  e componentes compartilhados.
- Status: versao ativa atual.

## Reversao

Para retornar as paginas internas, de autenticacao e legais a V3, altere o ramo
que aplica `ds-fintech-v5` em `templates/base.html` para `ds-aura-v3`.

Para retornar a home a V3, remova somente `home-fintech-v5` de
`templates/core/home.html`. Para voltar a V2, substitua
`home-adcoach-test home-fintech-v5` por `home-design-test` e deixe apenas
`ds-ui-v2` no elemento `body` de `templates/base.html`.

Essas camadas alteram somente apresentacao. Templates Django, atributos HTMX,
URLs, formularios e regras de negocio permanecem compartilhados entre as
versoes.
