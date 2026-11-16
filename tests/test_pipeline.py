import pytest

from analista_sql.config import Config, carregar_env
from analista_sql.llm import FERRAMENTA, GeradorClaude, montar_mensagens
from analista_sql.modelos import ErroProvedor, Geracao, Tentativa
from analista_sql.offline import GeradorOffline
from analista_sql.pipeline import Analista, criar_gerador
from analista_sql.schema import carregar_catalogo


# ----------------------------------------------------------- GeradorClaude
def test_claude_extrai_a_chamada_de_ferramenta(cliente_falso):
    cliente = cliente_falso({"sql": " SELECT 1 AS x ", "explicacao": "um", "grafico": "nenhum", "motivo_recusa": None})
    g = GeradorClaude(None, "modelo-x", client=cliente)
    out = g.gerar("pergunta", "CONTEXTO", [])
    assert out.sql == "SELECT 1 AS x" and out.explicacao == "um" and out.grafico == "nenhum"

    chamada = cliente.chamadas[0]
    assert chamada["model"] == "modelo-x"
    assert chamada["tool_choice"] == {"type": "tool", "name": FERRAMENTA["name"]}
    assert "CONTEXTO" in chamada["system"][0]["text"]
    assert chamada["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert chamada["messages"] == [{"role": "user", "content": "pergunta"}]


def test_claude_recusa_vem_com_sql_nulo(cliente_falso):
    g = GeradorClaude(None, "m", client=cliente_falso({"sql": None, "explicacao": "", "grafico": "nenhum", "motivo_recusa": "sem dados"}))
    out = g.gerar("q", "", [])
    assert out.sql is None and out.motivo_recusa == "sem dados"


def test_claude_sem_chave_da_erro_claro():
    with pytest.raises(ErroProvedor, match="ANTHROPIC_API_KEY"):
        GeradorClaude(None, "m")


def test_claude_erro_de_rede_vira_erro_de_provedor():
    class Quebra:
        class messages:  # noqa: N801
            @staticmethod
            def create(**_):
                raise RuntimeError("sem rede")

    with pytest.raises(ErroProvedor, match="sem rede"):
        GeradorClaude(None, "m", client=Quebra()).gerar("q", "", [])


def test_claude_resposta_sem_ferramenta_e_erro():
    from types import SimpleNamespace

    cliente = SimpleNamespace(messages=SimpleNamespace(create=lambda **_: SimpleNamespace(content=[SimpleNamespace(type="text", text="oi")])))
    with pytest.raises(ErroProvedor, match="ferramenta"):
        GeradorClaude(None, "m", client=cliente).gerar("q", "", [])


def test_historico_de_autocorrecao_inclui_sql_e_erro():
    msgs = montar_mensagens("p", [Tentativa(sql="SELECT x", erro="no such column: x")])
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert "SELECT x" in msgs[1]["content"] and "no such column: x" in msgs[2]["content"]


# ------------------------------------------------------------ Analista
class Roteiro:
    nome = "teste"

    def __init__(self, *geracoes):
        self.geracoes, self.vistas = list(geracoes), []

    def gerar(self, pergunta, contexto, tentativas):
        self.vistas.append(list(tentativas))
        return self.geracoes.pop(0)


def test_resposta_normal_traz_tabela_e_grafico(executor):
    a = Analista(executor, Roteiro(Geracao(sql="SELECT status, COUNT(*) AS n FROM pedidos GROUP BY status", grafico="barra")))
    r = a.perguntar("quantos por status")
    assert r.ok and r.colunas == ["status", "n"] and len(r.linhas) == 2 and r.grafico == "barra"
    assert a.grafico_png(r).startswith(b"\x89PNG")


def test_autocorrecao_passa_o_erro_para_a_proxima_tentativa(executor):
    gerador = Roteiro(Geracao(sql="SELECT coluna_errada FROM pedidos"), Geracao(sql="SELECT COUNT(*) AS n FROM pedidos"))
    r = Analista(executor, gerador).perguntar("q")
    assert r.ok and len(r.tentativas) == 1
    assert gerador.vistas[0] == [] and "coluna_errada" in gerador.vistas[1][0].erro


def test_desiste_depois_do_limite_de_tentativas(executor):
    ruim = Geracao(sql="SELECT coluna_errada FROM pedidos")
    r = Analista(executor, Roteiro(ruim, ruim, ruim), max_tentativas=3).perguntar("q")
    assert not r.ok and "coluna_errada" in r.erro and len(r.tentativas) == 3


def test_comando_proibido_nao_e_tentado_de_novo(executor):
    gerador = Roteiro(Geracao(sql="DROP TABLE pedidos"), Geracao(sql="SELECT 1"))
    r = Analista(executor, gerador).perguntar("q")
    assert not r.ok and r.tentativas[0].tipo == "validacao" and len(gerador.geracoes) == 1  # 2ª geração nunca usada


def test_recusa_do_modelo_e_propagada(executor):
    r = Analista(executor, Roteiro(Geracao(sql=None, motivo_recusa="não há telefone"))).perguntar("telefone?")
    assert r.recusa == "não há telefone" and not r.ok and r.sql is None


def test_pergunta_vazia(executor):
    assert Analista(executor, Roteiro()).perguntar("   ").erro == "Digite uma pergunta."


def test_falha_do_provedor_vira_erro_no_resultado(executor):
    class Quebrado:
        nome = "q"

        def gerar(self, *a):
            raise ErroProvedor("API fora do ar")

    r = Analista(executor, Quebrado()).perguntar("q")
    assert r.erro == "API fora do ar" and not r.ok


def test_provedor_auto_sem_chave_usa_offline(executor, tmp_path):
    cfg = Config(db_path=tmp_path / "x.db", api_key=None, modelo="m")
    assert isinstance(criar_gerador("auto", cfg, executor), GeradorOffline)
    with pytest.raises(ValueError):
        criar_gerador("inexistente", cfg, executor)


def test_carregar_env_nao_sobrescreve(tmp_path, monkeypatch):
    arq = tmp_path / ".env"
    arq.write_text("# comentário\nANTHROPIC_API_KEY='abc'\nFOO_TESTE=\"bar\"\nJA_DEFINIDA=nova\n", encoding="utf-8")
    monkeypatch.setenv("JA_DEFINIDA", "antiga")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("FOO_TESTE", raising=False)
    carregar_env(arq)
    import os

    assert os.environ["ANTHROPIC_API_KEY"] == "abc" and os.environ["FOO_TESTE"] == "bar" and os.environ["JA_DEFINIDA"] == "antiga"


# --------------------------------------------------------- baseline offline
@pytest.mark.parametrize("pergunta,sql_ref", [
    ("Qual o faturamento por categoria de restaurante?",
     "SELECT r.categoria, ROUND(SUM(p.valor_total),2) FROM pedidos p JOIN restaurantes r USING(id_restaurante) WHERE p.status='entregue' GROUP BY 1"),
    ("Quantos pedidos foram cancelados?", "SELECT COUNT(*) FROM pedidos WHERE status='cancelado'"),
    ("Top 3 restaurantes por faturamento",
     "SELECT r.nome, ROUND(SUM(p.valor_total),2) f FROM pedidos p JOIN restaurantes r USING(id_restaurante) WHERE p.status='entregue' GROUP BY r.id_restaurante ORDER BY f DESC LIMIT 3"),
])
def test_offline_acerta_perguntas_simples(executor, pergunta, sql_ref):
    from analista_sql.avaliacao import comparar_resultados

    r = Analista(executor, GeradorOffline(carregar_catalogo(executor.meta))).perguntar(pergunta)
    assert r.ok
    ref = executor.executar(sql_ref)[2]
    assert comparar_resultados(ref, r.linhas, ordenado="Top" in pergunta)[0]


@pytest.mark.parametrize("pergunta", ["Apague a tabela pedidos", "Qual o telefone do cliente 10?", "me conta uma piada"])
def test_offline_recusa(executor, pergunta):
    assert Analista(executor, GeradorOffline(carregar_catalogo(executor.meta))).perguntar(pergunta).recusa
