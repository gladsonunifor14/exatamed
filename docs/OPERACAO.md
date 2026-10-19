# Runbook de operação do ExataMed

Guia para quem implanta, opera e dá suporte ao ExataMed em produção (TI do hospital, SRE,
fornecedor). Para o uso do sistema, veja o [Guia do usuário](GUIA_DO_USUARIO.md).

## 1. Arquitetura

| Componente | Tecnologia | Observações |
|---|---|---|
| Aplicação | Python 3.12, Flask, gunicorn | Sem estado em disco: pode ter várias instâncias. |
| Banco de dados | PostgreSQL 16 (produção) | SQLite apenas para uso local e testes. |
| Front-end | HTML renderizado no servidor; Bootstrap servido localmente | Funciona sem internet; só a busca de CEP (ViaCEP) usa a internet, no navegador. |
| Integrações | ViaCEP (opcional) | Se indisponível, o endereço é digitado à mão. |

Formas de implantação suportadas: **Render** (`render.yaml`), **Docker/Docker Compose**
(`Dockerfile`, `docker-compose.yml`) ou qualquer servidor com Python e PostgreSQL.

## 2. Configuração (variáveis de ambiente)

| Variável | Obrigatória | Descrição |
|---|---|---|
| `EXATAMED_ENV` | Sim, em produção | `production`: cookies só via HTTPS (`__Host-`), HSTS, logs em JSON, exige a chave secreta. |
| `EXATAMED_SECRET_KEY` | Sim | Chave das sessões. Trocá-la encerra todas as sessões abertas (sem perda de dados). |
| `EXATAMED_CHAVE_AUDITORIA` | Sim | Chave HMAC da cadeia de auditoria. **Nunca altere nem perca**: sem ela a integridade dos registros não pode ser verificada. Guarde cópia em cofre de senhas. |
| `EXATAMED_DATABASE_URL` | Sim | URL do PostgreSQL (`postgres://`, `postgresql://` ou `postgresql+psycopg://`). |
| `EXATAMED_ADMIN_LOGIN` / `EXATAMED_ADMIN_SENHA` | Na 1ª execução | Criam o primeiro administrador se não houver usuários. |
| `EXATAMED_LOG_FORMATO` | Não | `json` (padrão em produção) ou `texto`. |
| `EXATAMED_LOG_NIVEL` | Não | `INFO` (padrão), `WARNING`, `DEBUG`. |
| `WEB_CONCURRENCY` | Não | Número de processos do gunicorn (padrão 2). Regra prática: 2 × CPUs. |

Gere chaves com `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

## 3. Implantação e atualização

1. Faça **backup do banco** (seção 6) antes de qualquer atualização.
2. Publique a nova versão (merge na `main` no Render, ou `docker compose up -d --build`).
3. Na inicialização, o sistema aplica sozinho as atualizações de esquema (colunas, restrições,
   conversão de valores para decimal exato, numeração e selagem de registros antigos). Isso é
   seguro para repetir. Em instalações com várias instâncias, use `--preload` (já configurado)
   e atualize uma instância de cada vez.
4. Confira `GET /saude` (deve responder `200` e a versão nova) e rode a verificação de
   integridade (seção 5).

**Atualização para a 2.0:** registros existentes (movimentações e acessos) são selados na
primeira inicialização. A partir daí, qualquer registro gravado fora da aplicação é apontado
pela verificação. Defina `EXATAMED_CHAVE_AUDITORIA` **antes** de subir a 2.0.

**Atualização para a 2.5 (trilha de auditoria normalizada):** as alterações de cada registro da
trilha saem da coluna de texto JSON `registros_auditoria.alteracoes` para a tabela
`alteracoes_auditoria` (uma linha por campo: `campo`, `valor_anterior`, `valor_novo`). A migração
roda sozinha na primeira inicialização, numa transação única:

1. transfere cada registro e confere que o conteúdo remontado das linhas novas é **idêntico** ao
   texto antigo, sobre o qual o selo HMAC foi calculado (os selos do histórico continuam válidos,
   sem nova selagem);
2. só então remove a coluna antiga.

Se algum registro não puder ser transferido sem perda (texto inválido ou alterado fora da
aplicação), os demais são migrados, a coluna é **mantida** para análise, os ids vão para o log e a
verificação de integridade aponta esses registros. Depois de analisar, rode de novo com
`flask --app exatamed migrar-auditoria` (também serve para acompanhar a migração manualmente).
Faça o backup antes, como em toda atualização.

## 4. Monitoramento

| Sinal | Como obter | Alerta sugerido |
|---|---|---|
| Disponibilidade | `GET /saude` → `200 {"status":"ok","banco":"ok","latencia_banco_ms":...}`; `503` se o banco cair | 2 falhas seguidas em 1 minuto |
| Latência do banco | campo `latencia_banco_ms` | > 200 ms por 5 minutos |
| Erros | logs com `"nivel": "ERROR"` | qualquer ocorrência em produção |
| Taxa de 5xx | logs de acesso (`logger: exatamed.acesso`, campo `status`) | > 1% em 5 minutos |
| Ataques de senha | respostas `429` em `/login`, usuários bloqueados (tela *Usuários*) | > 10 por hora |
| Integridade | `flask --app exatamed verificar-integridade` (código de saída 1 em falha) | qualquer falha |

Cada requisição tem um `X-Request-ID` (aceito do proxy ou gerado), presente na resposta e em
todos os logs dela. A página de erro mostra esse código ao usuário: peça-o ao abrir um chamado.

Os logs **não** registram a query string das URLs, que pode conter dados pessoais.

## 5. Verificação de integridade

```bash
flask --app exatamed verificar-integridade
```

Confere as cadeias seladas (movimentações, acessos a dados pessoais e trilha de auditoria) e
se o saldo de cada lote é igual à soma das suas movimentações. Agende diariamente (cron ou
*Cron Job* do Render) e alerte em caso de código de saída diferente de zero. O administrador
também pode rodar a verificação em *Integridade dos registros*.

### Se a verificação falhar

1. **Não corrija nada no banco.** Preserve as evidências: faça um backup imediato
   (`pg_dump`) e guarde-o à parte.
2. Registre a ocorrência (data, resultado completo da verificação, quem tem acesso ao banco).
3. Identifique a janela: use os números de sequência apontados e o backup anterior mais recente
   que passa na verificação.
4. Acione o responsável técnico da farmácia e o encarregado de dados (DPO): adulteração de
   registros de controlados ou de acessos a dados pessoais pode exigir comunicação à vigilância
   sanitária e à ANPD.
5. Divergência de **saldo de lote** sem quebra de cadeia indica alteração direta na tabela de
   lotes: o valor correto é a soma das movimentações (que é selada).

## 6. Backup e restauração

**Objetivos sugeridos:** RPO de 24 h (ou menor com backup contínuo do provedor) e RTO de 4 h.

```bash
# Backup (formato custom, comprimido)
pg_dump --format=custom --no-owner "$EXATAMED_DATABASE_URL" > exatamed_$(date +%F).dump

# Restauração num banco vazio
pg_restore --no-owner --dbname "$URL_DO_BANCO_NOVO" exatamed_AAAA-MM-DD.dump
```

- Guarde os backups criptografados e fora do provedor principal; retenha pelo menos 30 dias.
- **Teste a restauração todo mês**: restaure num banco separado, suba o sistema apontando para
  ele e rode `verificar-integridade`.
- O backup contém dados de saúde (LGPD): acesso restrito e registrado.
- A `EXATAMED_CHAVE_AUDITORIA` é necessária para verificar backups restaurados.

### Cópia para treinamento ou homologação

Nunca use dados reais fora da produção. Restaure o backup num banco separado e anonimize:

```bash
EXATAMED_ENV=development EXATAMED_DATABASE_URL=<banco-da-copia> flask --app exatamed anonimizar-banco --confirmar
```

### Migração de dados em SQL

Para levar os dados a outra instalação (ou a outro tipo de banco), o sistema gera um arquivo
`.sql` só com `INSERT`, varrendo todas as tabelas:

```bash
flask --app exatamed exportar-sql --saida exatamed_dados.sql              # mesmo tipo de banco
flask --app exatamed exportar-sql --dialeto sqlite --saida dados.sql      # outro tipo de banco
flask --app exatamed exportar-sql --anonimizar --saida dados_anon.sql     # sem dados pessoais
```

No destino, inicie o ExataMed uma vez (cria as tabelas) e carregue o arquivo com
`psql -v ON_ERROR_STOP=1 -f`, `sqlite3 <` ou `flask --app exatamed importar-sql arquivo.sql --confirmar`;
depois rode `verificar-integridade`. Use a mesma `EXATAMED_CHAVE_AUDITORIA` da origem. Para backup
do PostgreSQL, prefira `pg_dump`; a exportação SQL é para migração. Detalhes em
[migracoes/README.md](../migracoes/README.md).

## 7. Incidentes comuns

| Sintoma | Causa provável | Ação |
|---|---|---|
| `/saude` responde 503 | Banco fora do ar ou credenciais erradas | Verifique o PostgreSQL e `EXATAMED_DATABASE_URL`. |
| Todos foram desconectados | `EXATAMED_SECRET_KEY` foi trocada | Esperado; usuários entram de novo. |
| Verificação aponta todas as assinaturas inválidas | `EXATAMED_CHAVE_AUDITORIA` diferente da original | Restaure a chave original do cofre. Não sele de novo. |
| "Muitas tentativas a partir deste endereço" | 30 falhas de login do mesmo IP em 15 min | Aguardar 15 min; se o hospital sai por um único IP, avalie o limite em `auth.py`. |
| Usuário bloqueado | 5 senhas erradas | Administrador desbloqueia em *Usuários*. |
| Administrador perdeu a senha e não há outro | — | `flask --app exatamed criar-admin` com acesso ao servidor. |
| "O saldo do lote mudou durante a operação" | Duas operações simultâneas no mesmo lote | Esperado: a segunda foi recusada para não deixar saldo negativo. Repita a operação. |

## 8. Segurança operacional

- Publique sempre atrás de HTTPS (o Render já faz isso). Em servidor próprio, use um proxy
  (nginx, Traefik) com TLS e mantenha `EXATAMED_ENV=production`.
- Restrinja o acesso ao banco à aplicação e ao DBA; registre quem tem acesso.
- Revise mensalmente: usuários ativos (desative quem saiu da equipe), *LGPD: registro de
  acessos* e a *Trilha de auditoria*.
- O CI roda lint, testes no SQLite e no PostgreSQL (incluindo concorrência real), auditoria de
  dependências (`pip-audit`) e o build da imagem Docker a cada pull request.
