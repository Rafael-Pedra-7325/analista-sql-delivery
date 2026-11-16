"""Configuração via variáveis de ambiente e arquivo .env (sem dependências externas)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
MODELO_PADRAO = "claude-sonnet-5-5"


def carregar_env(caminho: Path | None = None) -> None:
    """Lê um .env simples (CHAVE=valor) sem sobrescrever variáveis já definidas."""
    caminho = caminho or RAIZ / ".env"
    if not caminho.is_file():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        os.environ.setdefault(chave.strip(), valor.strip().strip("'\""))


@dataclass
class Config:
    db_path: Path
    api_key: str | None
    modelo: str
    max_linhas: int = 1000
    timeout_s: float = 10.0
    max_tentativas: int = 3  # 1 geração + até 2 autocorreções

    @classmethod
    def do_ambiente(cls) -> "Config":
        carregar_env()
        db = Path(os.environ.get("DELIVERY_DB", RAIZ / "data" / "delivery.db"))
        return cls(
            db_path=db,
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
            modelo=os.environ.get("ANALISTA_MODELO", MODELO_PADRAO),
        )
