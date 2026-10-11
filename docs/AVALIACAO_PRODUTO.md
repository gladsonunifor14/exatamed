# ExataMed: de MVP a produto comercial (versão 2.0)

Avaliação feita sobre a versão 1.1, com o olhar de cada papel de um time de produto em saúde,
seguida do que a versão 2.0 entrega e do que fica para as próximas versões. O critério de
prioridade foi: **o que impede vender, implantar ou passar numa auditoria** vem primeiro.

## 1. Diagnóstico da versão 1.1

| Papel | Lacuna encontrada | Risco |
|---|---|---|
| Farmacêutico hospitalar | Dispensação errada não podia ser corrigida (sem estorno nem devolução) | Estoque e custo por paciente incorretos; tentação de editar o banco |
| Farmacêutico hospitalar | Sem bloqueio de lote (recall, interdição, quarentena) | Dispensação de lote recolhido: risco ao paciente e sanitário |
| Farmacêutico hospitalar | Sem escrituração de controlados (Portaria 344/98) | Não atende fiscalização da vigilância sanitária |
| Engenheiro backend | Quantidades e custos em ponto flutuante (`Float`) | Erros de centavos em custos e totais; inaceitável para faturamento e auditoria |
| Engenheiro backend | Baixa de estoque lia o saldo e subtraía na aplicação | Duas dispensações simultâneas podiam deixar o lote negativo |
| Engenheiro backend | Numeração da dispensação calculada por `MAX()+1` | Colisão de números sob concorrência (confirmado em teste) |
| Segurança | Sem trilha de alterações e sem proteção contra adulteração direta no banco | Registros de controlados e de acessos (LGPD) não eram auditáveis |
| Segurança | XSS armazenado: alergias do paciente inseridas com `innerHTML` | Execução de código no navegador de quem dispensa |
| Segurança | Login revelava, pelo tempo de resposta, quais usuários existem | Facilita ataques de senha direcionados |
| Segurança | Sem limite de tentativas por IP; sessões continuavam válidas após troca de senha ou desligamento | Força bruta distribuída; ex-funcionário com sessão aberta |
| Segurança / SRE | Bootstrap via CDN e JavaScript inline | Quebra em rede hospitalar sem internet; impede uma CSP efetiva |
| UX | Todos os pacientes carregados num `<select>` | Tela inutilizável com milhares de pacientes |
| SRE | Sem logs estruturados, sem correlação de requisições, health check sem tratar falha do banco | Incidentes difíceis de diagnosticar |
| SRE / QA | Sem CI, sem testes em PostgreSQL, sem imagem de contêiner | Regressões chegam à produção; implantação on-premises difícil |
| PM | Sem runbook, versão de produto ou changelog | Dependência de quem construiu para operar |

## 2. O que a versão 2.0 entrega

### Integridade dos dados (backend)
- **Decimal exato** (`NUMERIC(14,4)`) para quantidades e custos, com conversão automática dos
  bancos existentes (testado: valor do estoque idêntico antes e depois).
- **Baixa atômica**: `UPDATE ... WHERE saldo >= quantidade` mais `SELECT ... FOR UPDATE` nos lotes.
- **Restrições no banco**: saldo nunca negativo, quantidades e custos válidos.
- **Numeração da dispensação por contador travado** (sem colisão).
- Teste de **concorrência real no PostgreSQL**: 10 dispensações simultâneas disputando 5
  unidades resultam em exatamente 5 sucessos, saldo zero e numeração contínua.

### Auditoria (segurança, compliance)
- **Cadeia selada com HMAC-SHA256** sobre movimentações, acessos a dados pessoais e a própria
  trilha: alteração, remoção ou inserção direta no banco é detectada e localizada.
- **Trilha de auditoria** de todos os cadastros (antes e depois), sem gravar valores de dados
  pessoais, compatível com a anonimização da LGPD.
- **Conciliação** do saldo de cada lote com as suas movimentações.
- Tela de integridade para o administrador e comando `verificar-integridade` para agendamento.

### Fluxos farmacêuticos
- **Devolução e estorno** de dispensação, total ou parcial, com motivo, ao mesmo lote e custo,
  sem apagar a dispensação original. Os relatórios passam a mostrar o **consumo líquido**.
- **Bloqueio de lote** em todos os locais (recall, interdição, quarentena), com motivo e trilha.
- **Escrituração de controlados**: saldo anterior, entradas, saídas com paciente, prescritor
  (CRM) e responsável, saldo corrente e final, restrita ao farmacêutico e com a exportação registrada.

### Segurança
- Bootstrap, Popper e Bootstrap Icons **servidos localmente**; **CSP estrita**
  (`script-src 'self'`), sem JavaScript inline.
- XSS corrigido (`textContent`) e coberto por teste no navegador.
- Sessões invalidadas ao trocar a senha, mudar o perfil, desativar ou anonimizar o usuário.
- Limite de falhas de login por IP; tempo de resposta constante para login inexistente.
- `Cache-Control: no-store` nas páginas autenticadas, cookie `__Host-` e `Permissions-Policy`.

### UX
- **Busca incremental de pacientes** (nome, CPF ou Cartão SUS) com alergias visíveis antes da
  escolha; os pacientes deixaram de ser carregados em todas as telas de estoque.

### Operação (SRE, QA)
- **Logs em JSON** com `X-Request-ID`, sem query string (pode conter dados pessoais).
- `/saude` com latência do banco e resposta 503 quando o banco cai.
- **CI no GitHub Actions**: lint (ruff), testes no SQLite e no PostgreSQL, `pip-audit` e build
  da imagem Docker.
- **Dockerfile** (usuário sem privilégios, health check) e **docker-compose** com PostgreSQL
  para instalação no próprio hospital; dependências travadas em `requirements.lock`.
- **[Runbook de operação](OPERACAO.md)**: configuração, monitoramento, backup e restauração,
  resposta a falhas de integridade e incidentes comuns.

### Números da entrega
- 120 testes automatizados (61 na 1.1), executados no SQLite e no PostgreSQL 16.
- Atualização de um banco PostgreSQL da 1.1 validada de ponta a ponta.

## 3. Roadmap

### Próxima versão (P1)
| Item | Por quê | Responsável |
|---|---|---|
| Migrações versionadas (Alembic) no lugar das atualizações automáticas na inicialização | Rollback controlado e revisão de esquema em ambientes regulados | Backend |
| Dupla checagem para medicamentos de alta vigilância (MAV/ISMP) | Exigência de segurança do paciente em acreditação (ONA, JCI) | Farmacêutico + UX |
| Leitura de código de barras / DataMatrix (GS1) na entrada e na dispensação | Rastreabilidade por lote e menos erro de digitação | Frontend + Farmacêutico |
| Prescrição eletrônica e integração com o prontuário (HL7 FHIR `MedicationRequest`/`MedicationDispense`) | Elimina digitação dupla; base para farmácia clínica | Backend |
| Exportação para o SNGPC (ANVISA) | Obrigatória para controlados em farmácias com escrituração eletrônica | Backend + Farmacêutico |
| Autenticação de dois fatores (TOTP) e SSO (OIDC/SAML) com o diretório do hospital | Exigência comum de segurança da informação em hospitais | Segurança |
| Relatório do titular (direito de acesso, art. 18 da LGPD) | Atendimento ao titular sem consulta manual ao banco | Backend |

### Depois (P2)
- Multiempresa e multiunidade (vários hospitais na mesma instalação), com isolamento de dados.
- Kits e cirurgias (dispensação por procedimento), fracionamento e unitarização.
- Painéis gerenciais com curva ABC, giro e perdas por vencimento; previsão de demanda.
- Criptografia de campos sensíveis em repouso e gestão de chaves em KMS.
- Métricas Prometheus/OpenTelemetry e testes ponta a ponta automatizados no CI (Playwright).
- Validação de sistema computadorizado (documentação IQ/OQ/PQ) para clientes que exigem.

## 4. Decisões e limitações conhecidas
- **SQLite** permanece só para uso local e testes: não suporta `SELECT ... FOR UPDATE` nem a
  criação de restrições em tabelas existentes. Produção exige PostgreSQL.
- O **prazo de guarda de controlados** (2 anos) e o **limite de falhas por IP** (30 em 15 min)
  são configuráveis no código e devem ser validados com o responsável técnico e a TI do cliente.
- A cadeia de auditoria depende da `EXATAMED_CHAVE_AUDITORIA`: perder ou trocar a chave impede
  verificar o histórico (ver [runbook](OPERACAO.md)).
- As atualizações de esquema na inicialização são idempotentes e foram testadas a partir da
  1.1, mas não oferecem rollback automático: faça backup antes de atualizar (Alembic no P1).
