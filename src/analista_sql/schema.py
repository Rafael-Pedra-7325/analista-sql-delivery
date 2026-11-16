"""Esquema do banco, dicionário de dados, regras de negócio e contexto para o LLM.

Este módulo é a "fonte da verdade" semântica do projeto: o mesmo texto de regras de
negócio é usado no prompt do Claude, no baseline offline e como convenção das
consultas de referência da avaliação.
"""

from __future__ import annotations

import sqlite3

SCHEMA_SQL = """
CREATE TABLE restaurantes (
    id_restaurante INTEGER PRIMARY KEY,
    nome           TEXT NOT NULL,
    categoria      TEXT NOT NULL,
    cidade         TEXT NOT NULL,
    uf             TEXT NOT NULL,
    data_cadastro  TEXT NOT NULL,
    taxa_comissao  REAL NOT NULL
);

CREATE TABLE clientes (
    id_cliente      INTEGER PRIMARY KEY,
    cidade          TEXT NOT NULL,
    uf              TEXT NOT NULL,
    data_cadastro   TEXT NOT NULL,
    assinante_clube INTEGER NOT NULL CHECK (assinante_clube IN (0, 1))
);

CREATE TABLE entregadores (
    id_entregador INTEGER PRIMARY KEY,
    cidade        TEXT NOT NULL,
    modal         TEXT NOT NULL CHECK (modal IN ('moto', 'bicicleta', 'carro')),
    data_cadastro TEXT NOT NULL
);

CREATE TABLE pedidos (
    id_pedido           INTEGER PRIMARY KEY,
    id_cliente          INTEGER NOT NULL REFERENCES clientes (id_cliente),
    id_restaurante      INTEGER NOT NULL REFERENCES restaurantes (id_restaurante),
    id_entregador       INTEGER REFERENCES entregadores (id_entregador),
    data_pedido         TEXT NOT NULL,
    status              TEXT NOT NULL CHECK (status IN ('entregue', 'cancelado')),
    motivo_cancelamento TEXT,
    forma_pagamento     TEXT NOT NULL,
    cupom               TEXT,
    valor_itens         REAL NOT NULL,
    taxa_entrega        REAL NOT NULL,
    desconto            REAL NOT NULL,
    valor_total         REAL NOT NULL,
    distancia_km        REAL NOT NULL,
    tempo_estimado_min  INTEGER NOT NULL,
    tempo_entrega_min   INTEGER
);

CREATE TABLE itens_pedido (
    id_item        INTEGER PRIMARY KEY,
    id_pedido      INTEGER NOT NULL REFERENCES pedidos (id_pedido),
    produto        TEXT NOT NULL,
    quantidade     INTEGER NOT NULL,
    preco_unitario REAL NOT NULL
);

CREATE TABLE avaliacoes (
    id_avaliacao   INTEGER PRIMARY KEY,
    id_pedido      INTEGER NOT NULL UNIQUE REFERENCES pedidos (id_pedido),
    nota           INTEGER NOT NULL CHECK (nota BETWEEN 1 AND 5),
    data_avaliacao TEXT NOT NULL
);

CREATE INDEX idx_pedidos_data        ON pedidos (data_pedido);
CREATE INDEX idx_pedidos_restaurante ON pedidos (id_restaurante);
CREATE INDEX idx_pedidos_cliente     ON pedidos (id_cliente);
CREATE INDEX idx_itens_pedido        ON itens_pedido (id_pedido);
"""

# Descrição de cada tabela e coluna (vai para o prompt do LLM).
DESCRICOES: dict[str, tuple[str, dict[str, str]]] = {
    "restaurantes": (
        "Restaurantes parceiros.",
        {
            "id_restaurante": "identificador do restaurante",
            "nome": "nome fantasia",
            "categoria": "tipo de culinária",
            "cidade": "cidade do restaurante",
            "uf": "sigla do estado",
            "data_cadastro": "data de entrada na plataforma (YYYY-MM-DD)",
            "taxa_comissao": "fração do pedido cobrada do restaurante (0.12 = 12%)",
        },
    ),
    "clientes": (
        "Clientes (dados anonimizados, sem nome/CPF/telefone).",
        {
            "id_cliente": "identificador do cliente",
            "cidade": "cidade do cliente",
            "uf": "sigla do estado",
            "data_cadastro": "data de cadastro (YYYY-MM-DD)",
            "assinante_clube": "1 se assina o clube de benefícios, 0 caso contrário",
        },
    ),
    "entregadores": (
        "Entregadores parceiros (dados anonimizados).",
        {
            "id_entregador": "identificador do entregador",
            "cidade": "cidade de atuação",
            "modal": "veículo usado: moto, bicicleta ou carro",
            "data_cadastro": "data de cadastro (YYYY-MM-DD)",
        },
    ),
    "pedidos": (
        "Um registro por pedido (entregue ou cancelado).",
        {
            "id_pedido": "identificador do pedido",
            "id_cliente": "cliente que fez o pedido",
            "id_restaurante": "restaurante que recebeu o pedido",
            "id_entregador": "entregador (pode ser NULL em cancelados)",
            "data_pedido": "data e hora do pedido, texto 'YYYY-MM-DD HH:MM:SS'",
            "status": "'entregue' ou 'cancelado'",
            "motivo_cancelamento": "motivo; só preenchido quando status = 'cancelado'",
            "forma_pagamento": "como o cliente pagou",
            "cupom": "código do cupom usado (NULL se não usou)",
            "valor_itens": "soma dos itens em R$",
            "taxa_entrega": "taxa de entrega em R$ (0 para assinantes com frete grátis)",
            "desconto": "desconto do cupom em R$",
            "valor_total": "valor_itens + taxa_entrega - desconto, em R$",
            "distancia_km": "distância restaurante-cliente em km",
            "tempo_estimado_min": "prazo prometido ao cliente, em minutos",
            "tempo_entrega_min": "tempo real de entrega em minutos (NULL em cancelados)",
        },
    ),
    "itens_pedido": (
        "Itens de cada pedido (um pedido tem 1 a 4 itens).",
        {
            "id_item": "identificador do item",
            "id_pedido": "pedido ao qual o item pertence",
            "produto": "nome do produto",
            "quantidade": "unidades pedidas",
            "preco_unitario": "preço de uma unidade em R$",
        },
    ),
    "avaliacoes": (
        "Avaliação do cliente (só parte dos pedidos entregues é avaliada).",
        {
            "id_avaliacao": "identificador da avaliação",
            "id_pedido": "pedido avaliado (1 avaliação por pedido)",
            "nota": "nota inteira de 1 a 5",
            "data_avaliacao": "data e hora da avaliação",
        },
    ),
}

# Colunas de texto com poucos valores distintos: listadas no prompt para o modelo
# usar exatamente a grafia certa nos filtros.
COLUNAS_ENUM: list[tuple[str, str]] = [
    ("restaurantes", "categoria"),
    ("restaurantes", "cidade"),
    ("entregadores", "modal"),
    ("pedidos", "status"),
    ("pedidos", "forma_pagamento"),
    ("pedidos", "cupom"),
    ("pedidos", "motivo_cancelamento"),
    ("itens_pedido", "produto"),
]

REGRAS_NEGOCIO: list[str] = [
    "Pedido válido para volume e receita: status = 'entregue'. Só a taxa de cancelamento e as "
    "contagens de cancelados olham pedidos cancelados.",
    "Faturamento = SUM(pedidos.valor_total) dos pedidos entregues (já inclui a taxa de entrega e "
    "desconta o cupom).",
    "Ticket médio = AVG(pedidos.valor_total) dos pedidos entregues.",
    "Taxa de cancelamento (%) = 100 * pedidos cancelados / todos os pedidos.",
    "A cidade de um pedido é a cidade do restaurante (restaurantes.cidade).",
    "Pedido atrasado: tempo_entrega_min > tempo_estimado_min (somente entregues).",
    "Nota média = AVG(avaliacoes.nota); só parte dos pedidos entregues tem avaliação.",
    "Clientes ativos = clientes distintos com ao menos um pedido entregue no período.",
    "Unidades vendidas de um produto = SUM(itens_pedido.quantidade) em pedidos entregues.",
    "Os dados cobrem 2025-01-01 a 2025-12-31; 'este ano' ou 'no ano' significa 2025. Datas são "
    "texto ISO 'YYYY-MM-DD HH:MM:SS': use strftime()/date().",
]

CONVENCOES_SAIDA: list[str] = [
    "Mês deve aparecer como 'YYYY-MM' (strftime('%Y-%m', data_pedido)).",
    "Dia da semana deve aparecer com o nome em português: Domingo, Segunda, Terça, Quarta, Quinta, "
    "Sexta, Sábado.",
    "Arredonde valores monetários, médias e percentuais a 2 casas decimais com ROUND(x, 2); "
    "percentuais vão de 0 a 100.",
    "Use aliases em português, em snake_case (ex.: faturamento, total_pedidos, ticket_medio).",
    "Devolva só as colunas pedidas (em geral a dimensão e a métrica). Não use LIMIT, exceto em "
    "rankings ('top N', 'maior', 'menor').",
    "Use somente as tabelas e colunas listadas neste esquema.",
]

DIAS_SEMANA_SQL = (
    "CASE CAST(strftime('%w', {col}) AS INTEGER) "
    "WHEN 0 THEN 'Domingo' WHEN 1 THEN 'Segunda' WHEN 2 THEN 'Terça' WHEN 3 THEN 'Quarta' "
    "WHEN 4 THEN 'Quinta' WHEN 5 THEN 'Sexta' ELSE 'Sábado' END"
)


def carregar_catalogo(conn: sqlite3.Connection, limite: int = 80) -> dict[str, list[str]]:
    """Valores distintos das colunas de COLUNAS_ENUM, no formato {'tabela.coluna': [...]}."""
    catalogo: dict[str, list[str]] = {}
    for tabela, coluna in COLUNAS_ENUM:
        linhas = conn.execute(
            f"SELECT DISTINCT {coluna} FROM {tabela} WHERE {coluna} IS NOT NULL ORDER BY 1 LIMIT ?",
            (limite + 1,),
        ).fetchall()
        valores = [str(v[0]) for v in linhas]
        if len(valores) <= limite:
            catalogo[f"{tabela}.{coluna}"] = valores
    return catalogo


def periodo_dos_dados(conn: sqlite3.Connection) -> tuple[str, str]:
    minimo, maximo = conn.execute("SELECT MIN(data_pedido), MAX(data_pedido) FROM pedidos").fetchone()
    return str(minimo), str(maximo)


def montar_contexto(conn: sqlite3.Connection) -> str:
    """Texto com tabelas, colunas, relações, valores válidos e regras, para o prompt."""
    partes: list[str] = ["## Tabelas (SQLite)"]
    tabelas = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )]
    for tabela in tabelas:
        desc_tabela, desc_colunas = DESCRICOES.get(tabela, ("", {}))
        fks = {r[3]: f"{r[2]}.{r[4]}" for r in conn.execute(f"PRAGMA foreign_key_list({tabela})")}
        partes.append(f"\nTABELA {tabela}: {desc_tabela}")
        for _, nome, tipo, _, _, pk in conn.execute(f"PRAGMA table_info({tabela})"):
            extra = " [PK]" if pk else ""
            if nome in fks:
                extra += f" [FK -> {fks[nome]}]"
            partes.append(f"  - {nome} {tipo}{extra}: {desc_colunas.get(nome, '')}")

    partes.append("\n## Valores possíveis (use exatamente esta grafia, com acentos)")
    for chave, valores in carregar_catalogo(conn).items():
        partes.append(f"  - {chave}: " + " | ".join(valores))

    ini, fim = periodo_dos_dados(conn)
    partes.append(f"\n## Período dos dados\n  pedidos.data_pedido vai de {ini} até {fim}.")
    partes.append("\n## Regras de negócio")
    partes.extend(f"  - {r}" for r in REGRAS_NEGOCIO)
    partes.append("\n## Convenções da resposta")
    partes.extend(f"  - {r}" for r in CONVENCOES_SAIDA)
    return "\n".join(partes)
