"""Avaliação por execução (execution accuracy).

Em vez de comparar o texto do SQL (duas consultas muito diferentes podem responder igual,
e uma consulta quase idêntica pode responder errado), executamos a consulta de referência e
a consulta gerada no mesmo banco e comparamos os *resultados*:

* nomes de colunas e ordem das colunas não importam (tentamos as permutações);
* a ordem das linhas só importa quando o caso é marcado como `ordenado` (rankings / top N);
* números são comparados com tolerância de 0,011 (arredondamentos de 2 casas);
* colunas a mais ou a menos, ou linhas a mais ou a menos, contam como erro.

Casos de recusa (`sql_ref = null`) acertam quando o sistema recusa ou o SQL é barrado pela
camada de segurança; erram se ele devolve dados.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from itertools import permutations
from pathlib import Path
from typing import Any, Sequence

from .config import RAIZ, Config
from .modelos import ErroProvedor, Resultado
from .pipeline import Analista

TOLERANCIA = 0.011
MAX_COLUNAS_PERMUTADAS = 6
NIVEIS = ["facil", "medio", "dificil", "recusa"]
NOMES_NIVEL = {"facil": "Fácil", "medio": "Médio", "dificil": "Difícil", "recusa": "Recusa (não deve responder)"}


# ---------------------------------------------------------------- comparação
def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _chave(linha: Sequence[Any]) -> tuple:
    partes = []
    for v in linha:
        if v is None:
            partes.append((0, 0.0, ""))
        elif _num(v):
            partes.append((1, round(float(v), 2), ""))
        else:
            partes.append((2, 0.0, str(v).strip()))
    return tuple(partes)


def _valor_igual(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if _num(a) and _num(b):
        return abs(float(a) - float(b)) <= max(TOLERANCIA, 1e-9 * abs(float(a)))
    return str(a).strip() == str(b).strip()


def _linhas_iguais(a: Sequence[Sequence[Any]], b: Sequence[Sequence[Any]]) -> bool:
    return all(_valor_igual(x, y) for la, lb in zip(a, b) for x, y in zip(la, lb))


def comparar_resultados(ref: Sequence[Sequence[Any]], pred: Sequence[Sequence[Any]], ordenado: bool = False) -> tuple[bool, str]:
    """Devolve (iguais, motivo). `motivo` é vazio quando iguais."""
    if len(ref) != len(pred):
        return False, f"número de linhas diferente (esperado {len(ref)}, obtido {len(pred)})"
    if not ref:
        return True, ""
    n_ref, n_pred = len(ref[0]), len(pred[0])
    if n_ref != n_pred:
        return False, f"número de colunas diferente (esperado {n_ref}, obtido {n_pred})"

    base_ref = list(ref) if ordenado else sorted(ref, key=_chave)
    ordens = permutations(range(n_pred)) if n_pred <= MAX_COLUNAS_PERMUTADAS else [tuple(range(n_pred))]
    for ordem in ordens:
        reordenado = [tuple(linha[i] for i in ordem) for linha in pred]
        if not ordenado:
            reordenado.sort(key=_chave)
        if _linhas_iguais(base_ref, reordenado):
            return True, ""
    return False, "valores diferentes do esperado"


# ----------------------------------------------------------------- execução
def carregar_casos(caminho: Path) -> list[dict]:
    casos = json.loads(caminho.read_text(encoding="utf-8"))
    ids = [c["id"] for c in casos]
    if len(ids) != len(set(ids)):
        raise ValueError("ids duplicados em " + str(caminho))
    return casos


def _status_recusa(res: Resultado) -> tuple[str, bool, str]:
    """Classifica a resposta a uma pergunta que NÃO deveria ser respondida."""
    if res.recusa:
        return "recusa_correta", True, res.recusa
    if res.erro and any(t.tipo == "validacao" for t in res.tentativas):
        return "recusa_correta", True, f"bloqueado pela validação: {res.erro}"
    if res.erro and not res.sql:
        return "erro_provedor", False, res.erro
    return "respondeu_indevidamente", False, "devolveu dados para uma pergunta que deveria ser recusada"


def avaliar_caso(analista: Analista, caso: dict) -> dict:
    res = analista.perguntar(caso["pergunta"])
    base = {
        "id": caso["id"], "nivel": caso["nivel"], "pergunta": caso["pergunta"],
        "sql_gerado": res.sql, "falhas_antes": len(res.tentativas),
        "tempo_s": round(res.tempo_s, 2),
    }
    if caso["sql_ref"] is None:
        status, correto, motivo = _status_recusa(res)
        return {**base, "status": status, "correto": correto, "motivo": motivo, "executou": res.ok}

    if res.recusa:
        return {**base, "status": "recusa_indevida", "correto": False, "motivo": res.recusa, "executou": False}
    if not res.ok:
        status = "erro_provedor" if res.sql is None else "erro_execucao"
        return {**base, "status": status, "correto": False, "motivo": res.erro or "sem SQL", "executou": False}

    _, _, ref_linhas, _ = analista.executor.executar(caso["sql_ref"])
    iguais, motivo = comparar_resultados(ref_linhas, res.linhas, caso.get("ordenado", False))
    return {**base, "status": "correto" if iguais else "resultado_errado", "correto": iguais, "motivo": motivo, "executou": True}


def avaliar(analista: Analista, casos: list[dict], verboso: bool = True) -> list[dict]:
    resultados = []
    for i, caso in enumerate(casos, 1):
        r = avaliar_caso(analista, caso)
        resultados.append(r)
        if verboso:
            marca = "OK " if r["correto"] else "ERR"
            print(f"[{i:>2}/{len(casos)}] {marca} {r['id']:<4} {r['status']:<24} {caso['pergunta']}", flush=True)
    return resultados


# ------------------------------------------------------------------ métricas
def _pct(n: int, d: int) -> str:
    return f"{100 * n / d:.1f}%" if d else "n/d"


def resumir(resultados: list[dict]) -> dict:
    resp = [r for r in resultados if r["nivel"] != "recusa"]
    rec = [r for r in resultados if r["nivel"] == "recusa"]
    por_nivel = {}
    for nivel in NIVEIS:
        grupo = [r for r in resultados if r["nivel"] == nivel]
        if grupo:
            por_nivel[nivel] = {"total": len(grupo), "corretos": sum(r["correto"] for r in grupo)}
    return {
        "total": len(resultados),
        "corretos": sum(r["correto"] for r in resultados),
        "respondiveis": len(resp),
        "acuracia_execucao": sum(r["correto"] for r in resp) / len(resp) if resp else None,
        "sql_executavel": sum(r["executou"] for r in resp) / len(resp) if resp else None,
        "recusas": len(rec),
        "recusa_correta": sum(r["correto"] for r in rec) / len(rec) if rec else None,
        "autocorrigidos": sum(1 for r in resp if r["correto"] and r["falhas_antes"] > 0),
        "tempo_medio_s": sum(r["tempo_s"] for r in resultados) / len(resultados) if resultados else 0.0,
        "por_nivel": por_nivel,
        "status": dict(Counter(r["status"] for r in resultados)),
    }


def _fmt(v: float | None) -> str:
    return "n/d" if v is None else f"{100 * v:.1f}%"


def gerar_relatorio(resultados: list[dict], provedor: str, banco: str) -> str:
    s = resumir(resultados)
    linhas = [
        "# Relatório de avaliação — acurácia por execução",
        "",
        f"- Provedor: `{provedor}`",
        f"- Data: {date.today().isoformat()}",
        f"- Banco: `{banco}` (dados sintéticos)",
        f"- Casos: {s['total']} ({s['respondiveis']} respondíveis + {s['recusas']} que devem ser recusados)",
        "",
        "## Resumo",
        "",
        "| Métrica | Resultado |",
        "|---|---|",
        f"| **Acurácia por execução** (casos respondíveis) | **{_fmt(s['acuracia_execucao'])}** |",
        f"| SQL executável sem erro | {_fmt(s['sql_executavel'])} |",
        f"| Recusas corretas (escrita, dado inexistente, previsão) | {_fmt(s['recusa_correta'])} |",
        f"| Acertos que dependeram de autocorreção | {s['autocorrigidos']} |",
        f"| Tempo médio por pergunta | {s['tempo_medio_s']:.2f}s |",
        "",
        "## Por nível de dificuldade",
        "",
        "| Nível | Acertos | Total | Taxa |",
        "|---|---:|---:|---:|",
    ]
    for nivel, d in s["por_nivel"].items():
        linhas.append(f"| {NOMES_NIVEL[nivel]} | {d['corretos']} | {d['total']} | {_pct(d['corretos'], d['total'])} |")

    erros = [r for r in resultados if not r["correto"]]
    linhas += ["", "## Casos com erro", ""]
    if not erros:
        linhas.append("Nenhum.")
    for r in erros:
        linhas += [f"### {r['id']} — {r['pergunta']}", "", f"- Situação: `{r['status']}` — {r['motivo']}"]
        if r["sql_gerado"]:
            linhas += ["- SQL gerado:", "", "```sql", r["sql_gerado"], "```"]
        linhas.append("")
    linhas += [
        "## Como ler",
        "",
        "A acurácia compara o **resultado da execução** da consulta gerada com o da consulta de referência "
        "(`evals/casos.json`), ignorando nomes e ordem das colunas e, em perguntas sem ranking, a ordem das linhas. "
        "Colunas ou linhas a mais contam como erro. Números têm tolerância de 0,011. "
        "Detalhes em `src/analista_sql/avaliacao.py`.",
        "",
    ]
    return "\n".join(linhas)


# ----------------------------------------------------------------------- CLI
def main_avaliar(args: argparse.Namespace) -> int:
    config = Config.do_ambiente()
    caminho = Path(args.casos) if args.casos else RAIZ / "evals" / "casos.json"
    casos = carregar_casos(caminho)
    if args.filtro:
        casos = [c for c in casos if args.filtro in c["id"]]
        if not casos:
            print(f"Nenhum caso com id contendo {args.filtro!r}.", file=sys.stderr)
            return 2
    try:
        analista = Analista.criar(config, args.provedor)
    except (ErroProvedor, FileNotFoundError, ValueError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
    try:
        resultados = avaliar(analista, casos)
    finally:
        analista.fechar()

    s = resumir(resultados)
    relatorio = gerar_relatorio(resultados, analista.gerador.nome, str(config.db_path.name))
    for destino, conteudo in ((args.saida, relatorio), (args.json, json.dumps({"provedor": analista.gerador.nome, "resumo": s, "casos": resultados}, ensure_ascii=False, indent=2))):
        if destino:
            Path(destino).parent.mkdir(parents=True, exist_ok=True)
            Path(destino).write_text(conteudo, encoding="utf-8")
    print(f"\nAcurácia por execução: {_fmt(s['acuracia_execucao'])}  |  SQL executável: {_fmt(s['sql_executavel'])}  |  "
          f"Recusas corretas: {_fmt(s['recusa_correta'])}")
    if args.saida:
        print(f"Relatório em {args.saida}")
    return 0
