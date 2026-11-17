from types import SimpleNamespace

import pytest

from analista_sql.baseline import GeradorBaseline
from analista_sql.config import Config, carregar_env
from analista_sql.dados import gerar_banco
from analista_sql.llm import GeradorClaude, RespostaLLM, Tentativa, montar_mensagens
from analista_sql.pipeline import PipelineAnalista


@pytest.fixture()
def banco(tmp_path):
    db = tmp_path / "delivery.db"
    gerar_banco(db, n_pedidos=80, seed=7)
    return db


def test_pipeline_com_baseline_responde_todas_as_perguntas(banco):
    cfg = Config(db_path=banco, api_key=None, modelo="m")
    pipe = PipelineAnalista(cfg)
    for pergunta in [
        "Quantos pedidos foram entregues?",
        "Faturamento mensal",
        "Top 5 restaurantes por faturamento",
        "Ticket médio por categoria",
        "Tempo médio de entrega por cidade",
        "Taxa de cancelamento",
    ]:
        res = pipe.perguntar(pergunta)
        assert res.sucesso, f"Falhou para '{pergunta}': {res.erro}"
        assert res.provedor == "baseline"
        assert len(res.linhas) >= 1


def test_autocorrecao_recupera_de_sql_invalido_na_primeira_tentativa(banco):
    class GeradorQueErraUmaVez:
        def __init__(self):
            self.chamadas = 0

        def gerar(self, pergunta, schema, tentativas):
            self.chamadas += 1
            if self.chamadas == 1:
                return RespostaLLM("SELECT coluna_inexistente FROM pedidos", "tentativa 1", "nenhum")
            assert len(tentativas) == 1
            assert "no such column" in tentativas[0].erro
            return RespostaLLM("SELECT COUNT(*) AS total FROM pedidos", "tentativa 2", "nenhum")

    cfg = Config(db_path=banco, api_key=None, modelo="m")
    pipe = PipelineAnalista(cfg, gerador=GeradorQueErraUmaVez())
    res = pipe.perguntar("quantos pedidos?")
    assert res.sucesso and res.tentativas == 2 and res.linhas == [(80,)]


def test_pipeline_falha_apos_esgotar_tentativas(banco):
    class GeradorSempreQuebrado:
        def gerar(self, pergunta, schema, tentativas):
            return RespostaLLM("SELECT * FROM tabela_que_nao_existe", "ruim", "nenhum")

    cfg = Config(db_path=banco, api_key=None, modelo="m")
    pipe = PipelineAnalista(cfg, gerador=GeradorSempreQuebrado())
    res = pipe.perguntar("algo")
    assert not res.sucesso and res.tentativas == 3 and "no such table" in res.erro


def test_claude_extrai_a_chamada_de_ferramenta():
    chamadas = []

    class ClienteFalso:
        class messages:
            @staticmethod
            def create(**kwargs):
                chamadas.append(kwargs)
                return SimpleNamespace(
                    content=[
                        SimpleNamespace(
                            type="tool_use",
                            name="gerar_sql",
                            input={"sql": "SELECT 1 AS ok", "explicacao": "teste", "grafico": "nenhum"},
                        )
                    ]
                )

    cfg = Config(db_path=None, api_key="sk-teste", modelo="claude-sonnet-4-6")  # type: ignore[arg-type]
    g = GeradorClaude(cfg, cliente=ClienteFalso())
    r = g.gerar("pergunta", "schema", [])
    assert r == RespostaLLM(sql="SELECT 1 AS ok", explicacao="teste", grafico="nenhum")
    assert chamadas[0]["messages"] == [{"role": "user", "content": "pergunta"}]


def test_historico_de_autocorrecao_inclui_sql_e_erro():
    msgs = montar_mensagens("p", [Tentativa(sql="SELECT x", erro="no such column: x")])
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    bloco_uso = msgs[1]["content"][0]
    bloco_erro = msgs[2]["content"][0]
    assert bloco_uso["type"] == "tool_use" and bloco_uso["input"]["sql"] == "SELECT x"
    assert bloco_erro["type"] == "tool_result" and bloco_erro["is_error"] is True
    assert bloco_erro["tool_use_id"] == bloco_uso["id"]
    assert "no such column: x" in bloco_erro["content"]


def test_carregar_env_nao_sobrescreve(tmp_path, monkeypatch):
    arq = tmp_path / ".env"
    arq.write_text("# comentário\nANTHROPIC_API_KEY='abc'\nFOO_TESTE=\"bar\"\nJA_DEFINIDA=nova\n", encoding="utf-8")
    monkeypatch.setenv("JA_DEFINIDA", "antiga")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("FOO_TESTE", raising=False)
    carregar_env(arq)
    import os

    assert os.environ["ANTHROPIC_API_KEY"] == "abc" and os.environ["FOO_TESTE"] == "bar" and os.environ["JA_DEFINIDA"] == "antiga"
