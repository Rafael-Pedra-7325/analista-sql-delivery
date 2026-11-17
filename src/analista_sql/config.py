"""Configuração via variáveis de ambiente e arquivo .env (sem dependências externas)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
MODELO_PADRAO = "grok-3"


def carregar_env(caminho: Path | None = None) -> None:
    """Lê um .env simples (CHAVE=valor) sem sobrescrever variáveis já definidas."""
    candidatos = [caminho] if caminho is not None else [Path.cwd() / ".env", RAIZ / ".env"]
    alvo = next((p for p in candidatos if p and p.is_file()), None)
    if alvo is None:
        return
    for linha in alvo.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        os.environ.setdefault(chave.strip(), valor.strip().strip("'\""))


def _db_padrao() -> Path:
    base = RAIZ if (RAIZ / "pyproject.toml").is_file() else Path.cwd()
    return base / "data" / "delivery.db"


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
        db_env = os.environ.get("DELIVERY_DB")
        db = Path(db_env) if db_env else _db_padrao()
        return cls(
            db_path=db,
            api_key=os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY"),
            modelo=os.environ.get("ANALISTA_MODELO", MODELO_PADRAO),
        )
