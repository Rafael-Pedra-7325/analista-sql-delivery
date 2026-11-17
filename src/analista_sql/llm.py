"""Camada de LLM: traduz pergunta em linguagem natural para SQL via Claude (Anthropic API).

Usa tool use forçado (`tool_choice={"type": "tool", "name": "gerar_sql"}`) e prompt caching
do contexto do esquema para garantir resposta estruturada (SQL, explicação, gráfico ou recusa).
"""

from __future__ import annotations

from typing import Any, Protocol

from .config import MODELO_PADRAO
from .modelos import ErroProvedor, Geracao, Tentativa

FERRAMENTA = {
    "name": "gerar_sql",
    "description": (
        "Gera uma única consulta SELECT em SQLite para responder à pergunta de negócio, "
        "ou recusa quando a pergunta pede escrita, previsão ou dados inexistentes no esquema."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sql": {
                "type": ["string", "null"],
                "description": (
                    "Consulta SELECT (ou WITH ... SELECT) SQLite válida e somente leitura, "
                    "ou null quando a pergunta deve ser recusada."
                ),
            },
            "explicacao": {
                "type": "string",
                "description": "Resumo em 1 frase (português) do que a consulta calcula.",
            },
            "grafico": {
                "type": "string",
                "enum": ["nenhum", "barra", "linha", "dispersao"],
                "description": (
                    "Visualização sugerida: 'linha' para séries temporais, 'barra' para "
                    "categorias/rankings, 'dispersao' para duas métricas numéricas, 'nenhum' caso contrário."
                ),
            },
            "motivo_recusa": {
                "type": ["string", "null"],
                "description": "Explicação curta em português quando sql for null; caso contrário, null.",
            },
        },
        "required": ["sql", "explicacao", "grafico"],
    },
}

SYSTEM_PROMPT = """Você é um analista de dados sênior especializado em SQLite.
Converta a pergunta do usuário em UMA única consulta SELECT para o banco descrito abaixo.

Regras obrigatórias:
- Gere APENAS SELECT (ou WITH ... SELECT). Nunca use INSERT, UPDATE, DELETE, DROP, ALTER, PRAGMA ou ATTACH.
- Se o usuário pedir alteração/remoção de dados, dados pessoais inexistentes (nome, CPF, telefone, e-mail, endereço), lucro/custo ou previsões futuras, devolva sql = null e explique o motivo em motivo_recusa.
- Siga estritamente as regras de negócio, a grafia exata dos valores válidos e as convenções de saída listadas no contexto.
- Use somente as tabelas e colunas documentadas no esquema."""


class GeradorSQL(Protocol):
    nome: str

    def gerar(self, pergunta: str, contexto: str, tentativas: list[Tentativa]) -> Geracao: ...


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
                "input": {"sql": t.sql, "explicacao": "", "grafico": "nenhum", "motivo_recusa": None},
            }],
        })
        mensagens.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": (
                    f"Essa consulta falhou com o erro: {t.erro}\n"
                    "Corrija o SQL usando apenas tabelas e colunas do esquema e chame gerar_sql novamente."
                ),
                "is_error": True,
            }],
        })
    return mensagens


class GeradorClaude:
    """Chama a API da Anthropic com tool use forçado e prompt caching do esquema."""

    def __init__(
        self,
        api_key: str | None,
        modelo: str = MODELO_PADRAO,
        cliente: Any | None = None,
    ) -> None:
        self.modelo = modelo
        self.nome = f"claude:{modelo}"
        if cliente is not None:
            self._cliente = cliente
        else:
            if not api_key:
                raise ErroProvedor("ANTHROPIC_API_KEY não configurada.")
            try:
                import anthropic
            except ImportError as exc:
                raise ErroProvedor(
                    "Pacote 'anthropic' não instalado. Rode: pip install -e \".[claude]\""
                ) from exc
            self._cliente = anthropic.Anthropic(api_key=api_key)

    def gerar(self, pergunta: str, contexto: str, tentativas: list[Tentativa]) -> Geracao:
        try:
            resposta = self._cliente.messages.create(
                model=self.modelo,
                max_tokens=1024,
                system=[
                    {
                        "type": "text",
                        "text": f"{SYSTEM_PROMPT}\n\n{contexto}",
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                tools=[FERRAMENTA],
                tool_choice={"type": "tool", "name": "gerar_sql"},
                messages=montar_mensagens(pergunta, tentativas),
            )
        except Exception as exc:
            raise ErroProvedor(f"Falha ao consultar a API da Anthropic: {exc}") from exc

        for bloco in resposta.content:
            if getattr(bloco, "type", None) == "tool_use" and bloco.name == "gerar_sql":
                dados = bloco.input or {}
                raw_sql = dados.get("sql")
                sql = None if raw_sql is None or not str(raw_sql).strip() else str(raw_sql).strip()
                explicacao = str(dados.get("explicacao", "")).strip()
                grafico = dados.get("grafico")
                grafico_limpo = str(grafico).strip() if grafico else None
                motivo = dados.get("motivo_recusa")
                motivo_recusa = str(motivo).strip() if motivo else None
                if sql is None and not motivo_recusa:
                    motivo_recusa = explicacao or "Pergunta fora do escopo dos dados disponíveis."
                return Geracao(
                    sql=sql,
                    explicacao=explicacao,
                    grafico=grafico_limpo,
                    motivo_recusa=motivo_recusa,
                )
        raise ErroProvedor("O modelo Claude não retornou a chamada esperada da ferramenta gerar_sql.")
