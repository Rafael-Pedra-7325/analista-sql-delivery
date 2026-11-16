"""Linha de comando: gerar-dados | perguntar | avaliar | web."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import Config
from .modelos import ErroProvedor


def _tabela_texto(colunas: list[str], linhas: list[tuple], maximo: int = 25) -> str:
    def fmt(v) -> str:
        if v is None:
            return "-"
        return f"{v:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".") if isinstance(v, float) else str(v)

    corpo = [[fmt(v) for v in linha] for linha in linhas[:maximo]]
    larguras = [max(len(c), *(len(r[i]) for r in corpo)) if corpo else len(c) for i, c in enumerate(colunas)]
    linha_sep = "-+-".join("-" * w for w in larguras)
    saida = [" | ".join(c.ljust(w) for c, w in zip(colunas, larguras)), linha_sep]
    saida += [" | ".join(v.rjust(w) if v.replace(".", "").replace(",", "").replace("-", "").isdigit() else v.ljust(w)
                         for v, w in zip(r, larguras)) for r in corpo]
    if len(linhas) > maximo:
        saida.append(f"... (+{len(linhas) - maximo} linhas)")
    return "\n".join(saida)


def cmd_gerar_dados(args: argparse.Namespace) -> int:
    from .synthetic import gerar_banco

    config = Config.do_ambiente()
    destino = Path(args.saida) if args.saida else config.db_path
    contagens = gerar_banco(destino, semente=args.semente, escala=args.escala)
    print(f"Banco criado em {destino}")
    for tabela, n in contagens.items():
        print(f"  {tabela:<14} {n:>8,}".replace(",", "."))
    return 0


def cmd_perguntar(args: argparse.Namespace) -> int:
    from .pipeline import Analista, salvar_png

    config = Config.do_ambiente()
    try:
        analista = Analista.criar(config, args.provedor)
    except (ErroProvedor, FileNotFoundError, ValueError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
    try:
        res = analista.perguntar(" ".join(args.pergunta))
        print(f"Provedor: {res.provedor}  ({res.tempo_s:.2f}s)")
        if res.recusa:
            print(f"\nNão respondi: {res.recusa}")
            return 1
        if res.sql:
            print(f"\nSQL:\n{res.sql}")
        if res.erro:
            print(f"\nErro: {res.erro}", file=sys.stderr)
            return 1
        if res.explicacao:
            print(f"\n{res.explicacao}")
        print(f"\n{_tabela_texto(res.colunas, res.linhas)}")
        if res.truncado:
            print(f"(resultado limitado a {config.max_linhas} linhas)")
        if args.grafico:
            png = analista.grafico_png(res)
            if png:
                print(f"\nGráfico salvo em {salvar_png(png, args.grafico)}")
            else:
                print("\nEste resultado não tem um gráfico útil (ex.: sem coluna numérica).")
        return 0
    finally:
        analista.fechar()


def cmd_avaliar(args: argparse.Namespace) -> int:
    from .avaliacao import main_avaliar

    return main_avaliar(args)


def cmd_web(args: argparse.Namespace) -> int:
    from .web import servir

    servir(args.host, args.porta, args.provedor)
    return 0


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="analista-sql", description="Pergunte em português, receba SQL validado, tabela e gráfico.")
    sub = p.add_subparsers(dest="comando", required=True)

    g = sub.add_parser("gerar-dados", help="cria o banco SQLite sintético de delivery")
    g.add_argument("--saida", help="caminho do .db (padrão: data/delivery.db)")
    g.add_argument("--semente", type=int, default=42)
    g.add_argument("--escala", type=float, default=1.0, help="multiplica o volume de pedidos (padrão 1.0 ≈ 30 mil)")
    g.set_defaults(func=cmd_gerar_dados)

    q = sub.add_parser("perguntar", help="faz uma pergunta em português")
    q.add_argument("pergunta", nargs="+")
    q.add_argument("--provedor", choices=["auto", "claude", "offline"], default="auto")
    q.add_argument("--grafico", metavar="ARQUIVO.png", help="salva o gráfico neste arquivo")
    q.set_defaults(func=cmd_perguntar)

    a = sub.add_parser("avaliar", help="mede a acurácia por execução no conjunto de avaliação")
    a.add_argument("--provedor", choices=["auto", "claude", "offline"], default="auto")
    a.add_argument("--casos", default=None, help="arquivo JSON de casos (padrão: evals/casos.json)")
    a.add_argument("--saida", default="evals/relatorio.md", help="relatório em Markdown")
    a.add_argument("--json", default="evals/ultimo_resultado.json", help="resultado detalhado em JSON")
    a.add_argument("--filtro", help="roda só os casos cujo id contém este texto")
    a.set_defaults(func=cmd_avaliar)

    w = sub.add_parser("web", help="abre a interface web local")
    w.add_argument("--host", default="127.0.0.1")
    w.add_argument("--porta", type=int, default=8000)
    w.add_argument("--provedor", choices=["auto", "claude", "offline"], default="auto")
    w.set_defaults(func=cmd_web)
    return p


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
