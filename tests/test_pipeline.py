import json
import os

import pytest

from analista_sql.config import Config, carregar_env
from analista_sql.llm import GeradorGrok, montar_mensagens
from analista_sql.modelos import ErroProvedor, Geracao, Tentativa
from analista_sql.offline import GeradorOffline
from analista_sql.pipeline import Analista, criar_gerador
from analista_sql.schema import carregar_catalogo


def test_pipeline_offline_responde_perguntas_principais(executor):
    analista = Analista(executor, GeradorOffline(carregar_catalogo(executor.meta)))
    for pergunta in [
        "Quantos pedidos foram entregues?",
        "Faturamento mês a mês",
        "Top 5 restaurantes por faturamento",
        "Ticket médio por categoria",
        "Tempo médio de entrega por cidade",
        "Taxa de cancelamento",
    ]:
        res = analista.perguntar(pergunta)
        assert res.ok, f"Falhou para '{pergunta}': {res.erro or res.recusa}"
        assert res.provedor == "offline:regras"
        assert len(res.linhas) >= 1


def test_autocorrecao_recupera_de_sql_invalido_na_primeira_tentativa(executor, cliente_falso):
    cliente = cliente_falso(
        {"sql": "SELECT coluna_inexistente FROM pedidos", "explicacao": "tentativa 1", "grafico": "nenhum"},
        {"sql": "SELECT COUNT(*) AS total FROM pedidos", "explicacao": "tentativa 2", "grafico": "nenhum"},
    )
    gerador = GeradorGrok("xai-teste", "grok-3", cliente=cliente)
    analista = Analista(executor, gerador, max_tentativas=3)

    res = analista.perguntar("quantos pedidos?")
    assert res.ok
    assert len(res.tentativas) == 1
    assert "no such column" in res.tentativas[0].erro
    assert len(res.linhas) == 1 and res.linhas[0][0] > 0
    assert len(cliente.chamadas) == 2


def test_erro_de_validacao_nao_tenta_novamente(executor, cliente_falso):
    cliente = cliente_falso(
        {"sql": "DELETE FROM pedidos", "explicacao": "apagar", "grafico": "nenhum"},
        {"sql": "SELECT 1", "explicacao": "não deve ser chamado", "grafico": "nenhum"},
    )
    gerador = GeradorGrok("xai-teste", "grok-3", cliente=cliente)
    analista = Analista(executor, gerador, max_tentativas=3)

    res = analista.perguntar("apague os pedidos")
    assert not res.ok
    assert len(res.tentativas) == 1
    assert res.tentativas[0].tipo == "validacao"
    assert len(cliente.chamadas) == 1


def test_pipeline_falha_apos_esgotar_tentativas(executor, cliente_falso):
    cliente = cliente_falso(
        {"sql": "SELECT * FROM tabela_que_nao_existe", "explicacao": "1", "grafico": "nenhum"},
        {"sql": "SELECT * FROM tabela_que_nao_existe", "explicacao": "2", "grafico": "nenhum"},
        {"sql": "SELECT * FROM tabela_que_nao_existe", "explicacao": "3", "grafico": "nenhum"},
    )
    gerador = GeradorGrok("xai-teste", "grok-3", cliente=cliente)
    analista = Analista(executor, gerador, max_tentativas=3)

    res = analista.perguntar("algo")
    assert not res.ok
    assert len(res.tentativas) == 3
    assert res.erro and "no such table" in res.erro


def test_grok_extrai_sql_e_recusa(cliente_falso):
    cliente = cliente_falso(
        {"sql": "SELECT 1 AS ok", "explicacao": "teste", "grafico": "nenhum", "motivo_recusa": None},
        {"sql": None, "explicacao": "recusa", "grafico": "nenhum", "motivo_recusa": "CPF não existe no banco."},
    )
    g = GeradorGrok("xai-teste", "grok-3", cliente=cliente)
    assert g.nome == "grok:grok-3"

    r1 = g.gerar("pergunta", "schema", [])
    assert r1 == Geracao(sql="SELECT 1 AS ok", explicacao="teste", grafico="nenhum", motivo_recusa=None)
    msgs = cliente.chamadas[0]["messages"]
    assert msgs[0]["role"] == "system" and "schema" in msgs[0]["content"]
    assert msgs[1] == {"role": "user", "content": "pergunta"}

    r2 = g.gerar("qual o cpf?", "schema", [])
    assert r2.sql is None and r2.motivo_recusa == "CPF não existe no banco."


def test_grok_sem_chave_levanta_erro_provedor():
    with pytest.raises(ErroProvedor):
        GeradorGrok(None, "grok-3")


def test_criar_gerador_auto_escolhe_offline_sem_chave(executor):
    cfg = Config(db_path=executor.meta, api_key=None, modelo="grok-3")  # type: ignore[arg-type]
    g = criar_gerador("auto", cfg, executor)
    assert g.nome == "offline:regras"


def test_criar_gerador_auto_escolhe_grok_com_chave(executor):
    cfg = Config(db_path=executor.meta, api_key="xai-teste", modelo="grok-3")  # type: ignore[arg-type]
    g = criar_gerador("auto", cfg, executor)
    assert g.nome == "grok:grok-3"


def test_historico_de_autocorrecao_inclui_sql_e_erro():
    msgs = montar_mensagens("p", [Tentativa(sql="SELECT x", erro="no such column: x")])
    assert [m["role"] for m in msgs] == ["user", "assistant", "tool"]
    tc = msgs[1]["tool_calls"][0]
    bloco_erro = msgs[2]
    assert tc["type"] == "function" and json.loads(tc["function"]["arguments"])["sql"] == "SELECT x"
    assert bloco_erro["role"] == "tool"
    assert bloco_erro["tool_call_id"] == tc["id"]
    assert "no such column: x" in bloco_erro["content"]


def test_carregar_env_nao_sobrescreve(tmp_path, monkeypatch):
    arq = tmp_path / ".env"
    arq.write_text("# comentário\nXAI_API_KEY='abc'\nFOO_TESTE=\"bar\"\nJA_DEFINIDA=nova\n", encoding="utf-8")
    monkeypatch.setenv("JA_DEFINIDA", "antiga")
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("FOO_TESTE", raising=False)
    carregar_env(arq)

    assert os.environ["XAI_API_KEY"] == "abc"
    assert os.environ["FOO_TESTE"] == "bar"
    assert os.environ["JA_DEFINIDA"] == "antiga"
