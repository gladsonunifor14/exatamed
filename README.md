# ExataMed

**Sistema de gerenciamento de estoque para farmácia hospitalar.**

O ExataMed cadastra medicamentos e materiais médico-hospitalares, controla
entradas, saídas, transferências e dispensações por lote e validade, calcula o
custo pelo método **PEPS** (primeiro que entra, primeiro que sai) e gera os
relatórios de consumo, compras e inventário que a farmácia precisa no dia a dia.

[![Licença: Apache 2.0](https://img.shields.io/badge/licen%C3%A7a-Apache%202.0-blue.svg)](LICENSE)
![Versão](https://img.shields.io/badge/vers%C3%A3o-2.0.0-0b6e6e)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
[![CI](https://github.com/gladsonunifor14/exatamed/actions/workflows/ci.yml/badge.svg)](https://github.com/gladsonunifor14/exatamed/actions/workflows/ci.yml)
![Flask](https://img.shields.io/badge/flask-3.x-lightgrey)

![Painel do ExataMed](docs/img/painel.png)

---

> 📘 **Vai usar o sistema?** Leia o [Guia do usuário](docs/GUIA_DO_USUARIO.md): primeiro acesso,
> roteiro de implantação, dispensação, relatórios e perguntas frequentes. O mesmo guia está dentro
> do sistema, no menu **Ajuda**.
>
> 🛠️ **Vai implantar ou operar?** Veja o [Runbook de operação](docs/OPERACAO.md) (configuração,
> monitoramento, backup, incidentes). Avaliação do produto e roadmap:
> [docs/AVALIACAO_PRODUTO.md](docs/AVALIACAO_PRODUTO.md). Novidades: [CHANGELOG](CHANGELOG.md).

## Sumário

- [Funcionalidades](#funcionalidades)
- [Cadastros](#cadastros)
- [Controle de estoque e método PEPS](#controle-de-estoque-e-método-peps)
- [Dispensação e segurança do paciente](#dispensação-e-segurança-do-paciente)
- [Análises e relatórios](#análises-e-relatórios)
- [Usuários, login e perfis de acesso](#usuários-login-e-perfis-de-acesso)
- [Guia do usuário e primeiros passos](#guia-do-usuário-e-primeiros-passos)
- [Proteção de dados pessoais (LGPD)](#proteção-de-dados-pessoais-lgpd)
- [Auditoria e integridade dos dados](#auditoria-e-integridade-dos-dados)
- [Segurança e operação](#segurança-e-operação)
- [Tecnologias](#tecnologias)
- [Instalação e execução](#instalação-e-execução)
- [Publicação na web (Render)](#publicação-na-web-render)
- [Testes](#testes)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Roteiro](#roteiro)
- [Como contribuir](#como-contribuir)
- [Licença](#licença)

## Funcionalidades

- Cadastro de **pacientes**, **médicos**, **medicamentos/materiais** e **localizações**, com
  **endereço preenchido automaticamente pelo CEP** (ViaCEP).
- Estoque por **lote, validade e localização**, com custo unitário por camada.
- **Entradas** (nota fiscal/empenho), **saídas avulsas** (consumo de setor, perdas, avarias),
  **transferências entre locais** e **dispensação ao paciente**.
- Baixa automática pelo método **PEPS**, sem consumir lotes vencidos ou bloqueados, com
  **valores decimais exatos** e baixa atômica (o saldo nunca fica negativo, mesmo com operações simultâneas).
- **Devolução e estorno de dispensação** (total ou parcial) ao mesmo lote e custo, sem apagar o original.
- **Bloqueio de lote** (recall, interdição, quarentena) em todos os locais.
- **Alertas de alergia** em tempo real na dispensação e bloqueio até a ciência do farmacêutico.
- Exigência de **médico prescritor e nº de prescrição** para itens de controle especial
  (listas da Portaria SVS/MS nº 344/1998 e antimicrobianos).
- **Contagem de inventário** com ajustes rastreáveis.
- Painel com indicadores, itens a repor e lotes vencidos ou próximos do vencimento.
- Sete relatórios, incluindo a **escrituração de controlados**, com impressão e **exportação em CSV**.
- **Busca incremental de pacientes** (nome, CPF ou Cartão SUS) na dispensação.
- Histórico de movimentações **selado contra adulteração** (cadeia HMAC), **trilha de auditoria**
  de cadastros e verificação de integridade.
- **Adequação à LGPD:** documentos mascarados em listas, relatórios e exportações, registro de
  acessos a dados pessoais, relatórios sem identificação e anonimização de cadastros.
- **Login com perfis de acesso** (auxiliar, farmacêutico, administrador), bloqueio após tentativas
  erradas e senha provisória no primeiro acesso.

## Cadastros

### Paciente
Nome completo, nome da mãe, data de nascimento e **idade calculada automaticamente**, sexo,
CPF (com validação dos dígitos verificadores), documento de identidade, **Cartão Nacional do SUS**
(validação do CNS), endereço completo com CEP, telefone, nome do responsável e grau de
parentesco (obrigatórios para menores de 18 anos), plano de saúde, alergias conhecidas,
tipo sanguíneo, histórico de doenças graves e profissão.

### Médico
Nome completo, data de nascimento e idade, sexo, CPF, **CRM e UF** (únicos em conjunto),
especialidade, documento de identidade, endereço completo com CEP e telefone.

### Medicamento e material médico-hospitalar
Tipo (medicamento ou material), nome comercial (marca), princípio ativo (**DCB**), apresentação,
laboratório fabricante, **controle especial** (lista da Portaria 344/98), unidade de medida,
localização padrão, **alertas de alergia**, estoques mínimo e máximo.

**Lote, validade, localização e preço de custo** são registrados em cada entrada de estoque,
pois um mesmo produto pode ter vários lotes, em locais diferentes e com custos diferentes.
O custo das saídas é apurado pelo método PEPS.

### Localização
O sistema já vem com os dois locais principais, **Farmácia SUS** e **Farmácia Particular**,
que não podem ser excluídos nem desativados. Os usuários cadastram outros locais conforme a
necessidade: *Leito 1, Leito 2, Leito 3, Sala de parada, Sala de recuperação, UTI* etc.
As localizações servem tanto como local de armazenamento quanto como destino da dispensação.

## Controle de estoque e método PEPS

Cada entrada cria uma **camada de estoque** (lote) com data de entrada, quantidade, validade,
local e custo unitário. Em toda baixa (dispensação ou saída), o sistema:

1. seleciona os lotes do produto no local de origem, **ignorando os vencidos**;
2. ordena pela **data de entrada** (o mais antigo primeiro);
3. consome as camadas em sequência até completar a quantidade, gerando uma movimentação por lote
   com o **custo daquele lote**.

Exemplo: entrada de 5 un. a R$ 2,00 (dia 1) e de 10 un. a R$ 3,00 (dia 10). Uma saída de 8 un.
consome 5 × R$ 2,00 + 3 × R$ 3,00 = **R$ 19,00**, e o estoque remanescente (7 un.) fica
valorizado a R$ 3,00.

As **transferências** entre locais preservam lote, validade, custo e data de entrada originais,
mantendo a ordem PEPS no destino. Operações com saldo insuficiente são recusadas sem alterar o
estoque.

## Dispensação e segurança do paciente

- Seleção do paciente, médico, nº da prescrição, farmácia de origem (**apenas Farmácia SUS ou
  Farmácia Particular**) e **local de dispensação** (leito, sala etc.), com vários itens por dispensação.
- **Numeração automática** no formato número/ano (ex.: **00001/2026**), reiniciada a cada ano e
  protegida contra duplicidade por índice único no banco.
- Ao escolher paciente e produto, a tela mostra **conflitos de alergia**, se o item é de
  controle especial e o saldo disponível na origem.
- A verificação compara as alergias do paciente com o nome comercial, o princípio ativo e os
  alertas de alergia do produto (ex.: paciente alérgico a *penicilina* × produto com alerta
  *penicilinas, betalactâmicos*). Havendo conflito, a dispensação só é concluída com a
  confirmação explícita do farmacêutico, que fica registrada na observação.
- Itens de controle especial exigem médico prescritor e número da prescrição.
- O comprovante da dispensação mostra os lotes efetivamente baixados e o custo PEPS e pode ser impresso.

## Análises e relatórios

| # | Relatório | O que mostra |
|---|-----------|--------------|
| 1 | **Consumo diário** | Custo por dia (dispensações e saídas avulsas), quantidade por produto e média diária no período; filtro por local. |
| 2 | **Resumo de dispensação por data** | Número de dispensações, pacientes atendidos, itens e custo por data, com a lista detalhada. |
| 3 | **Consumo por local de dispensação** | Custo e participação percentual de cada leito/sala/setor, com detalhamento por produto. |
| 4 | **Consumo por paciente** | Dispensações, itens e custo por paciente; ao filtrar um paciente, os itens consumidos. |
| 5 | **Estoque mínimo/máximo e pedido de compra** | Saldo utilizável, mínimo, máximo, consumo médio diário (CMD), cobertura em dias, situação e **sugestão de compra** com custo estimado. |
| 6 | **Inventário** | Posição por lote e local, valorizada pelo custo PEPS, com destaque para lotes vencidos e a vencer em 90 dias, e resumo por produto. |
| 7 | **Escrituração de controlados** | Livro dos medicamentos de controle especial (Portaria 344/98): saldo anterior, entradas, saídas com paciente, prescritor e responsável, saldo corrente e final. Restrito ao farmacêutico; exportação registrada. |

**Cálculo do pedido de compra**

- *Saldo utilizável* = soma dos lotes não vencidos em todos os locais.
- *CMD* = consumo (dispensações + saídas) nos últimos *N* dias ÷ *N* (padrão: 30 dias).
- *Cobertura* = saldo utilizável ÷ CMD.
- Quando o saldo atinge o **estoque mínimo** (ponto de pedido), a sugestão é
  **estoque máximo − saldo utilizável**; o custo estimado usa o custo da entrada mais recente.

![Relatório de pedido de compra](docs/img/pedido.png)

A **contagem de inventário** (menu *Estoque → Contagem de inventário*) permite lançar a contagem
física de cada lote de um local; as diferenças geram movimentações de *ajuste de inventário*.

## Usuários, login e perfis de acesso

Todo o sistema exige login. Cada movimentação de estoque e cada dispensação registra
automaticamente o usuário que a fez, e o comprovante de dispensação mostra o responsável.

| Perfil | Pode |
|--------|------|
| **Auxiliar de farmácia** | Consultar estoque e relatórios; cadastrar pacientes e médicos; registrar entradas, transferências e dispensações de itens **sem** controle especial. |
| **Farmacêutico(a)** | Tudo do auxiliar, mais: dispensar itens de **controle especial**, **liberar dispensação com alerta de alergia**, saídas avulsas, contagem de inventário, cadastrar medicamentos e localizações e excluir registros. |
| **Administrador(a)** | Tudo do farmacêutico, mais: cadastrar usuários, definir perfis, redefinir senhas e desbloquear contas (menu do usuário → *Usuários*). |

Segurança:

- senhas guardadas com *hash* (nunca em texto), mínimo de 8 caracteres com letras e números;
- após **5 tentativas erradas**, o usuário fica bloqueado por 15 minutos (o administrador pode desbloquear);
- senha definida pelo administrador é **provisória**: o usuário precisa trocá-la no primeiro acesso;
- sessão expira em 8 horas; proteção contra CSRF em todos os formulários;
- em produção (`EXATAMED_ENV=production`): cookies apenas por HTTPS, HSTS e cabeçalhos de segurança.

### Primeiro acesso

- **Com dados de demonstração:** `flask --app exatamed demo` cria também os usuários
  `admin` / `admin1234`, `farmaceutico` / `farma1234` e `auxiliar` / `auxiliar1234`.
  Use-os apenas para testes.
- **Para uso real:** crie o administrador com `flask --app exatamed criar-admin` (o comando pede
  login, nome e senha) ou defina as variáveis `EXATAMED_ADMIN_LOGIN` e `EXATAMED_ADMIN_SENHA` —
  o administrador é criado na inicialização, se ainda não houver usuários. Depois, entre como
  administrador e cadastre os demais usuários.

## Guia do usuário e primeiros passos

O ExataMed traz um onboarding em três partes:

1. **[Guia do usuário](docs/GUIA_DO_USUARIO.md)** (`docs/GUIA_DO_USUARIO.md`): passo a passo
   ilustrado para cada perfil, com o roteiro de implantação, a dispensação no dia a dia, os
   relatórios, o método PEPS e as perguntas frequentes.
2. **Página Ajuda dentro do sistema:** exibe o mesmo arquivo do guia, com sumário lateral.
   Existe um texto só: atualizar o guia no repositório atualiza também a ajuda do sistema.
3. **Primeiros passos no painel:** logo após a instalação, o administrador vê um checklist de
   implantação (usuários, locais, medicamentos, estoque mínimo e máximo, médicos e pacientes,
   primeira entrada e primeira dispensação). Cada etapa é marcada sozinha quando os dados são
   cadastrados e tem atalhos para a tela certa e para o trecho do guia. O quadro some quando tudo
   estiver concluído e pode ser ocultado e reexibido.

![Página de ajuda do ExataMed](docs/img/ajuda.png)

## Proteção de dados pessoais (LGPD)

O ExataMed trata dados de saúde, que são dados pessoais **sensíveis** pela LGPD (Lei nº 13.709/2018).
Medidas implementadas:

| Medida | Como funciona |
|---|---|
| **Mascaramento** | CPF (`***.982.247-**`), Cartão SUS (`***********5933`), RG e telefone aparecem parcialmente ocultos em listas, na seleção de pacientes, nos relatórios e nos CSV. Completos só na ficha do cadastro e no comprovante de dispensação. |
| **Registro de acessos** (art. 37) | Tabela `registros_acesso`: quem visualizou a ficha, incluiu, alterou, abriu comprovante, exportou relatório com pacientes ou anonimizou um cadastro, com data, hora e IP. Consulta em *LGPD: registro de acessos* (administrador). |
| **Relatórios sem identificação** | Opção *Ocultar identificação dos pacientes*: o nome vira um código (`P-000123`) e os documentos são omitidos, na tela e no CSV. |
| **Anonimização** (arts. 16 e 18) | O administrador anonimiza paciente, médico ou usuário de forma irreversível, informando o motivo. Os dados identificadores são apagados (da data de nascimento fica o ano) e o histórico de estoque é preservado. |
| **Prazo de guarda** | Quem teve dispensação de medicamento de controle especial (inclusive antimicrobianos) nos últimos 2 anos só pode ser anonimizado após esse prazo (`PRAZO_GUARDA_CONTROLADOS_ANOS` em `exatamed/lgpd.py`). |
| **Cópias anonimizadas** | `flask --app exatamed anonimizar-banco --confirmar` anonimiza todos os dados pessoais de uma **cópia** do banco, para treinamento e testes (bloqueado com `EXATAMED_ENV=production`). |

Essas funções apoiam a adequação, mas não a substituem: a instituição continua responsável pela
política de privacidade, pela base legal de cada tratamento, pela indicação do encarregado (DPO)
e pelo atendimento aos titulares.

## Auditoria e integridade dos dados

| Mecanismo | O que garante |
|---|---|
| **Cadeia selada (HMAC-SHA256)** | Movimentações de estoque, acessos a dados pessoais e a trilha de auditoria recebem número de sequência e assinatura encadeada, com chave fora do banco (`EXATAMED_CHAVE_AUDITORIA`). Alteração, remoção ou inserção direta no banco é detectada e localizada. |
| **Trilha de auditoria** | Toda inclusão, alteração e exclusão de cadastros, com usuário, IP e valores de antes e depois (dados pessoais só como "alterado", compatível com a LGPD). |
| **Conciliação de saldos** | O saldo de cada lote é conferido com a soma das suas movimentações. |
| **Nada é apagado** | Correções são novas movimentações (devolução, ajuste de inventário), sempre com motivo e usuário. |
| **Restrições no banco** | Saldo não negativo, quantidades e custos válidos, número de dispensação único por ano. |

A verificação roda em *Integridade dos registros* (administrador) ou por linha de comando,
para agendamento e alerta:

```bash
flask --app exatamed verificar-integridade   # código de saída 1 se houver problema
```

## Segurança e operação

- **CSP estrita** (`script-src 'self'`), sem JavaScript inline; Bootstrap servido localmente
  (funciona em redes sem internet).
- Sessões encerradas ao trocar a senha, mudar o perfil ou desativar o usuário; limite de falhas
  de login por usuário e por IP; `Cache-Control: no-store` em páginas autenticadas.
- **Logs em JSON** com `X-Request-ID` (sem query string, que pode conter dados pessoais) e
  `/saude` com latência do banco (503 se o banco cair).
- **CI** no GitHub Actions: lint (ruff), testes no SQLite e no PostgreSQL (incluindo concorrência
  real), `pip-audit` e build da imagem Docker.
- **Docker**: `Dockerfile` (usuário sem privilégios, health check) e `docker-compose.yml` com
  PostgreSQL para instalação no próprio hospital. Dependências travadas em `requirements.lock`.

Detalhes no [Runbook de operação](docs/OPERACAO.md).

## Tecnologias

- [Python](https://www.python.org/) 3.10+
- [Flask](https://flask.palletsprojects.com/) 3 e [Flask-SQLAlchemy](https://flask-sqlalchemy.palletsprojects.com/)
- [SQLite](https://www.sqlite.org/) no uso local e [PostgreSQL](https://www.postgresql.org/) na publicação (driver psycopg 3)
- [gunicorn](https://gunicorn.org/) como servidor de produção
- [Bootstrap](https://getbootstrap.com/) 5.3 e Bootstrap Icons, servidos localmente (licenças em `exatamed/static/vendor/LICENSES.md`)
- [Flask-Login](https://flask-login.readthedocs.io/) e [Flask-WTF](https://flask-wtf.readthedocs.io/) (login e proteção CSRF)
- [Python-Markdown](https://python-markdown.github.io/) (página de ajuda)
- [pytest](https://pytest.org/) para os testes

## Instalação e execução

```bash
# 1. Clone o repositório
git clone https://github.com/gladsonunifor14/exatamed.git
cd exatamed

# 2. Crie e ative um ambiente virtual
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Instale as dependências
pip install -r requirements.txt

# 4. Carregue dados e usuários de demonstração...
flask --app exatamed demo
#    ...ou, para uso real, crie apenas o administrador:
# flask --app exatamed criar-admin

# 5. Inicie o servidor
flask --app exatamed run          # ou: python run.py
```

**Com Docker (servidor próprio):** `cp .env.exemplo .env`, preencha as chaves e rode
`docker compose up -d` (sobe o ExataMed e o PostgreSQL). Veja o [runbook](docs/OPERACAO.md).

Acesse <http://127.0.0.1:5000> e entre com um dos usuários (com os dados de demonstração:
`admin` / `admin1234`). O banco de dados é criado automaticamente em `instance/exatamed.db`,
já com as localizações *Farmácia SUS* e *Farmácia Particular*. Bancos criados por versões
anteriores são atualizados automaticamente na inicialização.

### Configuração

| Variável de ambiente | Descrição | Padrão |
|----------------------|-----------|--------|
| `EXATAMED_SECRET_KEY` | Chave secreta do Flask (sessões e mensagens). **Obrigatória em produção.** | `dev-troque-esta-chave` |
| `EXATAMED_ENV` | `production` ativa cookies seguros (HTTPS, `__Host-`), HSTS, logs em JSON e exige a chave secreta. | — |
| `EXATAMED_CHAVE_AUDITORIA` | Chave HMAC da cadeia de auditoria. **Defina em produção, guarde em cofre e nunca altere.** | a chave secreta |
| `EXATAMED_LOG_FORMATO` / `EXATAMED_LOG_NIVEL` | `json` ou `texto`; nível de log. | `json` em produção / `INFO` |
| `EXATAMED_ADMIN_LOGIN` / `EXATAMED_ADMIN_SENHA` | Criam o primeiro administrador, se não houver usuários. | — |
| `EXATAMED_CARREGAR_DEMO` | `1` carrega os dados de demonstração na inicialização, se o banco estiver vazio (sem usuários de demonstração). Use só em ambientes de teste. | — |
| `EXATAMED_DATABASE_URL` (ou `DATABASE_URL`) | URL do banco, ex.: `postgres://usuario:senha@host/exatamed`. URLs `postgres://` e `postgresql://` são convertidas automaticamente para o driver psycopg. | SQLite em `instance/` |

## Publicação na web (Render)

O GitHub Pages publica apenas sites estáticos; o ExataMed precisa de um servidor Python e de um
banco de dados. O repositório já traz o arquivo [`render.yaml`](render.yaml), que configura no
[Render](https://render.com) o sistema web e um banco **PostgreSQL** automaticamente.

> ⚠️ Dados de saúde são dados pessoais sensíveis pela LGPD. Use senhas fortes, cadastre cada
> pessoa com seu próprio usuário e desative os usuários de quem deixar a equipe.

1. Mescle as alterações na branch `main` do GitHub.
2. Crie uma conta em [render.com](https://render.com) entrando com sua conta do GitHub.
3. No painel, clique em **New → Blueprint** e selecione o repositório `exatamed`.
4. O Render lê o `render.yaml`, mostra o que será criado (o serviço web `exatamed` e o banco
   `exatamed-db`) e pede o valor de **`EXATAMED_ADMIN_SENHA`**: digite a senha do primeiro
   administrador (mínimo de 8 caracteres). Clique em **Apply** (ou **Deploy Blueprint**).
5. Aguarde a instalação. O sistema fica disponível em um endereço como
   `https://exatamed.onrender.com`. Entre com o usuário **`admin`** e a senha escolhida.

**Se você já publicou uma versão anterior (sem login):** antes de mesclar esta versão, abra o
serviço `exatamed` no Render, vá em **Environment** e adicione `EXATAMED_ADMIN_LOGIN` (ex.: `admin`),
`EXATAMED_ADMIN_SENHA` (sua senha) e `EXATAMED_ENV` = `production`. Sem um administrador,
ninguém conseguirá entrar no sistema. Os dados já cadastrados são preservados.

A partir daí, **cada `push` na branch `main` publica a nova versão automaticamente**.

O que o `render.yaml` configura:

- instalação com `pip install -r requirements.txt` e execução com o servidor de produção **gunicorn**;
- banco PostgreSQL ligado ao sistema pela variável `EXATAMED_DATABASE_URL`;
- `EXATAMED_SECRET_KEY` gerada aleatoriamente pelo Render e modo de produção (`EXATAMED_ENV`);
- criação do primeiro administrador (`EXATAMED_ADMIN_LOGIN` / `EXATAMED_ADMIN_SENHA`);
- verificação de funcionamento no endereço `/saude`.

**Observações sobre o plano gratuito do Render** (confira as condições atuais no site):

- o serviço web "dorme" após um período sem acesso, e a primeira página seguinte demora alguns
  segundos para abrir;
- o banco PostgreSQL gratuito tem prazo de validade; para uso contínuo, mude para um plano pago
  ou faça cópias de segurança periódicas.

Para uma publicação de **demonstração**, adicione a variável `EXATAMED_CARREGAR_DEMO` = `1` no
serviço: os dados fictícios são carregados na próxima inicialização, se o banco estiver vazio.
Não use essa opção num sistema com dados reais.

Em outros serviços (Railway, Fly.io, servidor próprio), defina `EXATAMED_ENV=production`,
`EXATAMED_SECRET_KEY`, `EXATAMED_DATABASE_URL`, `EXATAMED_ADMIN_LOGIN` e `EXATAMED_ADMIN_SENHA`
e inicie com:

```bash
gunicorn --preload --workers 2 --bind 0.0.0.0:$PORT "exatamed:create_app()"
```

## Testes

```bash
pip install -r requirements-dev.txt
pytest                                  # SQLite em memória

# No PostgreSQL (inclui o teste de concorrência real), como no CI:
EXATAMED_TESTE_BANCO=postgresql+psycopg://usuario:senha@localhost/exatamed_testes pytest
ruff check .                            # lint
```

Os testes cobrem a baixa PEPS, o bloqueio de lotes vencidos, as transferências, os alertas de
alergia, o controle especial, os ajustes de inventário, os sete relatórios, a renderização de
todas as telas, o login (bloqueio, senha provisória, redirecionamento seguro, CSRF), as permissões
de cada perfil, a numeração das dispensações (sequência por ano, colisão simultânea), a farmácia
de origem, as medidas da LGPD (mascaramento, registro de acessos, relatórios anônimos,
anonimização e prazo de guarda), a cadeia de auditoria (detecção de alteração, remoção e
inserção direta no banco), a trilha de auditoria, a devolução, o bloqueio de lote, a escrituração
de controlados, a CSP e as sessões, a concorrência real no PostgreSQL e a atualização de bancos
criados por versões anteriores.

## Estrutura do projeto

```
exatamed/
├── exatamed/
│   ├── __init__.py      # fábrica da aplicação, configuração e comandos "demo" e "criar-admin"
│   ├── auditoria.py     # cadeia selada, trilha de auditoria e verificação de integridade
│   ├── lgpd.py          # LGPD: registro de acessos e anonimização
│   ├── numeros.py       # quantidades e valores decimais exatos
│   ├── observabilidade.py  # logs em JSON e identificador de requisição
│   ├── models.py        # modelos: Usuario, Paciente, Medico, Produto, Localizacao, Lote, Dispensacao, Movimentacao
│   ├── estoque.py       # regras de negócio: entrada, baixa PEPS, transferência, dispensação, inventário
│   ├── relatorios.py    # análises e relatórios
│   ├── ajuda.py         # página de ajuda e checklist de primeiros passos
│   ├── auth.py          # login, perfis de acesso e gestão de usuários
│   ├── cadastros.py     # CRUD genérico dos cadastros e validações
│   ├── validacao.py     # CPF, CEP e Cartão Nacional de Saúde
│   ├── views.py         # telas de estoque, dispensação e relatórios
│   ├── demo.py          # dados de demonstração
│   ├── templates/       # páginas HTML (Jinja2)
│   └── static/          # estilos, JavaScript e bibliotecas servidas localmente (vendor/)
├── tests/               # testes automatizados (pytest)
├── docs/
│   ├── GUIA_DO_USUARIO.md  # guia do usuário (também exibido no menu Ajuda)
│   ├── OPERACAO.md         # runbook de operação
│   ├── AVALIACAO_PRODUTO.md  # avaliação do produto e roadmap
│   └── img/                # capturas de tela
├── .github/workflows/ci.yml  # integração contínua
├── Dockerfile, docker-compose.yml, .env.exemplo
├── render.yaml          # configuração de publicação no Render
├── requirements.lock    # versões exatas (Docker e CI)
├── CHANGELOG.md
├── requirements.txt
├── requirements-dev.txt
├── run.py
└── LICENSE
```

## Roteiro

O roteiro completo, com prioridades e justificativas, está em
[docs/AVALIACAO_PRODUTO.md](docs/AVALIACAO_PRODUTO.md). Próximos passos (P1):

- [ ] Migrações versionadas (Alembic)
- [ ] Dupla checagem de medicamentos de alta vigilância (MAV)
- [ ] Leitura de código de barras / DataMatrix (GS1) na entrada e na dispensação
- [ ] Integração com prescrição eletrônica e prontuário (HL7 FHIR)
- [ ] Exportação para o SNGPC (ANVISA)
- [ ] Autenticação em dois fatores e SSO com o diretório do hospital
- [ ] Relatório dos dados de um titular (direito de acesso, art. 18 da LGPD)

## Como contribuir

1. Faça um *fork* do projeto.
2. Crie uma *branch* para sua alteração: `git checkout -b minha-melhoria`.
3. Escreva testes e garanta que `pytest` passe.
4. Faça o *commit*: `git commit -m "Descreve a melhoria"`.
5. Envie a *branch* e abra um *Pull Request*.

Relatos de erros e sugestões são bem-vindos na aba *Issues*.

## Aviso

O ExataMed é uma ferramenta de apoio à gestão. Os alertas de alergia e de controle especial não
substituem a avaliação do farmacêutico e do médico responsáveis, nem dispensam o cumprimento da
legislação sanitária vigente.

## Licença

Distribuído sob a **Licença Apache, versão 2.0**. Consulte o arquivo [LICENSE](LICENSE).

```
Copyright 2026 ExataMed

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```
