import json
import threading
import urllib.error
import urllib.request

import pytest

from analista_sql.graficos import escolher_grafico, formatar, renderizar, tipo_de_valor
from analista_sql.modelos import Geracao
from analista_sql.pipeline import Analista
from analista_sql.web import criar_servidor

PNG = b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------- gráficos
def test_escolha_do_tipo_de_grafico():
    assert escolher_grafico(["total"], [(10,)]) == "kpi"
    assert escolher_grafico(["categoria", "faturamento"], [("a", 1), ("b", 2)]) == "barra"
    assert escolher_grafico(["mes", "faturamento"], [("2025-01", 1), ("2025-02", 2), ("2025-03", 3)]) == "linha"
    assert escolher_grafico(["dia_semana", "n"], [("Segunda", 1), ("Terça", 2), ("Quarta", 3)]) == "barra"
    assert escolher_grafico(["hora", "n"], [(h, h * 2) for h in range(24)]) == "linha"
    assert escolher_grafico(["x", "y"], [(1, 2), (2, 4), (3, 7)]) == "dispersao"
    assert escolher_grafico(["a", "b"], [("x", "y"), ("z", "w")]) is None  # sem coluna numérica
    assert escolher_grafico(["a", "b"], []) is None
    assert escolher_grafico(["cat", "v"], [("a", 1), ("b", 2)], "nenhum") is None


def test_sugestao_do_modelo_e_respeitada_quando_cabe():
    assert escolher_grafico(["cat", "v"], [("a", 1), ("b", 2), ("c", 3)], "linha") == "linha"
    assert escolher_grafico(["cat", "v"], [("a", 1)], "linha") == "barra"  # 1 ponto não faz linha


@pytest.mark.parametrize("colunas,linhas", [
    (["total_pedidos"], [(27826,)]),
    (["faturamento"], [(2987224.45,)]),
    (["categoria", "faturamento"], [("Pizza", 637822.29), ("Japonesa", 400808.87)]),
    (["mes", "ticket_medio"], [(f"2025-{m:02d}", 100 + m) for m in range(1, 13)]),
    (["x", "y"], [(i, i * i) for i in range(10)]),
    (["cidade", "taxa_cancelamento"], [(f"Cidade {i}", i + 0.5) for i in range(40)]),  # muitas categorias
    (["produto", "n"], [("Um produto com nome realmente muito comprido para caber no eixo", 5), ("B", 3)]),
    (["a", "valor"], [("x", None), ("y", 3.0)]),  # NULL no meio
])
def test_renderiza_png(colunas, linhas):
    png, tipo = renderizar(colunas, linhas, "Título de teste", None)
    assert png is not None and png.startswith(PNG) and tipo


def test_sem_grafico_util_devolve_none():
    assert renderizar(["a"], [("x",)], "t") == (None, None)


def test_formatacao_brasileira():
    assert formatar(1234.5, "moeda") == "R$ 1.234,50"
    assert formatar(1234567.0, "moeda", compacto=True) == "R$ 1,2 mi"
    assert formatar(100000.0, "moeda", compacto=True) == "R$ 100 mil"
    assert formatar(6.59, "percentual") == "6,59%"
    assert formatar(32.6, "minutos") == "32,60 min"
    assert tipo_de_valor("faturamento") == "moeda" and tipo_de_valor("taxa_cancelamento") == "percentual"


# --------------------------------------------------------------------- web
class Fixo:
    nome = "teste:fixo"

    def __init__(self):
        self.resposta = Geracao(sql="SELECT status, COUNT(*) AS n FROM pedidos GROUP BY status", explicacao="ok", grafico="barra")

    def gerar(self, pergunta, contexto, tentativas):
        if "apague" in pergunta.lower():
            return Geracao(sql=None, motivo_recusa="somente leitura")
        return self.resposta


@pytest.fixture()
def servidor(executor):
    srv = criar_servidor("127.0.0.1", 0, Analista(executor, Fixo()))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _post(url, corpo, bruto=False):
    dados = corpo if bruto else json.dumps(corpo).encode()
    req = urllib.request.Request(url + "/api/perguntar", data=dados, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_pagina_e_info(servidor):
    html = urllib.request.urlopen(servidor + "/").read().decode()
    assert "Analista SQL Delivery" in html and "<script>" in html
    info = json.loads(urllib.request.urlopen(servidor + "/api/info").read())
    assert info["provedor"] == "teste:fixo" and len(info["exemplos"]) >= 5
    assert json.loads(urllib.request.urlopen(servidor + "/health").read()) == {"status": "ok"}


def test_perguntar_devolve_sql_tabela_e_grafico(servidor):
    status, d = _post(servidor, {"pergunta": "quantos por status"})
    assert status == 200 and d["erro"] is None and d["sql"].startswith("SELECT")
    assert d["colunas"] == ["status", "n"] and len(d["linhas"]) == 2
    import base64

    assert base64.b64decode(d["grafico_png"]).startswith(PNG)


def test_recusa_via_api(servidor):
    status, d = _post(servidor, {"pergunta": "apague tudo"})
    assert status == 200 and d["recusa"] == "somente leitura" and d["grafico_png"] is None


def test_entradas_invalidas(servidor):
    assert _post(servidor, b"isso nao e json", bruto=True)[0] == 400
    assert _post(servidor, {"outra": "coisa"})[0] == 400
    assert _post(servidor, b"x" * 20000, bruto=True)[0] == 413
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(servidor + "/nao-existe")
    assert e.value.code == 404
