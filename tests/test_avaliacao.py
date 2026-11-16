import json
from pathlib import Path

import pytest

from analista_sql.avaliacao import avaliar, carregar_casos, comparar_resultados, gerar_relatorio, resumir
from analista_sql.modelos import Geracao
from analista_sql.pipeline import Analista

CASOS = Path(__file__).resolve().parents[1] / "evals" / "casos.json"


# ------------------------------------------------------------ comparação
def test_iguais_ignora_ordem_das_linhas_quando_nao_ordenado():
    assert comparar_resultados([("a", 1), ("b", 2)], [("b", 2), ("a", 1)])[0]


def test_ordem_importa_quando_ordenado():
    assert not comparar_resultados([("a", 1), ("b", 2)], [("b", 2), ("a", 1)], ordenado=True)[0]
    assert comparar_resultados([("a", 1), ("b", 2)], [("a", 1), ("b", 2)], ordenado=True)[0]


def test_ignora_ordem_das_colunas():
    assert comparar_resultados([("a", 1), ("b", 2)], [(1, "a"), (2, "b")])[0]


def test_tolerancia_numerica_e_int_vs_float():
    assert comparar_resultados([(10,)], [(10.0,)])[0]
    assert comparar_resultados([(3.14,)], [(3.1449,)])[0]
    assert not comparar_resultados([(3.14,)], [(3.16,)])[0]


def test_none_so_casa_com_none():
    assert comparar_resultados([(None, 1)], [(None, 1)])[0]
    assert not comparar_resultados([(None,)], [(0,)])[0]


def test_coluna_ou_linha_extra_e_erro():
    ok, motivo = comparar_resultados([("a", 1)], [("a", 1, 9)])
    assert not ok and "colunas" in motivo
    ok, motivo = comparar_resultados([("a", 1)], [("a", 1), ("b", 2)])
    assert not ok and "linhas" in motivo


def test_resultado_vazio_so_casa_com_vazio():
    assert comparar_resultados([], [])[0]
    assert not comparar_resultados([], [(1,)])[0]


def test_valores_diferentes_sao_reprovados():
    assert not comparar_resultados([("a", 1)], [("a", 2)])[0]
    assert not comparar_resultados([("Pizza",)], [("pizza",)])[0]


# ------------------------------------------------------ conjunto de casos
def test_casos_tem_formato_valido():
    casos = carregar_casos(CASOS)
    assert len(casos) >= 50
    for c in casos:
        assert {"id", "nivel", "pergunta", "sql_ref", "ordenado"} <= c.keys()
        assert c["nivel"] in {"facil", "medio", "dificil", "recusa"}
        assert (c["sql_ref"] is None) == (c["nivel"] == "recusa")
    assert {c["nivel"] for c in casos} == {"facil", "medio", "dificil", "recusa"}


def test_todas_as_consultas_de_referencia_executam(executor):
    for caso in carregar_casos(CASOS):
        if caso["sql_ref"]:
            executor.executar(caso["sql_ref"])  # não pode levantar


def test_referencias_de_ranking_sao_marcadas_como_ordenadas():
    for c in carregar_casos(CASOS):
        if c["sql_ref"] and "LIMIT" in c["sql_ref"]:
            assert c["ordenado"], c["id"]


# ------------------------------------------------- avaliação de ponta a ponta
class GeradorRoteirizado:
    nome = "teste:roteiro"

    def __init__(self, respostas):
        self.respostas = respostas  # pergunta -> Geracao

    def gerar(self, pergunta, contexto, tentativas):
        return self.respostas[pergunta]


def test_avaliar_classifica_cada_situacao(executor):
    ref = "SELECT COUNT(*) AS n FROM pedidos WHERE status = 'entregue'"
    casos = [
        {"id": "a", "nivel": "facil", "pergunta": "certo", "sql_ref": ref, "ordenado": False},
        {"id": "b", "nivel": "facil", "pergunta": "errado", "sql_ref": ref, "ordenado": False},
        {"id": "c", "nivel": "facil", "pergunta": "quebra", "sql_ref": ref, "ordenado": False},
        {"id": "d", "nivel": "facil", "pergunta": "recusa_indevida", "sql_ref": ref, "ordenado": False},
        {"id": "e", "nivel": "recusa", "pergunta": "recusa_certa", "sql_ref": None, "ordenado": False},
        {"id": "f", "nivel": "recusa", "pergunta": "escrita", "sql_ref": None, "ordenado": False},
        {"id": "g", "nivel": "recusa", "pergunta": "respondeu", "sql_ref": None, "ordenado": False},
    ]
    gerador = GeradorRoteirizado({
        "certo": Geracao(sql="SELECT COUNT(*) AS total FROM pedidos WHERE status = 'entregue'"),
        "errado": Geracao(sql="SELECT COUNT(*) AS total FROM pedidos"),
        "quebra": Geracao(sql="SELECT coluna_inexistente FROM pedidos"),
        "recusa_indevida": Geracao(sql=None, motivo_recusa="não sei"),
        "recusa_certa": Geracao(sql=None, motivo_recusa="dado inexistente"),
        "escrita": Geracao(sql="DELETE FROM pedidos"),
        "respondeu": Geracao(sql="SELECT 1 AS x"),
    })
    analista = Analista(executor, gerador, max_tentativas=2)
    res = {r["id"]: r for r in avaliar(analista, casos, verboso=False)}

    assert res["a"]["status"] == "correto" and res["a"]["correto"]
    assert res["b"]["status"] == "resultado_errado"
    assert res["c"]["status"] == "erro_execucao"
    assert res["d"]["status"] == "recusa_indevida"
    assert res["e"]["status"] == "recusa_correta" and res["e"]["correto"]
    assert res["f"]["status"] == "recusa_correta" and "validação" in res["f"]["motivo"]
    assert res["g"]["status"] == "respondeu_indevidamente" and not res["g"]["correto"]

    resumo = resumir(list(res.values()))
    assert resumo["respondiveis"] == 4 and resumo["acuracia_execucao"] == pytest.approx(0.25)
    assert resumo["recusa_correta"] == pytest.approx(2 / 3)
    assert resumo["sql_executavel"] == pytest.approx(0.5)  # a e b rodaram; c e d não
    relatorio = gerar_relatorio(list(res.values()), "teste", "x.db")
    assert "Acurácia por execução" in relatorio and "### c" in relatorio


def test_autocorrecao_conta_como_acerto_com_falha_previa(executor):
    class Corrige:
        nome = "teste:corrige"

        def gerar(self, pergunta, contexto, tentativas):
            if not tentativas:
                return Geracao(sql="SELECT nome_errado FROM pedidos")
            return Geracao(sql="SELECT COUNT(*) AS n FROM pedidos WHERE status = 'entregue'")

    caso = {"id": "x", "nivel": "facil", "pergunta": "q", "ordenado": False,
            "sql_ref": "SELECT COUNT(*) FROM pedidos WHERE status = 'entregue'"}
    [r] = avaliar(Analista(executor, Corrige()), [caso], verboso=False)
    assert r["correto"] and r["falhas_antes"] == 1
    assert resumir([r])["autocorrigidos"] == 1


def test_json_de_casos_e_utf8_valido():
    json.loads(CASOS.read_text(encoding="utf-8"))
