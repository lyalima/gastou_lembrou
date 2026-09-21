# Conta, privacidade e segurança

Versão: 1.0

## Cadastro e autenticação

O cadastro pode ocorrer por email e senha ou por Google. Contas criadas manualmente precisam confirmar o endereço de email. A redefinição de senha por email é destinada a quem não lembra a senha atual. Senhas são armazenadas pelo mecanismo de hash do Django e não podem ser recuperadas em texto aberto.

## Alteração de email e perfil

Ao alterar o email, o novo endereço passa pelo fluxo de confirmação. O endereço antigo deixa de ser uma credencial válida quando a troca é concluída. Telefone e CPF passam por validações próprias; o CPF só pode ser cadastrado uma vez conforme a regra atual do perfil.

## Exclusão da conta

A página de perfil oferece exclusão permanente da conta. A operação remove os registros associados segundo os relacionamentos e processos técnicos do sistema. Backups e obrigações legais podem exigir ciclos próprios de retenção, conforme a Política de Privacidade.

## Isolamento de dados

Pagamentos, metas, documentos, mensagens do Spike e conexões externas são consultados a partir do usuário autenticado. O Spike não aceita email, UUID ou nome mencionado na conversa como autorização para trocar de conta. Solicitações para acessar dados de outra pessoa devem ser recusadas.

## Documentos legais

Os Termos de Uso e a Política de Privacidade disponíveis no sistema são os documentos oficiais e prevalecem sobre resumos desta base. Quando uma versão legal é atualizada, o sistema pode enviar uma comunicação e exigir novo aceite no próximo acesso.

## Boas práticas do usuário

- Use uma senha exclusiva e proteja a conta de email vinculada.
- Não compartilhe sessão, senha, códigos ou links de redefinição.
- Confira os arquivos antes do upload e remova dados de terceiros que não sejam necessários.
- Desconecte integrações que não pretende mais utilizar.
- Informe ao suporte comportamentos inesperados ou suspeita de acesso indevido.
