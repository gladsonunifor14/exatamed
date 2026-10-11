# Histórico de versões

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o projeto usa
[versionamento semântico](https://semver.org/lang/pt-BR/).

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
