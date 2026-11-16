"""Execução segura de SQL no SQLite: somente leitura, com authorizer, timeout e limite de linhas."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from .modelos import ErroExecucao, ErroValidacao
from .validador import validar_sql

_ACOES_PERMITIDAS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, getattr(sqlite3, "SQLITE_RECURSIVE", 33)}
_FUNCOES_PROIBIDAS = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer", "zeroblob", "randomblob"}


def conectar_leitura(caminho: str | Path) -> sqlite3.Connection:
    """Abre o banco em modo somente leitura (falha se o arquivo não existir)."""
    caminho = Path(caminho).resolve()
    if not caminho.exists():
        raise FileNotFoundError(
            f"Banco não encontrado em {caminho}. Gere-o com: analista-sql gerar-dados"
        )
    return sqlite3.connect(f"{caminho.as_uri()}?mode=ro", uri=True, check_same_thread=False)


def _authorizer(acao: int, arg1: Any, arg2: Any, db: Any, origem: Any) -> int:
    if acao not in _ACOES_PERMITIDAS:
        return sqlite3.SQLITE_DENY
    if acao == sqlite3.SQLITE_READ and arg1 and str(arg1).lower().startswith("sqlite_"):
        return sqlite3.SQLITE_DENY  # não expõe o catálogo interno
    if acao == sqlite3.SQLITE_FUNCTION and arg2 and str(arg2).lower() in _FUNCOES_PROIBIDAS:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


class Executor:
    """Executa consultas já validadas. Uma instância pode ser reutilizada entre perguntas."""

    def __init__(self, caminho_db: str | Path, max_linhas: int = 1000, timeout_s: float = 10.0):
        # `meta`: leitura do esquema/catálogo pelo próprio sistema (nunca recebe SQL de usuário).
        self.meta = conectar_leitura(caminho_db)
        # `conn`: único caminho para SQL vindo do modelo/usuário, travado pelo authorizer.
        self.conn = conectar_leitura(caminho_db)
        self.conn.set_authorizer(_authorizer)
        self.max_linhas = max_linhas
        self.timeout_s = timeout_s

    def fechar(self) -> None:
        self.conn.close()
        self.meta.close()

    def executar(self, sql: str) -> tuple[str, list[str], list[tuple], bool]:
        """Valida e roda o SQL. Devolve (sql_limpo, colunas, linhas, truncado)."""
        limpo = validar_sql(sql)
        limite = time.monotonic() + self.timeout_s
        self.conn.set_progress_handler(lambda: 1 if time.monotonic() > limite else 0, 10_000)
        try:
            cur = self.conn.execute(limpo)
            colunas = [d[0] for d in cur.description or []]
            linhas = cur.fetchmany(self.max_linhas + 1)
        except sqlite3.DatabaseError as exc:
            msg = str(exc)
            if "not authorized" in msg or "authoriz" in msg or "prohibited" in msg:
                raise ErroValidacao("Operação não autorizada (o banco é somente leitura).") from exc
            if "interrupted" in msg:
                raise ErroExecucao(f"A consulta excedeu o tempo limite de {self.timeout_s:g}s.") from exc
            raise ErroExecucao(msg) from exc
        except sqlite3.Warning as exc:  # mais de uma instrução
            raise ErroValidacao(str(exc)) from exc
        finally:
            self.conn.set_progress_handler(None, 0)
        truncado = len(linhas) > self.max_linhas
        return limpo, colunas, [tuple(r) for r in linhas[: self.max_linhas]], truncado
