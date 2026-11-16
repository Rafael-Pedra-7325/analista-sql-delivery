"""Orquestra: pergunta -> SQL (LLM ou regras) -> validação -> execução -> autocorreção -> gráfico."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from .config import Config
from .executor import Executor
from .graficos import escolher_grafico, renderizar
from .llm import GeradorClaude, GeradorSQL
from .modelos import ErroExecucao, ErroProvedor, ErroValidacao, Resultado, Tentativa
from .offline import GeradorOffline
from .schema import carregar_catalogo, montar_contexto


def criar_gerador(provedor: str, config: Config, executor: Executor) -> GeradorSQL:
    if provedor == "offline":
        return GeradorOffline(carregar_catalogo(executor.meta))
    if provedor == "claude":
        return GeradorClaude(config.api_key, config.modelo)
    if provedor == "auto":
        return GeradorClaude(config.api_key, config.modelo) if config.api_key else GeradorOffline(carregar_catalogo(executor.meta))
    raise ValueError(f"Provedor desconhecido: {provedor!r} (use auto, claude ou offline)")


def garantir_banco(config: Config) -> None:
    """Se o banco não existe, gera os dados sintéticos (determinísticos, ~1s) em vez de falhar."""
    if config.db_path.exists():
        return
    from .synthetic import gerar_banco

    print(f"Banco não encontrado em {config.db_path}; gerando dados sintéticos...", file=sys.stderr)
    gerar_banco(config.db_path)


class Analista:
    """Ponto de entrada da biblioteca. Reutilize a mesma instância entre perguntas."""

    def __init__(self, executor: Executor, gerador: GeradorSQL, max_tentativas: int = 3):
        self.executor = executor
        self.gerador = gerador
        self.max_tentativas = max_tentativas
        self.contexto = montar_contexto(executor.meta)

    @classmethod
    def criar(cls, config: Config | None = None, provedor: str = "auto") -> "Analista":
        config = config or Config.do_ambiente()
        garantir_banco(config)
        executor = Executor(config.db_path, config.max_linhas, config.timeout_s)
        return cls(executor, criar_gerador(provedor, config, executor), config.max_tentativas)

    def perguntar(self, pergunta: str) -> Resultado:
        inicio = time.perf_counter()
        res = Resultado(pergunta=pergunta, provedor=self.gerador.nome)
        pergunta = (pergunta or "").strip()
        if not pergunta:
            res.erro = "Digite uma pergunta."
            return res
        try:
            for _ in range(self.max_tentativas):
                geracao = self.gerador.gerar(pergunta, self.contexto, res.tentativas)
                res.explicacao = geracao.explicacao
                if geracao.sql is None:
                    res.recusa = geracao.motivo_recusa or "Não consegui responder a essa pergunta com os dados disponíveis."
                    break
                try:
                    res.sql, res.colunas, res.linhas, res.truncado = self.executor.executar(geracao.sql)
                    res.grafico = escolher_grafico(res.colunas, res.linhas, geracao.grafico)
                    res.erro = None
                    break
                except (ErroValidacao, ErroExecucao) as exc:
                    res.sql = geracao.sql
                    res.erro = str(exc)
                    res.tentativas.append(Tentativa(
                        sql=geracao.sql, erro=str(exc),
                        tipo="validacao" if isinstance(exc, ErroValidacao) else "execucao"))
                    if isinstance(exc, ErroValidacao):
                        break  # tentar de novo não torna um comando proibido permitido
        except ErroProvedor as exc:
            res.erro = str(exc)
        res.tempo_s = time.perf_counter() - inicio
        return res

    def grafico_png(self, res: Resultado) -> bytes | None:
        """PNG do gráfico do resultado, ou None se não houver gráfico útil."""
        if not res.ok:
            return None
        png, _ = renderizar(res.colunas, res.linhas, res.pergunta, res.grafico)
        return png

    def fechar(self) -> None:
        self.executor.fechar()


def salvar_png(png: bytes, caminho: str | Path) -> Path:
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(png)
    return caminho
