import sqlite3

import pytest

from analista_sql.executor import Executor, conectar_leitura
from analista_sql.modelos import ErroExecucao, ErroValidacao
from analista_sql.validador import validar_sql


@pytest.mark.parametrize("sql", [
    "SELECT 1",
    "select count(*) from pedidos;",
    "WITH x AS (SELECT 1 AS a) SELECT a FROM x",
    "-- comentário\nSELECT 1",
    "SELECT 'delete from pedidos' AS texto",
    'SELECT 1 AS "drop"',
    "SELECT /* update */ 1",
    "SELECT * FROM pedidos WHERE status = 'entregue';;",
])
def test_aceita_consultas_somente_leitura(sql):
    assert validar_sql(sql)


@pytest.mark.parametrize("sql", [
    "",
    "   ",
    "DELETE FROM pedidos",
    "DROP TABLE pedidos",
    "UPDATE pedidos SET status = 'x'",
    "INSERT INTO clientes VALUES (1)",
    "PRAGMA table_info(pedidos)",
    "ATTACH DATABASE 'x.db' AS x",
    "SELECT 1; DROP TABLE pedidos",
    "SELECT 1; SELECT 2",
    "WITH x AS (SELECT 1) DELETE FROM pedidos",
    "SELECT load_extension('evil')",
    "SELECT 'aberta",
    "/* nao fecha SELECT 1",
    "VACUUM",
    "CREATE TABLE t (a INT)",
])
def test_bloqueia_comandos_perigosos(sql):
    with pytest.raises(ErroValidacao):
        validar_sql(sql)


def test_comentario_nao_esconde_comando():
    with pytest.raises(ErroValidacao):
        validar_sql("SELECT 1 /* oculto */ ; /* */ DROP TABLE pedidos")


def test_validacao_remove_comentarios_e_ponto_e_virgula():
    assert validar_sql("SELECT 1 -- fim\n;") == "SELECT 1"


def test_banco_abre_somente_leitura(db_path):
    conn = conectar_leitura(db_path)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM pedidos")


def test_arquivo_inexistente_da_erro_claro(tmp_path):
    with pytest.raises(FileNotFoundError, match="gerar-dados"):
        conectar_leitura(tmp_path / "nao_existe.db")


def test_authorizer_barra_catalogo_interno(executor):
    with pytest.raises(ErroValidacao):
        executor.executar("SELECT * FROM sqlite_master")


def test_erro_de_coluna_vira_erro_de_execucao(executor):
    with pytest.raises(ErroExecucao, match="no such column"):
        executor.executar("SELECT coluna_que_nao_existe FROM pedidos")


def test_timeout_interrompe_consulta_pesada(db_path):
    ex = Executor(db_path, timeout_s=0.3)
    try:
        with pytest.raises(ErroExecucao, match="tempo limite"):
            ex.executar("WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT COUNT(*) FROM c")
    finally:
        ex.fechar()


def test_resultado_grande_e_truncado(db_path):
    ex = Executor(db_path, max_linhas=10)
    try:
        _, _, linhas, truncado = ex.executar("SELECT id_pedido FROM pedidos")
        assert len(linhas) == 10 and truncado
        _, _, linhas, truncado = ex.executar("SELECT id_pedido FROM pedidos LIMIT 5")
        assert len(linhas) == 5 and not truncado
    finally:
        ex.fechar()


def test_dados_nao_mudam_depois_de_tentativas_de_escrita(executor):
    antes = executor.executar("SELECT COUNT(*) FROM pedidos")[2]
    for sql in ("DELETE FROM pedidos", "SELECT 1; DELETE FROM pedidos"):
        with pytest.raises(ErroValidacao):
            executor.executar(sql)
    assert executor.executar("SELECT COUNT(*) FROM pedidos")[2] == antes
