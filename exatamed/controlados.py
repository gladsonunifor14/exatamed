"""Classificação automática de controle especial pelo princípio ativo.

Referências:
- Portaria SVS/MS nº 344/1998, Anexo I (listas A1 a D1), na atualização vigente publicada por RDC.
- RDC nº 471/2021 (antimicrobianos de venda sob prescrição com retenção da receita), alterada pela
  RDC nº 973/2025; a lista de substâncias está na IN nº 360/2025, que também inclui os agonistas
  do receptor de GLP-1.

A tabela traz as substâncias de uso hospitalar mais comuns, não as listas completas: uma
substância ausente daqui pode ser controlada. A classificação é uma sugestão que o farmacêutico
confere no cadastro; revise a tabela a cada nova atualização do Anexo I ou da IN.
"""

import re
import unicodedata

# Lista -> substâncias (DCB, sem acentos e em minúsculas; sinônimos de uso corrente incluídos).
SUBSTANCIAS = {
    "A1": [
        "alfentanila", "buprenorfina", "fentanila", "fentanil", "hidrocodona", "hidromorfona", "levorfanol",
        "metadona", "morfina", "oxicodona", "oximorfona", "opio", "petidina", "meperidina", "remifentanila",
        "remifentanil", "sufentanila", "sufentanil", "tapentadol",
    ],
    "A2": [
        "codeina", "di-hidrocodeina", "diidrocodeina", "dextropropoxifeno", "etilmorfina", "folcodina",
        "nalbufina", "tramadol",
    ],
    "A3": ["anfetamina", "dexanfetamina", "lisdexanfetamina", "metilfenidato", "dexmetilfenidato"],
    "B1": [
        "alprazolam", "bromazepam", "clobazam", "clonazepam", "clorazepato", "clordiazepoxido", "cloxazolam",
        "diazepam", "estazolam", "eszopiclona", "fenobarbital", "flunitrazepam", "flurazepam", "lorazepam",
        "meprobamato", "midazolam", "nitrazepam", "oxazepam", "remimazolam", "triazolam", "zaleplona",
        "zolpidem", "zopiclona",
    ],
    "B2": ["anfepramona", "femproporex", "mazindol", "sibutramina"],
    "C1": [
        "agomelatina", "amissulprida", "amitriptilina", "aripiprazol", "asenapina", "biperideno", "bupropiona",
        "carbamazepina", "cetamina", "escetamina", "citalopram", "clomipramina", "clorpromazina", "clozapina",
        "desflurano", "desvenlafaxina", "dissulfiram", "divalproato", "droperidol", "duloxetina", "enflurano",
        "escitalopram", "etomidato", "etossuximida", "fenitoina", "flufenazina", "flumazenil", "fluoxetina",
        "fluvoxamina", "gabapentina", "halotano", "haloperidol", "imipramina", "isoflurano", "lacosamida",
        "lamotrigina", "levetiracetam", "levomepromazina", "litio", "lurasidona", "mirtazapina", "misoprostol",
        "naltrexona", "nortriptilina", "olanzapina", "oxcarbazepina", "paliperidona", "paroxetina",
        "periciazina", "pimozida", "pregabalina", "primidona", "propofol", "quetiapina", "risperidona",
        "selegilina", "sertralina", "sevoflurano", "sulpirida", "tianeptina", "tioridazina", "topiramato",
        "trazodona", "triexifenidil", "valproato", "valproico", "venlafaxina", "vigabatrina", "vortioxetina",
        "ziprasidona", "zuclopentixol",
    ],
    "C2": ["acitretina", "isotretinoina"],
    "C3": ["talidomida"],
    "C5": [
        "estanozolol", "mesterolona", "metiltestosterona", "nandrolona", "oxandrolona", "oximetolona",
        "testosterona",
    ],
    "D1": ["efedrina", "pseudoefedrina", "ergometrina", "ergotamina"],
    "ATB": [
        "amicacina", "amoxicilina", "ampicilina", "azitromicina", "aztreonam", "benzilpenicilina",
        "cefadroxila", "cefalexina", "cefalotina", "cefazolina", "cefepima", "cefotaxima", "cefoxitina",
        "ceftarolina", "ceftazidima", "ceftriaxona", "cefuroxima", "ciprofloxacino", "claritromicina",
        "clindamicina", "cloranfenicol", "colistimetato", "colistina", "daptomicina", "doxiciclina",
        "eritromicina", "ertapenem", "estreptomicina", "fosfomicina", "gentamicina", "imipenem",
        "levofloxacino", "linezolida", "meropenem", "metronidazol", "minociclina", "moxifloxacino",
        "nitrofurantoina", "norfloxacino", "ofloxacino", "oxacilina", "penicilina", "piperacilina",
        "polimixina", "secnidazol", "sulfadiazina", "sulfametoxazol", "teicoplanina", "tetraciclina",
        "tigeciclina", "tinidazol", "tobramicina", "trimetoprima", "vancomicina",
    ],
    "GLP1": ["dulaglutida", "liraglutida", "lixisenatida", "semaglutida", "tirzepatida"],
}

# Quando a associação tem substâncias de listas diferentes, vale a mais restritiva.
PRIORIDADE = ["A1", "A2", "A3", "B1", "B2", "C3", "C2", "C5", "C1", "D1", "ATB", "GLP1"]

REFERENCIAS = {
    "ATB": "RDC 471/2021",
    "GLP1": "RDC 471/2021 e IN 360/2025",
}


def normalizar(texto):
    sem_acento = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9-]+", " ", sem_acento.lower()).split())


def _compilar():
    padroes = []
    for lista in PRIORIDADE:
        for substancia in SUBSTANCIAS[lista]:
            padroes.append((lista, substancia, re.compile(rf"(?<![a-z0-9-]){re.escape(substancia)}(?![a-z0-9-])")))
    return padroes


_PADROES = _compilar()


def classificar(*textos):
    """Devolve ``(lista, substância)`` do primeiro texto que contém uma substância controlada.

    Os textos são consultados em ordem (ex.: princípio ativo e, na falta dele, o nome do
    produto). Dentro de um texto, prevalece a lista mais restritiva. Sem correspondência,
    devolve ``(None, None)``.
    """
    for texto in textos:
        normalizado = normalizar(texto)
        if not normalizado:
            continue
        for lista, substancia, padrao in _PADROES:
            if padrao.search(normalizado):
                return lista, substancia
    return None, None


def referencia(lista):
    return REFERENCIAS.get(lista, "Portaria 344/98")
