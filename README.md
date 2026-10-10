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

## Sumário

- [Funcionalidades](#funcionalidades)
- [Cadastros](#cadastros)
- [Controle de estoque e método PEPS](#controle-de-estoque-e-método-peps)
- [Dispensação e segurança do paciente](#dispensação-e-segurança-do-paciente)
- [Análises e relatórios](#análises-e-relatórios)
- [Tecnologias](#tecnologias)
- [Instalação e execução](#instalação-e-execução)
- [Testes](#testes)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Roteiro](#roteiro)
- [Como contribuir](#como-contribuir)
- [Licença](#licença)

## Funcionalidades

- Cadastro de **pacientes**, **médicos**, **medicamentos/materiais** e **localizações**.
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
- Histórico imutável de movimentações para auditoria.

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

- Seleção do paciente, médico, nº da prescrição, farmácia de origem e **local de dispensação**
  (leito, sala etc.), com vários itens por dispensação.
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

## Tecnologias

- [Python](https://www.python.org/) 3.10+
- [Flask](https://flask.palletsprojects.com/) 3 e [Flask-SQLAlchemy](https://flask-sqlalchemy.palletsprojects.com/)
- [SQLite](https://www.sqlite.org/) por padrão (qualquer banco suportado pelo SQLAlchemy, como PostgreSQL, pode ser usado)
- [Bootstrap](https://getbootstrap.com/) 5 e Bootstrap Icons (via CDN)
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

# 4. (Opcional) Carregue dados de demonstração
flask --app exatamed demo

# 5. Inicie o servidor
flask --app exatamed run          # ou: python run.py
```

Acesse <http://127.0.0.1:5000>. O banco de dados é criado automaticamente em
`instance/exatamed.db`, já com as localizações *Farmácia SUS* e *Farmácia Particular*.

### Configuração

| Variável de ambiente | Descrição | Padrão |
|----------------------|-----------|--------|
| `EXATAMED_SECRET_KEY` | Chave secreta do Flask (sessões e mensagens). **Defina em produção.** | `dev-troque-esta-chave` |
| `EXATAMED_DATABASE_URL` | URL do banco no formato SQLAlchemy, ex.: `postgresql://usuario:senha@host/exatamed` | SQLite em `instance/` |

Para produção, use um servidor WSGI, por exemplo:

```bash
pip install gunicorn
gunicorn "exatamed:create_app()"
```

## Testes

```bash
pip install -r requirements-dev.txt
pytest
```

Os testes cobrem a baixa PEPS, o bloqueio de lotes vencidos, as transferências, os alertas de
alergia, o controle especial, os ajustes de inventário, os seis relatórios e a renderização de
todas as telas.

## Estrutura do projeto

```
exatamed/
├── exatamed/
│   ├── __init__.py      # fábrica da aplicação, filtros e comando "demo"
│   ├── models.py        # modelos: Paciente, Medico, Produto, Localizacao, Lote, Dispensacao, Movimentacao
│   ├── estoque.py       # regras de negócio: entrada, baixa PEPS, transferência, dispensação, inventário
│   ├── relatorios.py    # análises e relatórios
│   ├── cadastros.py     # CRUD genérico dos cadastros e validações
│   ├── validacao.py     # CPF, CEP e Cartão Nacional de Saúde
│   ├── views.py         # telas de estoque, dispensação e relatórios
│   ├── demo.py          # dados de demonstração
│   ├── templates/       # páginas HTML (Jinja2)
│   └── static/          # estilos
├── tests/               # testes automatizados (pytest)
├── docs/img/            # capturas de tela
├── requirements.txt
├── requirements-dev.txt
├── run.py
└── LICENSE
```

## Roteiro

Melhorias previstas para próximas versões:

- [ ] Autenticação de usuários e perfis de acesso (farmacêutico, auxiliar, administrador)
- [ ] Trilha de auditoria por usuário
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
