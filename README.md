# ExataMed

**Sistema de gerenciamento de estoque para farmácia hospitalar.**

O ExataMed cadastra medicamentos e materiais médico-hospitalares, controla
entradas, saídas, transferências e dispensações por lote e validade, calcula o
custo pelo método **PEPS** (primeiro que entra, primeiro que sai) e gera os
relatórios de consumo, compras e inventário que a farmácia precisa no dia a dia.

[![Licença: Apache 2.0](https://img.shields.io/badge/licen%C3%A7a-Apache%202.0-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Flask](https://img.shields.io/badge/flask-3.x-lightgrey)

![Painel do ExataMed](docs/img/painel.png)

---

> 📘 **Vai usar o sistema?** Leia o [Guia do usuário](docs/GUIA_DO_USUARIO.md): primeiro acesso,
> roteiro de implantação, dispensação, relatórios e perguntas frequentes. O mesmo guia está dentro
> do sistema, no menu **Ajuda**.

## Sumário

- [Funcionalidades](#funcionalidades)
- [Cadastros](#cadastros)
- [Controle de estoque e método PEPS](#controle-de-estoque-e-método-peps)
- [Dispensação e segurança do paciente](#dispensação-e-segurança-do-paciente)
- [Análises e relatórios](#análises-e-relatórios)
- [Usuários, login e perfis de acesso](#usuários-login-e-perfis-de-acesso)
- [Guia do usuário e primeiros passos](#guia-do-usuário-e-primeiros-passos)
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
- Baixa automática pelo método **PEPS**, sem consumir lotes vencidos.
- **Alertas de alergia** em tempo real na dispensação e bloqueio até a ciência do farmacêutico.
- Exigência de **médico prescritor e nº de prescrição** para itens de controle especial
  (listas da Portaria SVS/MS nº 344/1998 e antimicrobianos).
- **Contagem de inventário** com ajustes rastreáveis.
- Painel com indicadores, itens a repor e lotes vencidos ou próximos do vencimento.
- Seis relatórios gerenciais, com impressão e **exportação em CSV** (compatível com Excel).
- Histórico imutável de movimentações para auditoria, com o **usuário** responsável por cada uma.
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

## Tecnologias

- [Python](https://www.python.org/) 3.10+
- [Flask](https://flask.palletsprojects.com/) 3 e [Flask-SQLAlchemy](https://flask-sqlalchemy.palletsprojects.com/)
- [SQLite](https://www.sqlite.org/) no uso local e [PostgreSQL](https://www.postgresql.org/) na publicação (driver psycopg 3)
- [gunicorn](https://gunicorn.org/) como servidor de produção
- [Bootstrap](https://getbootstrap.com/) 5 e Bootstrap Icons (via CDN)
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

Acesse <http://127.0.0.1:5000> e entre com um dos usuários (com os dados de demonstração:
`admin` / `admin1234`). O banco de dados é criado automaticamente em `instance/exatamed.db`,
já com as localizações *Farmácia SUS* e *Farmácia Particular*. Bancos criados por versões
anteriores são atualizados automaticamente na inicialização.

### Configuração

| Variável de ambiente | Descrição | Padrão |
|----------------------|-----------|--------|
| `EXATAMED_SECRET_KEY` | Chave secreta do Flask (sessões e mensagens). **Obrigatória em produção.** | `dev-troque-esta-chave` |
| `EXATAMED_ENV` | `production` ativa cookies seguros (HTTPS), HSTS e exige a chave secreta. | — |
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
pytest
```

Os testes cobrem a baixa PEPS, o bloqueio de lotes vencidos, as transferências, os alertas de
alergia, o controle especial, os ajustes de inventário, os seis relatórios, a renderização de
todas as telas, o login (bloqueio, senha provisória, redirecionamento seguro, CSRF), as permissões
de cada perfil, a numeração das dispensações (sequência por ano, colisão simultânea), a farmácia
de origem e a atualização de bancos criados por versões anteriores.

## Estrutura do projeto

```
exatamed/
├── exatamed/
│   ├── __init__.py      # fábrica da aplicação, configuração e comandos "demo" e "criar-admin"
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
│   └── static/          # estilos
├── tests/               # testes automatizados (pytest)
├── docs/
│   ├── GUIA_DO_USUARIO.md  # guia do usuário (também exibido no menu Ajuda)
│   └── img/                # capturas de tela
├── render.yaml          # configuração de publicação no Render
├── requirements.txt
├── requirements-dev.txt
├── run.py
└── LICENSE
```

## Roteiro

Melhorias previstas para próximas versões:

- [x] Autenticação de usuários e perfis de acesso (farmacêutico, auxiliar, administrador)
- [x] Registro do usuário em cada movimentação
- [ ] Recuperação de senha por e-mail
- [ ] Escrituração de controlados e integração com o SNGPC/ANVISA
- [ ] Devolução de itens não utilizados ao estoque
- [ ] Leitura de código de barras / DataMatrix na entrada e na dispensação
- [ ] Importação de notas fiscais eletrônicas (XML da NF-e)
- [ ] Gráficos interativos no painel

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
