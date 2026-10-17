# Migração de dados em SQL

Os arquivos `.sql` desta pasta contêm apenas comandos `INSERT` (mais os `DELETE` iniciais e, no
PostgreSQL, o ajuste das sequências de ids). Eles servem para carregar dados num banco do
ExataMed que já tenha as tabelas criadas.

| Arquivo | Conteúdo |
|---|---|
| `dados_demonstracao_postgresql.sql` | Dados **fictícios** de demonstração para PostgreSQL (produção no Render) |
| `dados_demonstracao_sqlite.sql` | Os mesmos dados para SQLite (uso local) |

Os dois equivalem ao comando `flask --app exatamed demo` e trazem os usuários de demonstração do
README (`admin`, `farmaceutico`, `auxiliar`). Os selos da cadeia de auditoria foram gerados com a
chave padrão de desenvolvimento: use estes arquivos só em testes ou treinamento.

## Gerar o arquivo a partir de um banco (inclusive o de produção)

O próprio sistema varre todas as tabelas e escreve os `INSERT`, na ordem das chaves estrangeiras e
com os mesmos ids:

```bash
# no servidor (no Render: Shell do serviço), com o banco configurado em DATABASE_URL
flask --app exatamed exportar-sql --saida exatamed_dados.sql

# cópia sem dados pessoais (pacientes, médicos e usuários anonimizados; registro de acessos fora)
flask --app exatamed exportar-sql --anonimizar --saida exatamed_anonimizado.sql

# para carregar num banco de outro tipo
flask --app exatamed exportar-sql --dialeto sqlite --saida exatamed_dados_sqlite.sql
```

> **LGPD:** a exportação sem `--anonimizar` contém dados pessoais e de saúde. Guarde o arquivo
> criptografado, com acesso restrito, e **nunca** o coloque no repositório.

## Carregar o arquivo num banco novo

1. Aponte o ExataMed para o banco novo e inicie-o uma vez: o sistema cria as tabelas.
2. Carregue o arquivo (ele apaga os dados existentes antes de inserir):

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f exatamed_dados.sql      # PostgreSQL
sqlite3 instance/exatamed.db < exatamed_dados_sqlite.sql           # SQLite
flask --app exatamed importar-sql exatamed_dados.sql --confirmar    # qualquer um dos dois
```

3. Confira: `flask --app exatamed verificar-integridade`.

O banco de destino precisa usar a **mesma `EXATAMED_CHAVE_AUDITORIA`** do banco de origem; com outra
chave, a verificação aponta os registros selados como alterados. O arquivo roda numa transação
única: se algo falhar, nada é gravado.
