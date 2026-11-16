"""Validação estática de SQL: só leitura, uma única instrução.

Esta é a primeira de três camadas de defesa. As outras duas ficam em `executor.py`:
conexão SQLite aberta em modo somente leitura e um *authorizer* que nega qualquer
operação que não seja SELECT/READ/FUNCTION. Assim, um SQL malicioso (ou uma alucinação
do modelo) precisa passar pelas três para causar dano.
"""

from __future__ import annotations

import re

from .modelos import ErroValidacao

PALAVRAS_PROIBIDAS = {
    "insert", "update", "delete", "drop", "alter", "create", "replace", "attach", "detach",
    "pragma", "vacuum", "reindex", "analyze", "begin", "commit", "rollback", "savepoint",
    "release", "truncate", "merge", "grant", "revoke", "load_extension",
}

_IDENT = re.compile(r"[a-z_][a-z0-9_]*")


def _varrer(sql: str) -> tuple[str, str]:
    """Percorre o SQL e devolve (sql_sem_comentarios, esqueleto).

    O esqueleto troca o conteúdo de strings e identificadores entre aspas por espaços,
    para a análise de palavras-chave não confundir `'delete'` (texto) com DELETE (comando).
    """
    limpo: list[str] = []
    esqueleto: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if c == "-" and sql.startswith("--", i):
            fim = sql.find("\n", i)
            i = n if fim == -1 else fim
            limpo.append(" ")
            esqueleto.append(" ")
        elif c == "/" and sql.startswith("/*", i):
            fim = sql.find("*/", i + 2)
            if fim == -1:
                raise ErroValidacao("Comentário de bloco não fechado.")
            i = fim + 2
            limpo.append(" ")
            esqueleto.append(" ")
        elif c in ("'", '"', "`", "["):
            fecha = "]" if c == "[" else c
            j = i + 1
            while True:
                if j >= n:
                    raise ErroValidacao("Aspas ou colchetes não fechados.")
                if sql[j] == fecha:
                    if fecha != "]" and j + 1 < n and sql[j + 1] == fecha:  # aspas escapadas ('' ou "")
                        j += 2
                        continue
                    break
                j += 1
            limpo.append(sql[i : j + 1])
            esqueleto.append(c + " " * (j - i - 1) + fecha)
            i = j + 1
        else:
            limpo.append(c)
            esqueleto.append(c)
            i += 1
    return "".join(limpo), "".join(esqueleto)


def validar_sql(sql: str) -> str:
    """Valida o SQL e devolve a versão limpa (sem comentários nem `;` final).

    Levanta `ErroValidacao` se a consulta não for um único SELECT/WITH somente leitura.
    """
    if not sql or not sql.strip():
        raise ErroValidacao("SQL vazio.")
    limpo, esqueleto = _varrer(sql)
    limpo = limpo.strip()
    esqueleto = esqueleto.strip()
    while esqueleto.endswith(";"):
        esqueleto = esqueleto[:-1].rstrip()
        limpo = limpo[:-1].rstrip()
    if not limpo:
        raise ErroValidacao("SQL vazio.")
    if ";" in esqueleto:
        raise ErroValidacao("Só é permitida uma instrução por consulta.")

    palavras = _IDENT.findall(esqueleto.lower())
    if not palavras or palavras[0] not in ("select", "with"):
        raise ErroValidacao("Só consultas SELECT (ou WITH ... SELECT) são permitidas.")
    proibidas = sorted(set(palavras) & PALAVRAS_PROIBIDAS)
    if proibidas:
        raise ErroValidacao(f"Comando não permitido (somente leitura): {', '.join(proibidas).upper()}.")
    return limpo
