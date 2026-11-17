"""Camada de LLM: traduz pergunta em linguagem natural para SQL via Groq (Llama 3.3 70B).

Usa function calling forçado (`tool_choice="required"`) no endpoint compatível com OpenAI
da Groq (`https://api.groq.com/openai/v1`) para garantir resposta estruturada com SQL,
explicação, sugestão de gráfico ou recusa.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from types import SimpleNamespace
from typing import Any, Protocol

from .config import MODELO_PADRAO
from .modelos import ErroProvedor, Geracao, Tentativa

GROQ_BASE_URL = "https://api.groq.com/openai/v1"

FERRAMENTA = {
    "type": "function",
    "function": {
        "name": "gerar_sql",
        "description": (
            "Gera uma única consulta SELECT em SQLite para responder à pergunta de negócio, "
            "ou recusa quando a pergunta pede escrita, previsão ou dados inexistentes no esquema."
        ),
        "parameters": {
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


def montar_mensagens(pergunta: str, tentativas: list[Tentativa], contexto: str = "") -> list[dict[str, Any]]:
    """Histórico da conversa no formato Chat Completions: system + user + (tool_calls, tool) de cada tentativa."""
    mensagens: list[dict[str, Any]] = []
    if contexto:
        mensagens.append({"role": "system", "content": f"{SYSTEM_PROMPT}\n\n{contexto}"})
    mensagens.append({"role": "user", "content": pergunta})
    for idx, t in enumerate(tentativas, 1):
        tool_id = f"call_tentativa_{idx}"
        mensagens.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": tool_id,
                    "type": "function",
                    "function": {
                        "name": "gerar_sql",
                        "arguments": json.dumps(
                            {"sql": t.sql, "explicacao": "", "grafico": "nenhum", "motivo_recusa": None},
                            ensure_ascii=False,
                        ),
                    },
                }
            ],
        })
        mensagens.append({
            "role": "tool",
            "tool_call_id": tool_id,
            "content": (
                f"Essa consulta falhou com o erro: {t.erro}\n"
                "Corrija o SQL usando apenas tabelas e colunas do esquema e chame gerar_sql novamente."
            ),
        })
    return mensagens


class _ClienteHTTPGroq:
    """Fallback leve via biblioteca padrão caso o pacote `openai` não esteja instalado."""

    def __init__(self, api_key: str, base_url: str = GROQ_BASE_URL) -> None:
        self._api_key = api_key
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> Any:
        corpo = json.dumps(kwargs, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self._url,
            data=corpo,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
                "User-Agent": "analista-sql-delivery/0.1",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                dados = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detalhe = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {detalhe}") from exc

        msg = dados["choices"][0]["message"]
        tool_calls = [
            SimpleNamespace(
                id=tc.get("id", ""),
                type=tc.get("type", "function"),
                function=SimpleNamespace(
                    name=tc["function"]["name"],
                    arguments=tc["function"]["arguments"],
                ),
            )
            for tc in (msg.get("tool_calls") or [])
        ]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=msg.get("content"), tool_calls=tool_calls))]
        )


class GeradorGroq:
    """Chama a API gratuita da Groq com function calling forçado."""

    def __init__(
        self,
        api_key: str | None,
        modelo: str = MODELO_PADRAO,
        cliente: Any | None = None,
    ) -> None:
        self.modelo = modelo
        self.nome = f"groq:{modelo}"
        if cliente is not None:
            self._cliente = cliente
        else:
            if not api_key:
                raise ErroProvedor("GROQ_API_KEY não configurada.")
            try:
                import openai

                self._cliente = openai.OpenAI(api_key=api_key, base_url=GROQ_BASE_URL)
            except ImportError:
                self._cliente = _ClienteHTTPGroq(api_key=api_key, base_url=GROQ_BASE_URL)

    def gerar(self, pergunta: str, contexto: str, tentativas: list[Tentativa]) -> Geracao:
        try:
            resposta = self._cliente.chat.completions.create(
                model=self.modelo,
                max_tokens=2048,
                temperature=0,
                tools=[FERRAMENTA],
                tool_choice="required",
                messages=montar_mensagens(pergunta, tentativas, contexto),
            )
        except Exception as exc:
            raise ErroProvedor(f"Falha ao consultar a API da Groq: {exc}") from exc

        choices = getattr(resposta, "choices", None) or []
        if not choices:
            raise ErroProvedor("A API da Groq não retornou escolhas na resposta.")

        mensagem = choices[0].message
        for chamada in getattr(mensagem, "tool_calls", None) or []:
            func = getattr(chamada, "function", None)
            if func is not None and getattr(func, "name", None) == "gerar_sql":
                raw_args = getattr(func, "arguments", "{}")
                try:
                    dados = raw_args if isinstance(raw_args, dict) else json.loads(raw_args or "{}")
                except json.JSONDecodeError as exc:
                    raise ErroProvedor(f"Argumentos JSON inválidos retornados pela Groq: {exc}") from exc

                raw_sql = dados.get("sql")
                if raw_sql is None or str(raw_sql).strip().lower() in ("", "null", "none"):
                    sql = None
                else:
                    sql = str(raw_sql).strip()

                explicacao = str(dados.get("explicacao", "")).strip()
                grafico = dados.get("grafico")
                grafico_limpo = str(grafico).strip() if grafico else None
                motivo = dados.get("motivo_recusa")
                motivo_recusa = (
                    None
                    if motivo is None or str(motivo).strip().lower() in ("", "null", "none")
                    else str(motivo).strip()
                )
                if sql is None and not motivo_recusa:
                    motivo_recusa = explicacao or "Pergunta fora do escopo dos dados disponíveis."
                return Geracao(
                    sql=sql,
                    explicacao=explicacao,
                    grafico=grafico_limpo,
                    motivo_recusa=motivo_recusa,
                )
        raise ErroProvedor("O modelo Groq não retornou a chamada esperada da ferramenta gerar_sql.")
