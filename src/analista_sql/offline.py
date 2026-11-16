"""Baseline offline: gerador de SQL por regras, sem LLM e sem chave de API.

Serve a três propósitos: (1) deixar o projeto rodar de ponta a ponta sem credenciais,
(2) ser um ponto de comparação na avaliação (quanto o LLM adiciona sobre regras?) e
(3) tornar os testes determinísticos.

Gramática suportada: [métrica] [por dimensão] [filtros] [top N / maior / menor].
Perguntas fora disso (CTEs, janelas, subconsultas, comparações) são recusadas como
"não entendi" -- é exatamente aí que um LLM deve ganhar do baseline.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .modelos import Geracao, Tentativa
from .schema import DIAS_SEMANA_SQL


def normalizar(texto: str) -> str:
    """minúsculas, sem acentos, só letras/dígitos/% separados por espaço único."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9%]+", " ", sem_acento.lower())).strip()


ENTREGUE = "p.status = 'entregue'"

# (id, regex, expressão, alias, rótulo, filtros-base, aliases de tabelas necessárias)
METRICAS: list[dict] = [
    dict(id="unidades", pat=r"unidades|mais vendid|itens vendid|quantidade vendida",
         expr="SUM(i.quantidade)", alias="unidades_vendidas", rotulo="unidades vendidas (pedidos entregues)",
         where=[ENTREGUE], joins={"i"}),
    dict(id="taxa_cancel", pat=r"(taxa|percentual|porcentagem|%).*cancel|cancel.*(taxa|percentual|porcentagem|%)",
         expr="ROUND(100.0 * SUM(CASE WHEN p.status = 'cancelado' THEN 1 ELSE 0 END) / COUNT(*), 2)",
         alias="taxa_cancelamento", rotulo="taxa de cancelamento (%) sobre todos os pedidos", where=[], joins=set()),
    dict(id="cancelados", pat=r"cancel", expr="COUNT(*)", alias="pedidos_cancelados",
         rotulo="pedidos cancelados", where=["p.status = 'cancelado'"], joins=set()),
    dict(id="atrasados", pat=r"atras",
         expr="ROUND(100.0 * SUM(CASE WHEN p.tempo_entrega_min > p.tempo_estimado_min THEN 1 ELSE 0 END) / COUNT(*), 2)",
         alias="pct_atrasados", rotulo="% de pedidos entregues com atraso", where=[ENTREGUE], joins=set()),
    dict(id="ticket", pat=r"ticket|valor medio", expr="ROUND(AVG(p.valor_total), 2)", alias="ticket_medio",
         rotulo="ticket médio (pedidos entregues)", where=[ENTREGUE], joins=set()),
    dict(id="nota", pat=r"\bnotas?\b|avaliac", expr="ROUND(AVG(a.nota), 2)", alias="nota_media",
         rotulo="nota média das avaliações", where=[], joins={"a"}),
    dict(id="tempo", pat=r"tempo|demora|minutos", expr="ROUND(AVG(p.tempo_entrega_min), 2)",
         alias="tempo_medio_entrega_min", rotulo="tempo médio de entrega em minutos", where=[ENTREGUE], joins=set()),
    dict(id="distancia", pat=r"distancia", expr="ROUND(AVG(p.distancia_km), 2)", alias="distancia_media_km",
         rotulo="distância média em km (pedidos entregues)", where=[ENTREGUE], joins=set()),
    dict(id="taxa_entrega", pat=r"taxa de entrega", expr="ROUND(AVG(p.taxa_entrega), 2)",
         alias="taxa_entrega_media", rotulo="taxa de entrega média", where=[ENTREGUE], joins=set()),
    dict(id="desconto", pat=r"desconto", expr="ROUND(SUM(p.desconto), 2)", alias="total_descontos",
         rotulo="total de descontos concedidos", where=[ENTREGUE], joins=set()),
    dict(id="clientes", pat=r"clientes (ativos|distintos|unicos|diferentes)|quantos clientes|numero de clientes",
         expr="COUNT(DISTINCT p.id_cliente)", alias="clientes_ativos",
         rotulo="clientes distintos com pedido entregue", where=[ENTREGUE], joins=set()),
    dict(id="faturamento", pat=r"faturamento|receita|vendas|gmv|faturou|vendeu|faturaram",
         expr="ROUND(SUM(p.valor_total), 2)", alias="faturamento", rotulo="faturamento (pedidos entregues)",
         where=[ENTREGUE], joins=set()),
    dict(id="pedidos", pat=r"pedidos|entregas|quantos|usad[ao]|popular|frequente",
         expr="COUNT(*)", alias="total_pedidos", rotulo="pedidos entregues", where=[ENTREGUE], joins=set()),
]

PREFIXO = (
    r"(?:\b(?:por|cada|qual|quais|top|maior(?:es)?|menor(?:es)?|melhor(?:es)?|pior(?:es)?|mais|menos)\b|\b\d{1,3}\b)"
    r"\s+(?:(?:o|a|os|as|de|do|da)\s+)?(?:\d{1,3}\s+)?(?:(?:maiores|menores|melhores|piores|principais)\s+)?"
)

DIMENSOES: list[dict] = [
    dict(id="categoria", pat=r"categorias?|culinarias?|tipos? de (?:comida|restaurante)", expr="r.categoria",
         alias="categoria", joins={"r"}, rotulo="categoria do restaurante"),
    dict(id="cidade", pat=r"cidades?", expr="r.cidade", alias="cidade", joins={"r"}, rotulo="cidade"),
    dict(id="restaurante", pat=r"restaurantes?", expr="r.nome", alias="restaurante", joins={"r"},
         rotulo="restaurante"),
    dict(id="forma_pagamento", pat=r"formas? de pagamento|meios? de pagamento|metodos? de pagamento",
         expr="p.forma_pagamento", alias="forma_pagamento", joins=set(), rotulo="forma de pagamento"),
    dict(id="modal", pat=r"modais?|veiculos?|tipos? de entregador", expr="e.modal", alias="modal", joins={"e"},
         rotulo="modal do entregador"),
    dict(id="produto", pat=r"produtos?", expr="i.produto", alias="produto", joins={"i"}, rotulo="produto"),
    dict(id="motivo", pat=r"motivos?", expr="p.motivo_cancelamento", alias="motivo_cancelamento", joins=set(),
         rotulo="motivo de cancelamento"),
    dict(id="mes", pat=r"mes(?:es)?", direto=r"mes a mes|mensal|mensalmente|evolu|ao longo do ano|ao longo dos meses",
         expr="strftime('%Y-%m', p.data_pedido)", alias="mes", joins=set(), rotulo="mês", temporal=True,
         ordem="1"),
    dict(id="dia_semana", pat=r"dias? da semana", expr=DIAS_SEMANA_SQL.format(col="p.data_pedido"),
         alias="dia_semana", joins=set(), rotulo="dia da semana", temporal=True,
         ordem="MIN(strftime('%w', p.data_pedido))"),
    dict(id="hora", pat=r"horas?(?: do dia)?", direto=r"por hora|cada hora|hora do dia",
         expr="CAST(strftime('%H', p.data_pedido) AS INTEGER)", alias="hora", joins=set(), rotulo="hora do dia",
         temporal=True, ordem="1"),
]

JOINS = {
    "r": "JOIN restaurantes r ON r.id_restaurante = p.id_restaurante",
    "a": "JOIN avaliacoes a ON a.id_pedido = p.id_pedido",
    "i": "JOIN itens_pedido i ON i.id_pedido = p.id_pedido",
    "e": "JOIN entregadores e ON e.id_entregador = p.id_entregador",
    "c": "JOIN clientes c ON c.id_cliente = p.id_cliente",
}

MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7,
         "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}
ORDINAIS = {"primeiro": 1, "segundo": 2, "terceiro": 3, "quarto": 4, "1": 1, "2": 2, "3": 3, "4": 4}

CATEGORIA_PADROES = {
    "Pizza": r"pizza", "Hambúrguer": r"hamburguer|hamburgueria|burger", "Japonesa": r"japones|sushi",
    "Brasileira": r"brasileir", "Lanches": r"lanche", "Açaí": r"acai", "Saudável": r"saudave",
    "Doces e Bolos": r"\bdoces?\b|\bbolos?\b|confeitaria", "Italiana": r"italian", "Árabe": r"arabe",
    "Padaria": r"padaria",
}
PAGAMENTO_PADROES = {
    "Pix": r"\bpix\b", "Cartão de crédito": r"credito", "Cartão de débito": r"debito",
    "Vale-refeição": r"vale refeicao|vale alimentacao", "Dinheiro": r"dinheiro",
}

RECUSA_ESCRITA = re.compile(r"\b(apague|apagar|delete|deletar|exclua|excluir|remova|remover|atualize|atualizar|altere|alterar|insira|inserir|drop|truncate)\b")
NAO_SUPORTADO = re.compile(
    r"\b(mais de \d|menos de \d|acima|abaixo|pelo menos|no minimo|no maximo|maior que|menor que|superior|inferior|"
    r"comparad|em relacao|crescimento|variacao|acumulad|participacao|representa|desvio|mediana|percentil|"
    r"media geral|media mensal|retencao)\b"
)
RECUSA_DADOS = re.compile(r"\b(telefone|cpf|senha|e mail|email|endereco|cartao numero|previsao|prever|lucro)\b")


@dataclass
class _Consulta:
    metrica: dict
    dimensao: dict | None = None
    filtros: list[str] = field(default_factory=list)
    juncoes: set[str] = field(default_factory=set)
    notas: list[str] = field(default_factory=list)
    limite: int | None = None
    desc: bool = True
    ranking: bool = False


class GeradorOffline:
    nome = "offline:regras"

    def __init__(self, catalogo: dict[str, list[str]]):
        self.cidades = catalogo.get("restaurantes.cidade", [])
        self.categorias = set(catalogo.get("restaurantes.categoria", []))
        self.modais = catalogo.get("entregadores.modal", [])

    # ------------------------------------------------------------------ API
    def gerar(self, pergunta: str, contexto: str, tentativas: list[Tentativa]) -> Geracao:
        t = normalizar(pergunta)
        if RECUSA_ESCRITA.search(t):
            return Geracao(sql=None, motivo_recusa="Este sistema é somente leitura: não altero nem apago dados.")
        if RECUSA_DADOS.search(t):
            return Geracao(sql=None, motivo_recusa="Essa informação não existe no banco (dados anonimizados e sem custos).")

        if NAO_SUPORTADO.search(t):
            return Geracao(sql=None, motivo_recusa="Essa pergunta usa uma construção (limiar, comparação, acumulado...) "
                                                   "que o baseline por regras não suporta.")

        entidade = self._contagem_de_entidade(t)
        if entidade:
            return entidade

        metrica = next((m for m in METRICAS if re.search(m["pat"], t)), None)
        if metrica is None:
            return Geracao(sql=None, motivo_recusa="Não consegui identificar qual métrica você quer calcular.")

        q = _Consulta(metrica=metrica)
        q.dimensao = self._dimensao(t)
        if q.dimensao is None and metrica["id"] == "unidades":
            q.dimensao = next(d for d in DIMENSOES if d["id"] == "produto")
        if q.dimensao and q.dimensao["id"] == "produto" and metrica["id"] != "unidades":
            q.metrica = next(m for m in METRICAS if m["id"] == "unidades")
            q.notas.append("com produto como dimensão, uso unidades vendidas")
        if q.dimensao and q.dimensao["id"] == "motivo" and metrica["id"] not in ("cancelados",):
            q.metrica = next(m for m in METRICAS if m["id"] == "cancelados")

        self._filtros(t, q)
        self._ranking(t, q)
        return self._montar(q)

    # ----------------------------------------------------------- dimensões
    def _dimensao(self, t: str) -> dict | None:
        melhor: tuple[int, dict] | None = None
        for d in DIMENSOES:
            posicoes = []
            m = re.search(PREFIXO + r"(?:" + d["pat"] + r")\b", t)
            if m:
                posicoes.append(m.start())
            if d.get("direto"):
                m2 = re.search(d["direto"], t)
                if m2:
                    posicoes.append(m2.start())
            if posicoes and (melhor is None or min(posicoes) < melhor[0]):
                melhor = (min(posicoes), d)
        return melhor[1] if melhor else None

    # -------------------------------------------------------------- filtros
    def _filtros(self, t: str, q: _Consulta) -> None:
        dim = q.dimensao["id"] if q.dimensao else None

        if dim != "cidade":
            for cidade in self.cidades:
                if re.search(rf"\b{re.escape(normalizar(cidade))}\b", t):
                    q.filtros.append(f"r.cidade = '{cidade}'")
                    q.juncoes.add("r")
                    q.notas.append(f"cidade = {cidade}")
                    break
        if dim != "categoria":
            for cat, padrao in CATEGORIA_PADROES.items():
                if cat in self.categorias and re.search(padrao, t):
                    q.filtros.append(f"r.categoria = '{cat}'")
                    q.juncoes.add("r")
                    q.notas.append(f"categoria = {cat}")
                    break
        if dim != "forma_pagamento":
            for forma, padrao in PAGAMENTO_PADROES.items():
                if re.search(padrao, t):
                    q.filtros.append(f"p.forma_pagamento = '{forma}'")
                    q.notas.append(f"pagamento = {forma}")
                    break
        if re.search(r"assinantes?|clube", t) and not re.search(r"nao assinantes?", t):
            q.filtros.append("c.assinante_clube = 1")
            q.juncoes.add("c")
            q.notas.append("somente assinantes do clube")
        if re.search(r"fins? de semana|final de semana", t) and dim != "dia_semana":
            q.filtros.append("strftime('%w', p.data_pedido) IN ('0', '6')")
            q.notas.append("fins de semana")
        if re.search(r"\bsem cupom\b", t):
            q.filtros.append("p.cupom IS NULL")
        elif re.search(r"\bcom cupom\b|\bcupons?\b", t):
            q.filtros.append("p.cupom IS NOT NULL")

        if dim != "mes":
            ano = re.search(r"\b(20\d\d)\b", t)
            ano_n = int(ano.group(1)) if ano else 2025
            mes = next((n for nome, n in MESES.items() if re.search(rf"\b{nome}\b", t)), None)
            tri = re.search(r"(primeiro|segundo|terceiro|quarto|[1-4])\s*o?\s*trimestre", t)
            if mes:
                ini, fim = f"{ano_n}-{mes:02d}-01", (f"{ano_n + 1}-01-01" if mes == 12 else f"{ano_n}-{mes + 1:02d}-01")
                q.filtros.append(f"p.data_pedido >= '{ini}' AND p.data_pedido < '{fim}'")
                q.notas.append(f"período {ini[:7]}")
            elif tri:
                n = ORDINAIS[tri.group(1)]
                ini, fim = f"{ano_n}-{3 * n - 2:02d}-01", (f"{ano_n + 1}-01-01" if n == 4 else f"{ano_n}-{3 * n + 1:02d}-01")
                q.filtros.append(f"p.data_pedido >= '{ini}' AND p.data_pedido < '{fim}'")
                q.notas.append(f"{n}º trimestre de {ano_n}")
            elif ano and ano_n != 2025:
                q.filtros.append(f"p.data_pedido >= '{ano_n}-01-01' AND p.data_pedido < '{ano_n + 1}-01-01'")

    # -------------------------------------------------------------- ranking
    def _ranking(self, t: str, q: _Consulta) -> None:
        if q.dimensao is None:
            return
        n = None
        m = (re.search(r"\btop\s*(\d{1,3})\b", t) or re.search(r"\b(\d{1,3})\s+(?:\w+\s+){0,2}(?:maiores|menores|melhores|piores|mais)\b", t)
             or re.search(r"\b(?:os|as)\s+(\d{1,3})\b", t))
        if m:
            n = int(m.group(1))
        elif re.search(r"\btop\b", t):
            n = 10
        crescente = bool(re.search(r"\b(menor|menores|pior|piores|menos|minimo)\b", t))
        superlativo = bool(re.search(r"\b(maior|maiores|menor|menores|melhor|melhores|pior|piores|mais|menos)\b", t))
        if n is None and superlativo and re.search(r"\bqual\b", t) and not re.search(r"\bquais\b", t):
            n = 1
        if n is not None or (superlativo and not q.dimensao.get("temporal")):
            q.ranking = True
        q.limite = n
        q.desc = not crescente

    # -------------------------------------------------- contagem de entidades
    def _contagem_de_entidade(self, t: str) -> Geracao | None:
        """'Quantos restaurantes/entregadores/assinantes ...' consultam tabelas de cadastro."""
        if re.search(r"quantos restaurantes|numero de restaurantes", t):
            tabela, alias, rotulo, dims = "restaurantes", "total_restaurantes", "restaurantes", {"categoria": "categoria", "cidade": "cidade"}
            filtros = []
            for cidade in self.cidades:
                if re.search(rf"\b{re.escape(normalizar(cidade))}\b", t):
                    filtros.append(f"cidade = '{cidade}'")
        elif re.search(r"quantos entregadores|numero de entregadores", t):
            tabela, alias, rotulo, dims = "entregadores", "total_entregadores", "entregadores", {"modal": "modal", "cidade": "cidade"}
            filtros = []
            for modal in self.modais:
                if re.search(rf"\b{modal}\b", t):
                    filtros.append(f"modal = '{modal}'")
            for cidade in self.cidades:
                if re.search(rf"\b{re.escape(normalizar(cidade))}\b", t):
                    filtros.append(f"cidade = '{cidade}'")
        elif re.search(r"quantos (clientes (sao|estao) )?assinantes|quantos clientes (sao|estao) assinantes", t):
            tabela, alias, rotulo, dims = "clientes", "total_assinantes", "clientes assinantes do clube", {"cidade": "cidade"}
            filtros = ["assinante_clube = 1"]
        else:
            return None

        coluna = next((col for chave, col in dims.items()
                       if re.search(PREFIXO + rf"(?:{chave}s?|{chave.replace('_', ' ')}s?)\b", t)), None)
        where = f" WHERE {' AND '.join(filtros)}" if filtros else ""
        if coluna:
            sql = (f"SELECT {coluna}, COUNT(*) AS {alias} FROM {tabela}{where} "
                   f"GROUP BY {coluna} ORDER BY {alias} DESC, {coluna}")
            return Geracao(sql=sql, explicacao=f"Contagem de {rotulo} por {coluna}.", grafico="barra")
        return Geracao(sql=f"SELECT COUNT(*) AS {alias} FROM {tabela}{where}",
                       explicacao=f"Contagem de {rotulo}.", grafico="nenhum")

    # ------------------------------------------------------------- montagem
    def _montar(self, q: _Consulta) -> Geracao:
        m, d = q.metrica, q.dimensao
        juncoes = set(m["joins"]) | q.juncoes | (set(d["joins"]) if d else set())
        where = list(m["where"]) + q.filtros
        ordem_juncoes = [k for k in ("r", "a", "i", "e", "c") if k in juncoes]
        partes = [f"SELECT {d['expr'] + ' AS ' + d['alias'] + ', ' if d else ''}{m['expr']} AS {m['alias']}",
                  "FROM pedidos p"]
        partes.extend(JOINS[k] for k in ordem_juncoes)
        if where:
            partes.append("WHERE " + " AND ".join(where))
        if d:
            partes.append("GROUP BY 1")
            if q.ranking or not d.get("temporal"):
                direcao = "DESC" if q.desc else "ASC"
                partes.append(f"ORDER BY {m['alias']} {direcao}, {d['alias']} ASC")
            else:
                partes.append(f"ORDER BY {d['ordem']}")
            if q.limite:
                partes.append(f"LIMIT {q.limite}")
        sql = "\n".join(partes)

        texto = f"Calculei {m['rotulo']}"
        if d:
            texto += f" por {d['rotulo']}"
        if q.notas:
            texto += " (" + "; ".join(q.notas) + ")"
        grafico = "nenhum" if not d else ("linha" if d.get("temporal") and not q.ranking else "barra")
        return Geracao(sql=sql, explicacao=texto + ".", grafico=grafico)
