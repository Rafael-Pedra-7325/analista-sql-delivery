"""Gerador de dados sintéticos de delivery (determinístico por semente).

Nenhum dado real é usado: restaurantes, clientes e pedidos são inventados, com padrões
plausíveis (picos no almoço e jantar, fins de semana mais fortes, crescimento ao longo do
ano, atraso que derruba a nota) para que as perguntas de negócio tenham respostas
interessantes.
"""

from __future__ import annotations

import bisect
import random
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from .schema import SCHEMA_SQL

ANO = 2025

CIDADES: list[tuple[str, str, float]] = [
    ("São Paulo", "SP", 0.22),
    ("Rio de Janeiro", "RJ", 0.14),
    ("Belo Horizonte", "MG", 0.10),
    ("Brasília", "DF", 0.10),
    ("Curitiba", "PR", 0.09),
    ("Porto Alegre", "RS", 0.08),
    ("Salvador", "BA", 0.08),
    ("Recife", "PE", 0.07),
    ("Fortaleza", "CE", 0.07),
    ("Goiânia", "GO", 0.05),
]

# categoria -> (prefixos de nome, (preparo mín, máx) em min, peso de popularidade, produtos)
CATEGORIAS: dict[str, dict] = {
    "Pizza": {
        "prefixos": ["Pizzaria", "Forneria", "Casa da Pizza"],
        "preparo": (18, 30), "peso": 1.3,
        "produtos": [("Pizza Margherita", 42.0), ("Pizza Calabresa", 45.0), ("Pizza Quatro Queijos", 52.0),
                     ("Pizza Portuguesa", 49.0), ("Refrigerante 2L", 12.0)],
    },
    "Hambúrguer": {
        "prefixos": ["Burger", "Hamburgueria", "Grill"],
        "preparo": (14, 24), "peso": 1.3,
        "produtos": [("Cheeseburger", 28.0), ("Bacon Burger", 34.0), ("Burger Duplo", 39.0),
                     ("Batata Frita", 16.0), ("Milkshake", 18.0), ("Refrigerante Lata", 7.0)],
    },
    "Japonesa": {
        "prefixos": ["Sushi", "Temakeria", "Casa Oriental"],
        "preparo": (16, 28), "peso": 0.9,
        "produtos": [("Combo Sushi 20 peças", 68.0), ("Temaki Salmão", 29.0), ("Yakisoba", 38.0),
                     ("Hot Roll", 32.0), ("Sashimi Salmão", 44.0)],
    },
    "Brasileira": {
        "prefixos": ["Restaurante", "Cozinha", "Panela"],
        "preparo": (14, 26), "peso": 1.0,
        "produtos": [("Feijoada Individual", 36.0), ("Prato Feito", 27.0), ("Strogonoff de Frango", 31.0),
                     ("Moqueca de Peixe", 54.0), ("Suco Natural", 9.0)],
    },
    "Lanches": {
        "prefixos": ["Lanchonete", "Lanches", "Sanduicheria"],
        "preparo": (10, 20), "peso": 1.1,
        "produtos": [("X-Tudo", 26.0), ("X-Salada", 21.0), ("Misto Quente", 12.0),
                     ("Pastel de Carne", 10.0), ("Coxinha", 8.0), ("Refrigerante Lata", 7.0)],
    },
    "Açaí": {
        "prefixos": ["Açaí", "Casa do Açaí", "Tigela"],
        "preparo": (8, 15), "peso": 0.7,
        "produtos": [("Açaí 300ml", 18.0), ("Açaí 500ml", 26.0), ("Açaí 700ml", 34.0),
                     ("Vitamina de Frutas", 15.0)],
    },
    "Saudável": {
        "prefixos": ["Verde", "Fit", "Bowl"],
        "preparo": (12, 22), "peso": 0.6,
        "produtos": [("Salada Caesar", 29.0), ("Bowl de Frango", 33.0), ("Wrap Integral", 27.0),
                     ("Suco Verde", 12.0), ("Poke Vegano", 38.0)],
    },
    "Doces e Bolos": {
        "prefixos": ["Doceria", "Confeitaria", "Ateliê"],
        "preparo": (8, 16), "peso": 0.6,
        "produtos": [("Brigadeiro (6 un)", 18.0), ("Bolo de Cenoura (fatia)", 12.0), ("Torta de Limão", 16.0),
                     ("Cheesecake", 19.0), ("Brownie", 11.0)],
    },
    "Italiana": {
        "prefixos": ["Cantina", "Trattoria", "Osteria"],
        "preparo": (18, 30), "peso": 0.7,
        "produtos": [("Spaghetti à Bolonhesa", 42.0), ("Lasanha", 46.0), ("Risoto de Funghi", 51.0),
                     ("Fettuccine Alfredo", 44.0), ("Tiramisù", 20.0)],
    },
    "Árabe": {
        "prefixos": ["Esfiharia", "Oriente", "Casa Árabe"],
        "preparo": (12, 22), "peso": 0.6,
        "produtos": [("Esfiha de Carne (6 un)", 24.0), ("Kibe (6 un)", 22.0), ("Combo Shawarma", 36.0),
                     ("Falafel", 28.0)],
    },
    "Padaria": {
        "prefixos": ["Padaria", "Panificadora", "Pão & Cia"],
        "preparo": (8, 16), "peso": 0.8,
        "produtos": [("Pão Francês (10 un)", 8.0), ("Café com Leite", 7.0), ("Sanduíche Natural", 15.0),
                     ("Croissant", 9.0), ("Bolo de Fubá (fatia)", 6.0)],
    },
}

NOMES_PROPRIOS = [
    "Bella Massa", "Dom Forno", "Sabor Real", "Tio Zé", "Nona Rosa", "Estrela", "Villa Verde", "Capital",
    "Imperial", "Brasa Viva", "Sol Nascente", "Quintal", "do Chef", "Rota 66", "Maré Alta", "Cantinho",
    "da Esquina", "Ouro Fino", "Bom Prato", "Fogo Alto", "Primavera", "Central", "do Bairro", "Gosto Bom",
    "Mestre Cuca", "Boa Mesa", "Vila Nova", "Paraíso",
]

PAGAMENTOS = [("Pix", 0.38), ("Cartão de crédito", 0.34), ("Cartão de débito", 0.10),
              ("Vale-refeição", 0.12), ("Dinheiro", 0.06)]
MODAIS = [("moto", 0.70), ("bicicleta", 0.20), ("carro", 0.10)]
MOTIVOS = [("Restaurante fechado", 0.25), ("Cliente desistiu", 0.35),
           ("Falta de entregador", 0.25), ("Item indisponível", 0.15)]

FATOR_DIA_SEMANA = [0.85, 0.88, 0.92, 0.98, 1.20, 1.25, 1.10]  # segunda ... domingo
PESO_HORA = [0.2, 0.1, 0.05, 0.02, 0.02, 0.05, 0.2, 0.5, 0.8, 1.0, 1.5, 4.0, 7.0, 6.0, 3.0, 2.0,
             2.2, 3.0, 5.0, 8.0, 9.0, 6.0, 3.0, 1.0]
RESTAURANTES_POR_CIDADE = 22


def _escolha(rnd: random.Random, pares: list[tuple]) -> str:
    return rnd.choices([p[0] for p in pares], weights=[p[1] for p in pares])[0]


def _data_aleatoria(rnd: random.Random, ini: date, fim: date) -> str:
    return (ini + timedelta(days=rnd.randint(0, (fim - ini).days))).isoformat()


def _criar_restaurantes(rnd: random.Random) -> list[dict]:
    restaurantes: list[dict] = []
    usados: set[str] = set()
    categorias = list(CATEGORIAS)
    for cidade, uf, _ in CIDADES:
        cats = categorias * 2  # cada categoria aparece duas vezes por cidade
        for categoria in cats[:RESTAURANTES_POR_CIDADE]:
            cfg = CATEGORIAS[categoria]
            while True:
                nome = f"{rnd.choice(cfg['prefixos'])} {rnd.choice(NOMES_PROPRIOS)}"
                if nome not in usados:
                    usados.add(nome)
                    break
            qualidade = rnd.uniform(0.3, 1.0)
            mult = rnd.uniform(0.85, 1.35)
            restaurantes.append({
                "id": len(restaurantes) + 1,
                "nome": nome,
                "categoria": categoria,
                "cidade": cidade,
                "uf": uf,
                "data_cadastro": _data_aleatoria(rnd, date(2021, 1, 1), date(2024, 12, 31)),
                "comissao": rnd.choice([0.12, 0.15, 0.23]),
                "qualidade": qualidade,
                "peso": qualidade * cfg["peso"] * rnd.uniform(0.6, 1.6),
                "precos": {p: round(base * mult, 2) for p, base in cfg["produtos"]},
                "preparo": cfg["preparo"],
            })
    return restaurantes


def gerar_banco(caminho: str | Path, semente: int = 42, escala: float = 1.0) -> dict[str, int]:
    """Cria o banco SQLite em `caminho` (sobrescrevendo) e devolve a contagem por tabela.

    `escala` multiplica o volume diário de pedidos (1.0 ≈ 30 mil pedidos no ano).
    """
    rnd = random.Random(semente)
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if caminho.exists():
        caminho.unlink()

    restaurantes = _criar_restaurantes(rnd)
    rest_por_cidade: dict[str, list[dict]] = {}
    for r in restaurantes:
        rest_por_cidade.setdefault(r["cidade"], []).append(r)

    n_clientes = max(300, int(3000 * escala))
    n_entregadores = max(60, int(400 * escala))
    cidades = [(c, w) for c, _, w in CIDADES]
    uf_de = {c: uf for c, uf, _ in CIDADES}

    clientes = []
    for i in range(1, n_clientes + 1):
        cidade = _escolha(rnd, cidades)
        if rnd.random() < 0.70:
            cad = _data_aleatoria(rnd, date(2023, 1, 1), date(2024, 12, 31))
        else:
            cad = _data_aleatoria(rnd, date(ANO, 1, 1), date(ANO, 11, 30))
        clientes.append((i, cidade, uf_de[cidade], cad, 1 if rnd.random() < 0.18 else 0))

    entregadores = []
    for i in range(1, n_entregadores + 1):
        cidade = _escolha(rnd, cidades)
        entregadores.append((i, cidade, _escolha(rnd, MODAIS), _data_aleatoria(rnd, date(2022, 1, 1), date(2025, 6, 30))))
    modal_de = {e[0]: e[2] for e in entregadores}
    entreg_por_cidade: dict[str, list[int]] = {}
    for e in entregadores:
        entreg_por_cidade.setdefault(e[1], []).append(e[0])
    for c, _, _ in CIDADES:  # garante ao menos um entregador por cidade
        if c not in entreg_por_cidade:
            entreg_por_cidade[c] = [rnd.choice(entregadores)[0]]

    # clientes por cidade, ordenados por data de cadastro (para só pedir depois de cadastrado)
    cli_por_cidade: dict[str, list[tuple]] = {}
    for c in sorted(clientes, key=lambda x: (x[3], x[0])):
        cli_por_cidade.setdefault(c[1], []).append(c)
    datas_cad = {cid: [c[3] for c in lst] for cid, lst in cli_por_cidade.items()}

    pedidos, itens, avaliacoes = [], [], []
    base_diaria = 80 * escala
    dia = date(ANO, 1, 1)
    while dia.year == ANO:
        fator_mes = 0.88 + 0.22 * (dia.month - 1) / 11 + (0.05 if dia.month == 12 else 0.0)
        n_dia = round(base_diaria * FATOR_DIA_SEMANA[dia.weekday()] * fator_mes * rnd.uniform(0.92, 1.08))
        horarios = sorted(
            datetime(dia.year, dia.month, dia.day, h, rnd.randint(0, 59), rnd.randint(0, 59))
            for h in rnd.choices(range(24), weights=PESO_HORA, k=n_dia)
        )
        for momento in horarios:
            data_str = momento.strftime("%Y-%m-%d %H:%M:%S")
            cidade = _escolha(rnd, cidades)
            lista = cli_por_cidade.get(cidade, [])
            elegiveis = bisect.bisect_right(datas_cad.get(cidade, []), data_str)
            if elegiveis == 0:
                continue
            # clientes mais antigos pedem mais (cauda longa)
            cliente = lista[int(elegiveis * rnd.random() ** 1.7)]
            rest = rnd.choices(rest_por_cidade[cidade], weights=[r["peso"] for r in rest_por_cidade[cidade]])[0]

            produtos = rnd.sample(list(rest["precos"]), k=min(len(rest["precos"]), rnd.choices([1, 2, 3, 4], weights=[35, 35, 20, 10])[0]))
            id_pedido = len(pedidos) + 1
            valor_itens = 0.0
            for p in produtos:
                qtd = rnd.choice([1, 1, 1, 2, 2, 3])
                preco = rest["precos"][p]
                valor_itens += qtd * preco
                itens.append((len(itens) + 1, id_pedido, p, qtd, preco))
            valor_itens = round(valor_itens, 2)

            km = round(min(14.0, max(0.4, rnd.lognormvariate(1.0, 0.5))), 1)
            taxa = 0.0 if (cliente[4] and rnd.random() < 0.7) else round(3.5 + 1.1 * km, 2)
            cupom, desconto = None, 0.0
            if rnd.random() < 0.22:
                sorteio = rnd.choice(["BEMVINDO10", "FRETE5", "FOME15"])
                if sorteio == "BEMVINDO10" and valor_itens >= 30:
                    cupom, desconto = sorteio, 10.0
                elif sorteio == "FRETE5" and taxa > 0:
                    cupom, desconto = sorteio, min(5.0, taxa)
                elif sorteio == "FOME15":
                    cupom, desconto = sorteio, round(valor_itens * 0.15, 2)
            total = round(max(0.0, valor_itens + taxa - desconto), 2)
            estimado = int(round((25 + 3.5 * km) / 5) * 5)

            hora = momento.hour
            pico_jantar = 19 <= hora <= 21
            p_cancel = min(0.2, 0.045 + (0.02 if pico_jantar else 0.0) + 0.004 * km)
            cancelado = rnd.random() < p_cancel
            if cancelado:
                entregador = rnd.choice(entreg_por_cidade[cidade]) if rnd.random() < 0.4 else None
                pedidos.append((id_pedido, cliente[0], rest["id"], entregador, data_str, "cancelado",
                                _escolha(rnd, MOTIVOS), _escolha(rnd, PAGAMENTOS), cupom, valor_itens, taxa,
                                desconto, total, km, estimado, None))
                continue

            entregador = rnd.choice(entreg_por_cidade[cidade])
            modal = modal_de.get(entregador, "moto")
            ajuste = {"moto": 0.0, "bicicleta": 4.0 + 1.2 * km, "carro": 3.0}[modal]
            tempo = int(round(rnd.randint(*rest["preparo"]) + 3.6 * km + ajuste + (5 if pico_jantar else 0)
                              + rnd.gauss(0, 5)))
            tempo = max(10, tempo)
            pedidos.append((id_pedido, cliente[0], rest["id"], entregador, data_str, "entregue", None,
                            _escolha(rnd, PAGAMENTOS), cupom, valor_itens, taxa, desconto, total, km,
                            estimado, tempo))
            if rnd.random() < 0.55:
                atraso = max(0, tempo - estimado)
                bruto = 2.7 + 2.0 * rest["qualidade"] - 0.04 * atraso + rnd.gauss(0, 0.8)
                nota = int(min(5, max(1, round(bruto))))
                quando = (momento + timedelta(minutes=tempo + rnd.randint(5, 240))).strftime("%Y-%m-%d %H:%M:%S")
                avaliacoes.append((len(avaliacoes) + 1, id_pedido, nota, quando))
        dia += timedelta(days=1)

    conn = sqlite3.connect(caminho)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.executemany("INSERT INTO restaurantes VALUES (?,?,?,?,?,?,?)",
                         [(r["id"], r["nome"], r["categoria"], r["cidade"], r["uf"], r["data_cadastro"], r["comissao"])
                          for r in restaurantes])
        conn.executemany("INSERT INTO clientes VALUES (?,?,?,?,?)", clientes)
        conn.executemany("INSERT INTO entregadores VALUES (?,?,?,?)", entregadores)
        conn.executemany("INSERT INTO pedidos VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", pedidos)
        conn.executemany("INSERT INTO itens_pedido VALUES (?,?,?,?,?)", itens)
        conn.executemany("INSERT INTO avaliacoes VALUES (?,?,?,?)", avaliacoes)
        conn.commit()
        conn.execute("ANALYZE")
    finally:
        conn.close()

    return {
        "restaurantes": len(restaurantes), "clientes": len(clientes), "entregadores": len(entregadores),
        "pedidos": len(pedidos), "itens_pedido": len(itens), "avaliacoes": len(avaliacoes),
    }
