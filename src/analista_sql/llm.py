"""Camada de LLM: traduz pergunta em linguagem natural para SQL via Claude (Anthropic API).

Usa tool use forçado (`tool_choice={"type": "tool", "name": "gerar_sql"}`) para garantir
resposta estruturada com SQL, explicação curta e sugestão de gráfico.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .config import Config

FERRAMENTA = {
    "name": "gerar_sql",
    "description": (
        "Gera uma única consulta SELECT em SQLite para responder à pergunta de negócio. "
        "Nunca usa comandos de escrita nem multi-statements."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": "Consulta SELECT SQLite completa, válida e somente leitura.",
            },
            "explicacao": {
                "type": "string",
                "description": "Resumo em 1 frase (português) do que a consulta calcula.",
            },
            "grafico": {
                "type": "string",
                "enum": ["nenhum", "barra", "linha"],
                "description": (
                    "Tipo de visualização sugerida: 'linha' para séries temporais, "
                    "'barra' para categorias/rankings, 'nenhum' para valor único ou tabela."
                ),
            },
        },
        "required": ["sql", "explicacao", "grafico"],
    },
}

SYSTEM_PROMPT = """Você é um analista de dados sênior especializado em SQLite.
Converta a pergunta do usuário em UMA única consulta SELECT para o banco descrito abaixo.

Regras obrigatórias:
- Gere APENAS SELECT (ou WITH ... SELECT). Nunca use INSERT, UPDATE, DELETE, DROP, ALTER, PRAGMA ou ATTACH.
- Use somente as tabelas e colunas documentadas no schema.
- Em SQLite, para datas use strftime('%Y-%m', coluna) ou date(coluna).
- Prefira nomes de colunas claros em português (ex.: total_pedidos, receita_total) usando AS.
- Sempre aplique um limite razoável (ex.: LIMIT 20) em rankings e listagens.
- Se a pergunta for ambígua, faça a escolha mais útil para negócios e registre na explicação.

Schema do banco:
{schema}
"""


@dataclass
class RespostaLLM:
    sql: str
    explicacao: str
    grafico: str  # "nenhum" | "barra" | "linha"


@dataclass
class Tentativa:
    sql: str
    erro: str


class GeradorSQL(Protocol):
    def gerar(self, pergunta: str, schema: str, tentativas: list[Tentativa]) -> RespostaLLM: ...


def montar_mensagens(pergunta: str, tentativas: list[Tentativa]) -> list[dict[str, Any]]:
    """Histórico da conversa: pergunta + (tool_use falho, tool_result com erro) de cada tentativa."""
    mensagens: list[dict[str, Any]] = [{"role": "user", "content": pergunta}]
    for idx, t in enumerate(tentativas, 1):
        tool_id = f"toolu_tentativa_{idx}"
        mensagens.append({
            "role": "assistant",
            "content": [{
                "type": "tool_use",
                "id": tool_id,
                "name": FERRAMENTA["name"],
                "input": {"sql": t.sql, "explicacao": "", "grafico": "nenhum"},
            }],
        })
        mensagens.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": (
                    f"Essa consulta falhou com o erro: {t.erro}\n"
                    "Corrija e chame a ferramenta gerar_sql novamente."
                ),
                "is_error": True,
            }],
        })
    return mensagens


class GeradorClaude:
    """Chama a API da Anthropic com tool use forçado."""

    def __init__(self, config: Config, cliente: Any | None = None) -> None:
        self.config = config
        if cliente is not None:
            self._cliente = cliente
        else:
            if not config.api_key:
                raise RuntimeError("ANTHROPIC_API_KEY não configurada.")
            import anthropic  # import preguiçoso para não exigir rede/chave nos testes

            self._cliente = anthropic.Anthropic(api_key=config.api_key)

    def gerar(self, pergunta: str, schema: str, tentativas: list[Tentativa]) -> RespostaLLM:
        resposta = self._cliente.messages.create(
            model=self.config.modelo,
            max_tokens=1024,
            system=SYSTEM_PROMPT.format(schema=schema),
            tools=[FERRAMENTA],
            tool_choice={"type": "tool", "name": "gerar_sql"},
            messages=montar_mensagens(pergunta, tentativas),
        )
        for bloco in resposta.content:
            if getattr(bloco, "type", None) == "tool_use" and bloco.name == "gerar_sql":
                dados = bloco.input
                return RespostaLLM(
                    sql=str(dados.get("sql", "")).strip(),
                    explicacao=str(dados.get("explicacao", "")).strip(),
                    grafico=str(dados.get("grafico", "nenhum")).strip() or "nenhum",
                )
        raise RuntimeError("O modelo Claude não retornou a chamada esperada da ferramenta gerar_sql.")
