"""Gráficos automáticos para o resultado de uma consulta (matplotlib, sem estado global).

Decisões de design: uma única cor de destaque (a pergunta tem uma só medida), barras
ordenadas como vieram da consulta, grade discreta, textos em tinta neutra e rótulos de
valor apenas quando são poucos. Nunca há dois eixos Y: só a primeira medida numérica
é desenhada.
"""

from __future__ import annotations

import io
import re
import textwrap
from typing import Any, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

COR = "#D64045"
TINTA = "#1F2430"
TINTA_2 = "#5B6270"
GRADE = "#E6E8EC"
FUNDO = "#FFFFFF"
MAX_CATEGORIAS = 20

_TEMPORAL = re.compile(r"^(mes|meses|data|dia|ano|periodo|trimestre|semana|hora)$")


def _numero_br(valor: float, casas: int) -> str:
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "§").replace(".", ",").replace("§", ".")


def tipo_de_valor(coluna: str) -> str:
    c = coluna.lower()
    if re.search(r"faturamento|receita|valor|ticket|total_descontos|taxa_entrega|preco|gmv|comissao", c):
        return "moeda"
    if re.search(r"taxa_cancelamento|pct|percentual|porcentagem|perc", c):
        return "percentual"
    if re.search(r"minutos|_min$|tempo", c):
        return "minutos"
    if re.search(r"_km$|distancia", c):
        return "km"
    return "numero"


def formatar(valor: float, tipo: str, compacto: bool = False) -> str:
    if compacto and abs(valor) >= 1_000_000:
        base, sufixo = valor / 1_000_000, " mi"
    elif compacto and abs(valor) >= 10_000:
        base, sufixo = valor / 1_000, " mil"
    else:
        base, sufixo = valor, ""
    inteiro = float(base).is_integer()
    casas = 0 if inteiro else (1 if sufixo else 2)
    texto = _numero_br(base, casas) + sufixo
    return {"moeda": f"R$ {texto}", "percentual": f"{texto}%", "minutos": f"{texto} min", "km": f"{texto} km"}.get(tipo, texto)


def _e_numero(valor: Any) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)


def _humanizar(nome: str) -> str:
    texto = nome.replace("_", " ").strip()
    return texto[:1].upper() + texto[1:]


def _classificar(colunas: Sequence[str], linhas: Sequence[Sequence[Any]]) -> tuple[list[int], list[int]]:
    """Índices das colunas numéricas e das não numéricas (ignorando NULLs)."""
    numericas, texto = [], []
    for i in range(len(colunas)):
        valores = [r[i] for r in linhas if r[i] is not None]
        (numericas if valores and all(_e_numero(v) for v in valores) else texto).append(i)
    return numericas, texto


def escolher_grafico(colunas: Sequence[str], linhas: Sequence[Sequence[Any]], sugestao: str | None = None) -> str | None:
    """Devolve 'kpi' | 'barra' | 'linha' | 'dispersao' | None, combinando a sugestão com a forma dos dados."""
    if not linhas or not colunas:
        return None
    numericas, texto = _classificar(colunas, linhas)
    if len(linhas) == 1 and len(colunas) == 1 and numericas:
        return "kpi"
    if sugestao == "nenhum" or not numericas:
        return None
    x_temporal = None
    if texto:
        x_temporal = texto[0]
    elif _TEMPORAL.match(colunas[numericas[0]].lower()) and len(numericas) >= 2:
        x_temporal = numericas[0]
    if x_temporal is None:
        return "dispersao" if len(numericas) >= 2 and len(linhas) >= 3 else None
    nome_x = colunas[x_temporal].lower()
    e_serie = bool(_TEMPORAL.match(nome_x)) and nome_x != "dia_semana"
    if sugestao == "dispersao":
        sugestao = None
    if sugestao == "linha" and len(linhas) >= 2:
        return "linha"
    if sugestao == "barra":
        return "barra"
    return "linha" if e_serie and len(linhas) >= 3 else "barra"


def _estilo_eixos(ax) -> None:
    ax.set_facecolor(FUNDO)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    for lado in ("left", "bottom"):
        ax.spines[lado].set_color(GRADE)
    ax.tick_params(colors=TINTA_2, labelsize=9, length=0)
    ax.grid(True, color=GRADE, linewidth=0.8)
    ax.set_axisbelow(True)


def renderizar(colunas: Sequence[str], linhas: Sequence[Sequence[Any]], titulo: str, sugestao: str | None = None) -> tuple[bytes | None, str | None]:
    """Desenha o gráfico. Devolve (png_em_bytes, tipo_usado); (None, None) se não há gráfico útil."""
    tipo = escolher_grafico(colunas, linhas, sugestao)
    if tipo is None:
        return None, None
    numericas, texto = _classificar(colunas, linhas)
    titulo_quebrado = "\n".join(textwrap.wrap(titulo, 78)) if titulo else ""

    with matplotlib.rc_context({"font.family": "DejaVu Sans", "figure.facecolor": FUNDO}):
        if tipo == "kpi":
            tp = tipo_de_valor(colunas[0])
            fig, ax = plt.subplots(figsize=(7, 2.6))
            ax.axis("off")
            ax.text(0.5, 0.58, formatar(float(linhas[0][0]), tp), ha="center", va="center", fontsize=40,
                    fontweight="bold", color=COR, transform=ax.transAxes)
            ax.text(0.5, 0.18, _humanizar(colunas[0]), ha="center", va="center", fontsize=12, color=TINTA_2,
                    transform=ax.transAxes)
            if titulo_quebrado:
                fig.suptitle(titulo_quebrado, x=0.02, ha="left", fontsize=11, color=TINTA, fontweight="bold")
        elif tipo == "dispersao":
            xi, yi = numericas[0], numericas[1]
            fig, ax = plt.subplots(figsize=(8, 4.6))
            _estilo_eixos(ax)
            ax.scatter([r[xi] for r in linhas], [r[yi] for r in linhas], s=22, color=COR, alpha=0.75,
                       edgecolors=FUNDO, linewidths=1)
            ax.set_xlabel(_humanizar(colunas[xi]), color=TINTA_2, fontsize=10)
            ax.set_ylabel(_humanizar(colunas[yi]), color=TINTA_2, fontsize=10)
            fig.suptitle(titulo_quebrado, x=0.02, ha="left", fontsize=12, color=TINTA, fontweight="bold")
        else:
            if texto:
                xi = texto[0]
                yi = next(i for i in numericas)
            else:
                xi, yi = numericas[0], numericas[1]
            dados = [(str(r[xi]), r[yi]) for r in linhas if r[yi] is not None][:MAX_CATEGORIAS * (3 if tipo == "linha" else 1)]
            rotulos = [d[0] for d in dados]
            valores = [float(d[1]) for d in dados]
            tp = tipo_de_valor(colunas[yi])
            fig, ax = plt.subplots(figsize=(8, 4.6))
            _estilo_eixos(ax)
            fmt = FuncFormatter(lambda v, _: formatar(v, tp, compacto=True))
            mostrar_valores = len(valores) <= 15

            if tipo == "linha":
                xs = list(range(len(valores)))
                ax.plot(xs, valores, color=COR, linewidth=2, marker="o" if len(xs) <= 24 else None,
                        markersize=6, markerfacecolor=COR, markeredgecolor=FUNDO, markeredgewidth=1.5)
                ax.set_xticks(xs[:: max(1, len(xs) // 12)])
                ax.set_xticklabels(rotulos[:: max(1, len(xs) // 12)], rotation=45 if len(xs) > 8 else 0,
                                   ha="right" if len(xs) > 8 else "center")
                ax.yaxis.set_major_formatter(fmt)
                ax.grid(axis="x", visible=False)
                ax.annotate(formatar(valores[-1], tp), (xs[-1], valores[-1]), textcoords="offset points",
                            xytext=(0, 9), ha="center", fontsize=9, color=TINTA)
            else:
                dados = dados[:MAX_CATEGORIAS]
                rotulos, valores = rotulos[:MAX_CATEGORIAS], valores[:MAX_CATEGORIAS]
                horizontal = len(valores) > 7 or max(len(r) for r in rotulos) > 12
                if horizontal:
                    ys = list(range(len(valores)))
                    ax.barh(ys, valores, color=COR, height=0.62)
                    ax.set_yticks(ys)
                    ax.set_yticklabels([textwrap.shorten(r, 34, placeholder="…") for r in rotulos])
                    ax.invert_yaxis()
                    ax.xaxis.set_major_formatter(fmt)
                    ax.grid(axis="y", visible=False)
                    if mostrar_valores:
                        for y, v in zip(ys, valores):
                            ax.annotate(formatar(v, tp), (v, y), textcoords="offset points", xytext=(4, 0),
                                        va="center", fontsize=8.5, color=TINTA)
                        ax.margins(x=0.14)
                else:
                    xs = list(range(len(valores)))
                    ax.bar(xs, valores, color=COR, width=0.6)
                    ax.set_xticks(xs)
                    ax.set_xticklabels(rotulos)
                    ax.yaxis.set_major_formatter(fmt)
                    ax.grid(axis="x", visible=False)
                    if mostrar_valores:
                        for x, v in zip(xs, valores):
                            ax.annotate(formatar(v, tp), (x, v), textcoords="offset points", xytext=(0, 4),
                                        ha="center", fontsize=8.5, color=TINTA)
                        ax.margins(y=0.12)
            ax.set_xlabel("" if tipo != "dispersao" else "")
            fig.suptitle(titulo_quebrado, x=0.02, ha="left", fontsize=12, color=TINTA, fontweight="bold")
            ax.text(0.0, 1.01, _humanizar(colunas[yi]), transform=ax.transAxes, fontsize=9, color=TINTA_2)

        fig.tight_layout(rect=(0, 0, 1, 0.93))
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png", dpi=150, facecolor=FUNDO)
        plt.close(fig)
    return buffer.getvalue(), tipo
