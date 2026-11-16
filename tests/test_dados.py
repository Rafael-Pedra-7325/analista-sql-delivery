import hashlib
import sqlite3

from analista_sql.schema import carregar_catalogo, montar_contexto
from analista_sql.synthetic import gerar_banco


def _consultar(db_path, sql):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def _impressao_digital(caminho) -> str:
    conn = sqlite3.connect(caminho)
    try:
        h = hashlib.sha256()
        for tabela in ("restaurantes", "clientes", "entregadores", "pedidos", "itens_pedido", "avaliacoes"):
            for linha in conn.execute(f"SELECT * FROM {tabela} ORDER BY 1"):
                h.update(repr(linha).encode())
        return h.hexdigest()
    finally:
        conn.close()


def test_mesma_semente_gera_mesmos_dados(tmp_path):
    a, b = tmp_path / "a.db", tmp_path / "b.db"
    gerar_banco(a, semente=3, escala=0.1)
    gerar_banco(b, semente=3, escala=0.1)
    assert _impressao_digital(a) == _impressao_digital(b)


def test_semente_diferente_gera_dados_diferentes(tmp_path):
    a, b = tmp_path / "a.db", tmp_path / "b.db"
    gerar_banco(a, semente=3, escala=0.1)
    gerar_banco(b, semente=4, escala=0.1)
    assert _impressao_digital(a) != _impressao_digital(b)


def test_integridade_referencial(db_path):
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def test_valor_total_bate_com_componentes(db_path):
    erros = _consultar(db_path, """
        SELECT COUNT(*) FROM pedidos
        WHERE ABS(valor_total - MAX(0, valor_itens + taxa_entrega - desconto)) > 0.011
    """)[0][0]
    assert erros == 0


def test_valor_itens_bate_com_soma_dos_itens(db_path):
    erros = _consultar(db_path, """
        SELECT COUNT(*) FROM pedidos p
        JOIN (SELECT id_pedido, SUM(quantidade * preco_unitario) AS s FROM itens_pedido GROUP BY 1) i USING (id_pedido)
        WHERE ABS(p.valor_itens - i.s) > 0.011
    """)[0][0]
    assert erros == 0


def test_regras_de_status(db_path):
    assert _consultar(db_path, "SELECT COUNT(*) FROM pedidos WHERE status='cancelado' AND tempo_entrega_min IS NOT NULL")[0][0] == 0
    assert _consultar(db_path, "SELECT COUNT(*) FROM pedidos WHERE status='entregue' AND tempo_entrega_min IS NULL")[0][0] == 0
    assert _consultar(db_path, "SELECT COUNT(*) FROM pedidos WHERE status='entregue' AND motivo_cancelamento IS NOT NULL")[0][0] == 0
    assert _consultar(db_path, "SELECT COUNT(*) FROM pedidos WHERE status='cancelado' AND motivo_cancelamento IS NULL")[0][0] == 0


def test_avaliacao_so_de_pedido_entregue(db_path):
    assert _consultar(db_path, "SELECT COUNT(*) FROM avaliacoes a JOIN pedidos p USING (id_pedido) WHERE p.status <> 'entregue'")[0][0] == 0


def test_pedidos_so_depois_do_cadastro_do_cliente(db_path):
    assert _consultar(db_path, "SELECT COUNT(*) FROM pedidos p JOIN clientes c USING (id_cliente) WHERE substr(p.data_pedido, 1, 10) < c.data_cadastro")[0][0] == 0


def test_periodo_e_2025(db_path):
    menor, maior = _consultar(db_path, "SELECT MIN(data_pedido), MAX(data_pedido) FROM pedidos")[0]
    assert menor.startswith("2025-01-01") or menor.startswith("2025-01-0")
    assert maior.startswith("2025-12-")


def test_nao_ha_dados_pessoais_reais(db_path):
    colunas = {r[1] for t in ("clientes", "entregadores") for r in _consultar(db_path, f"PRAGMA table_info({t})")}
    assert not colunas & {"nome", "cpf", "telefone", "email", "endereco"}


def test_contexto_para_o_llm_tem_o_essencial(executor):
    ctx = montar_contexto(executor.meta)
    for trecho in ("TABELA pedidos", "[FK -> restaurantes.id_restaurante]", "Pix", "Pizza", "Regras de negócio", "Convenções da resposta"):
        assert trecho in ctx
    catalogo = carregar_catalogo(executor.meta)
    assert "São Paulo" in catalogo["restaurantes.cidade"]
    assert set(catalogo["pedidos.status"]) == {"cancelado", "entregue"}
