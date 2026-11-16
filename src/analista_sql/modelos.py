"""Estruturas de dados e exceções compartilhadas pelo pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ErroValidacao(Exception):
    """A consulta foi barrada antes (ou durante) a execução por violar as regras de segurança."""


class ErroExecucao(Exception):
    """A consulta é permitida, mas falhou ao rodar (coluna inexistente, timeout, etc.)."""


class ErroProvedor(Exception):
    """Falha ao falar com o provedor de LLM (chave ausente, rede, limite de uso)."""


@dataclass
class Geracao:
    """O que o gerador (Claude ou baseline offline) devolve para uma pergunta."""

    sql: str | None
    explicacao: str = ""
    grafico: str | None = None  # 'barra' | 'linha' | 'dispersao' | 'nenhum' | None (automático)
    motivo_recusa: str | None = None


@dataclass
class Tentativa:
    """Uma tentativa de SQL que falhou; alimenta a autocorreção."""

    sql: str
    erro: str
    tipo: str = "execucao"  # "validacao" (barrado pela segurança) ou "execucao" (falhou ao rodar)


@dataclass
class Resultado:
    pergunta: str
    sql: str | None = None
    explicacao: str = ""
    colunas: list[str] = field(default_factory=list)
    linhas: list[tuple[Any, ...]] = field(default_factory=list)
    truncado: bool = False
    grafico: str | None = None
    recusa: str | None = None
    erro: str | None = None
    tentativas: list[Tentativa] = field(default_factory=list)
    tempo_s: float = 0.0
    provedor: str = ""

    @property
    def ok(self) -> bool:
        return self.erro is None and self.recusa is None and self.sql is not None
