# Histórico de versões

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o projeto usa
[versionamento semântico](https://semver.org/lang/pt-BR/).

## [2.5.0] — 2026-10-19

### Alterado
- Trilha de auditoria normalizada: as alterações de cada registro saem da coluna de texto JSON
  `registros_auditoria.alteracoes` para a nova tabela `alteracoes_auditoria` (uma linha por campo,
  com valor anterior e novo). A coluna antiga é removida.
- O selo HMAC do registro de auditoria passa a ser calculado sobre o JSON canônico montado a
  partir das linhas da tabela nova, idêntico ao texto antigo: os selos do histórico continuam
  válidos sem nova selagem, e alterar uma linha de alteração direto no banco é detectado.

### Migração
- Automática na inicialização e pelo comando `flask --app exatamed migrar-auditoria`: transfere o
  histórico conferindo registro a registro e só remove a coluna se todos forem transferidos sem
  perda (caso contrário mantém a coluna e aponta os ids).
- `importar-sql` aceita arquivos exportados até a 2.4 e migra as alterações ao carregar.

## [2.4.0] — 2026-10-17

### Adicionado
- Data e hora da dispensação, para lançamento retroativo. Data futura é recusada (no campo e no
  servidor). A baixa PEPS usa só os lotes que já estavam em estoque e dentro da validade na data
  informada; a numeração segue o ano dessa data.
- O comprovante indica o lançamento retroativo e quando o registro foi feito.
- Comandos `exportar-sql` e `importar-sql`: arquivo `.sql` com os `INSERT` de todas as tabelas,
  na ordem das chaves estrangeiras, com os mesmos ids e os selos da auditoria preservados
  (PostgreSQL ou SQLite; opção `--anonimizar`). Pasta `migracoes/` com os dados de demonstração.

## [2.3.0] — 2026-10-15

### Adicionado
- Menu **Dashboard** com painéis de gestão: evolução do custo por dia/mês/ano (filtros de médico
  e localização), curva ABC (filtro de medicamentos e materiais), itens a vencer em 30/60/90 dias,
  taxa de ruptura, nível do estoque de segurança, giro do estoque e taxas de devolução e de
  avarias/perdas.
- Gráficos em SVG gerados no servidor, com dica ao passar o mouse ou focar pelo teclado e tabela
  de valores de cada gráfico.
- Sugestões padronizadas de motivo na saída avulsa (avaria, quebra, vencimento, perda...).

## [2.2.0] — 2026-10-15

### Adicionado
- Classificação automática do controle especial no cadastro de medicamentos, pelo princípio ativo
  (ou pelo nome, na falta dele), com tabela de referência das listas da Portaria 344/98 e dos
  antimicrobianos da RDC 471/2021. Associações recebem a lista mais restritiva; a escolha manual
  diferente da tabela é mantida com aviso.
- Lista "Agonista GLP-1 com retenção de receita (RDC 471/2021, IN 360/2025)".
- Cadastro do produto na própria conferência da NF-e (farmacêutico), com os dados do XML já
  preenchidos; o produto fica escolhido no item sem perder o que foi conferido.
- Exclusão de notas fiscais descartadas em **Estoque → Notas fiscais (NF-e)** (farmacêutico).
- Estorno de movimentações em **Estoque → Movimentações**: lançamento inverso no mesmo lote e
  custo, autorizado pela senha de um farmacêutico ou administrador (registrado na cadeia de
  auditoria). Transferências são estornadas nas duas partes; dispensações viram devolução.
- Filtro por classificação (A1, B1, C1, antimicrobiano...) na escrituração de controlados.

### Alterado
- A chegada de uma transferência passa a ficar ligada à saída da origem.
- Notas importadas não podem ser excluídas (documento de origem dos lotes); notas em conferência
  precisam ser descartadas antes.

### Corrigido
- Erro de JavaScript ao abrir uma nota já importada.

## [2.1.0] — 2026-10-14

### Adicionado
- Importação do XML da NF-e (modelo 55, leiautes 4.00 e 3.10) em **Estoque → Entrada**, com
  conferência antes de confirmar: produto, fator de conversão de unidade, lotes e validades.
- Custo de aquisição por unidade com frete, seguro, outras despesas, IPI e ICMS-ST, menos desconto.
- Sugestão do produto pelo código do fornecedor (memorizado a cada importação), GTIN ou registro ANVISA.
- Lista de notas fiscais importadas, pendentes e descartadas; lotes ligados à nota de origem e
  XML original guardado.
- Campos **código de barras (GTIN)** e **registro ANVISA** no cadastro de produtos.

### Segurança
- XML lido com `defusedxml` (DTD e entidades recusadas), limite de 5 MB, apenas notas com
  protocolo de autorização da SEFAZ e bloqueio de importação em dobro da mesma chave de acesso.

## [2.0.0] — 2026-10-11

Evolução de MVP para produto auditável, seguro e operável. Detalhes e roadmap em
[docs/AVALIACAO_PRODUTO.md](docs/AVALIACAO_PRODUTO.md).

### Adicionado
- Devolução e estorno de dispensação (total ou parcial), ao mesmo lote e custo, com motivo.
- Bloqueio e desbloqueio de lote em todos os locais (recall, interdição, quarentena).
- Relatório de escrituração de medicamentos controlados (Portaria SVS/MS nº 344/1998).
- Cadeia de auditoria selada (HMAC-SHA256) para movimentações, acessos e trilha de auditoria.
- Trilha de auditoria de cadastros (antes e depois) e tela de integridade dos registros.
- Comando `flask --app exatamed verificar-integridade` (código de saída 1 em falha).
- Busca incremental de pacientes na dispensação.
- Adequação à LGPD: mascaramento, registro de acessos, relatórios sem identificação e
  anonimização de cadastros com prazo de guarda de controlados.
- Logs estruturados em JSON com `X-Request-ID`; `/saude` com latência do banco.
- CI (GitHub Actions), Dockerfile, docker-compose, `requirements.lock` e runbook de operação.

### Alterado
- Quantidades e custos passam a ser decimais exatos (`NUMERIC(14,4)`); bancos existentes são
  convertidos automaticamente.
- Relatórios de consumo mostram valores líquidos (dispensado menos devolvido).
- Número da dispensação vem de um contador travado no banco.
- Bootstrap 5.3.8, Popper e Bootstrap Icons servidos localmente (sem CDN).
- Sessões de versões anteriores são encerradas na atualização (novo formato de sessão).

### Segurança
- Baixa de estoque atômica e restrições no banco impedem saldo negativo sob concorrência.
- Política de segurança de conteúdo estrita, sem JavaScript inline.
- Corrigido XSS armazenado no campo de alergias da tela de dispensação.
- Tempo de resposta constante no login (não revela usuários existentes) e limite de falhas por IP.
- Sessões encerradas ao trocar a senha, mudar o perfil, desativar ou anonimizar o usuário.
- `Cache-Control: no-store` nas páginas autenticadas; cookie `__Host-` em produção.

### Atualização a partir da 1.x
1. Faça backup do banco.
2. Defina `EXATAMED_CHAVE_AUDITORIA` (guarde-a em cofre; nunca a altere).
3. Publique a 2.0: o esquema é atualizado e o histórico é selado na primeira inicialização.
4. Rode `flask --app exatamed verificar-integridade`.

## [1.1.0] — 2026-10-10
- Login com perfis, onboarding (guia, página Ajuda, primeiros passos), CEP, numeração n/ano das
  dispensações e publicação no Render.

## [1.0.0] — 2026-10-10
- Primeira versão: cadastros, estoque com custo PEPS, dispensação e seis relatórios.
