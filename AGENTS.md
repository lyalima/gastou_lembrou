# AGENTS.md

## Objetivo atual

Melhorar gradualmente o frontend e a experiencia de uso do Gastou Lembrou,
preservando todas as funcionalidades, regras de negocio e integracoes existentes.

## Prioridade das instrucoes

1. Este arquivo define os limites das alteracoes no projeto.
2. A skill `web-design-guidelines` deve ser usada como ferramenta de auditoria.
3. Uma recomendacao da skill nao autoriza automaticamente uma alteracao.
4. Em caso de conflito, preservar o comportamento atual e seguir este arquivo.

## Escopo permitido

- Templates Django em `templates/`.
- Estilos existentes em `static/css/app.css`.
- JavaScript de interface em `static/js/app.js`.
- Componentes visuais, estados de UI, responsividade e acessibilidade.
- Textos curtos de interface, quando a mudanca melhorar clareza ou consistencia.

## Restricoes

- Nao alterar backend sem pedido explicito.
- Nao alterar models, migrations, forms, views, URLs, tasks, signals ou settings
  para resolver apenas uma questao visual.
- Nao alterar contratos, nomes de campos, parametros de URL ou regras de negocio.
- Nao alterar o comportamento de autenticacao, emails, Celery, Redis, Gemini,
  pagamentos, lembretes, relatorios ou uploads.
- Nao adicionar, remover ou atualizar bibliotecas sem autorizacao.
- Nao substituir Django Templates, HTMX ou o JavaScript existente por outro
  framework.
- Nao fazer redesign radical nem reconstruir paginas que podem ser melhoradas
  incrementalmente.
- Nao remover funcionalidades, controles ou informacoes existentes.
- Nao modificar arquivos `.env`, credenciais, banco de dados ou arquivos enviados
  pelos usuarios.

## Direcao visual

- Manter a identidade visual, a logo e a estrutura atual do produto.
- Reutilizar classes, componentes e padroes existentes antes de criar novos.
- Priorizar hierarquia visual, legibilidade, espacamento, alinhamento e contraste.
- Manter consistencia entre paginas, formularios, cards, tabelas, filtros e modais.
- Preservar os modos claro e escuro na area autenticada.
- Garantir que estados de hover, focus, active, disabled, loading, success e error
  sejam perceptiveis e consistentes.
- Usar Font Awesome para novos icones quando houver um icone adequado.
- Evitar decoracao excessiva, animacoes desnecessarias e elementos que reduzam a
  clareza de uma ferramenta de controle financeiro.
- Nao alterar a aparencia dos emails ao ajustar temas da aplicacao.

## Responsividade

- Verificar no minimo larguras de 375 px, 768 px e 1280 px.
- Evitar rolagem horizontal acidental.
- Garantir que textos, botoes, filtros, formularios, graficos e modais nao se
  sobreponham nem sejam cortados.
- Preservar o funcionamento da sidebar expandida e recolhida.
- Manter alvos de toque confortaveis em dispositivos moveis.
- Distribuir grupos grandes de filtros em mais de uma linha quando necessario.

## Acessibilidade

- Manter HTML semantico e uma hierarquia correta de titulos.
- Todo campo deve possuir label associado.
- Todo botao apenas com icone deve possuir nome acessivel e tooltip adequado.
- Preservar navegacao por teclado e foco visivel.
- Nao depender apenas de cor para transmitir estado ou erro.
- Manter contraste adequado nos modos claro e escuro.
- Imagens informativas devem possuir texto alternativo; imagens decorativas devem
  usar `alt=""`.
- Modais devem manter titulo identificavel, fechamento acessivel e foco utilizavel.

## Django e HTMX

- Preservar tags, filtros, variaveis e blocos dos Django Templates.
- Preservar atributos `hx-*`, alvos, swaps e eventos HTMX existentes.
- Nao trocar links por botoes, ou botoes por links, quando isso mudar a semantica
  ou o comportamento.
- Manter tokens CSRF e mensagens de validacao.
- Estados vazios, erros e carregamento devem continuar funcionando.
- Alteracoes em partials devem ser verificadas tanto no carregamento inicial
  quanto depois de atualizacoes via HTMX.

## Fluxo com `web-design-guidelines`

1. Auditar apenas os arquivos ou paginas solicitados.
2. Apresentar os achados por prioridade, com referencia `arquivo:linha`.
3. Separar problemas objetivos de sugestoes esteticas.
4. Nao implementar durante uma solicitacao que pedir somente auditoria.
5. Quando a implementacao for solicitada, corrigir apenas os itens aprovados.
6. Fazer alteracoes pequenas e revisar o diff antes de concluir.
7. Verificar visualmente desktop, tablet e mobile quando o ambiente permitir.

## Criterios de aceite

- Nenhuma funcionalidade existente foi perdida ou alterada.
- As paginas continuam funcionando com Django e HTMX.
- O resultado e coerente nos modos claro e escuro aplicaveis.
- A interface funciona por teclado e apresenta foco visivel.
- Nao ha sobreposicoes, cortes de texto ou rolagem horizontal acidental.
- O layout foi verificado nas larguras definidas neste arquivo.
- As mudancas permanecem limitadas ao escopo solicitado.

## Checks

Executar, conforme o alcance da alteracao:

```powershell
python manage.py check
python manage.py test
```

Quando a suite completa nao puder ser executada, rodar os testes dos apps
afetados e informar claramente quais verificacoes nao foram realizadas.
