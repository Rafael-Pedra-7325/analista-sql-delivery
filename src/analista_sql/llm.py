"""Gerador de SQL com Claude (tool use) e a interface comum aos geradores."""

from __future__ import annotations

from typing import Any, Protocol

from .modelos import ErroProvedor, Geracao, Tentativa

PROMPT_SISTEMA = """\
Você é um analista de dados sênior de uma plataforma brasileira de delivery de comida. \
Sua tarefa é transformar a pergunta do usuário, escrita em português, em UMA consulta SQL \
para o banco SQLite descrito abaixo.

Regras:
1. Dialeto SQLite. Apenas SELECT (ou WITH ... SELECT). Nunca modifique dados nem o esquema.
2. Use somente as tabelas e colunas do esquema; nunca invente nomes. Para filtros de texto, copie a \
grafia exata dos valores listados (com acentos).
3. Siga à risca as regras de negócio e as convenções da resposta abaixo: elas definem o que \
significam faturamento, ticket médio, taxa de cancelamento etc.
4. Se a pergunta não puder ser respondida com estes dados (ex.: pede telefone, lucro, custo de \
marketing, previsão) ou pedir para alterar/apagar dados, NÃO invente: chame a ferramenta com \
sql = null e explique o motivo em motivo_recusa.
5. Em perguntas ambíguas, escolha a interpretação mais comum e diga a premissa em `explicacao`.
6. Responda sempre chamando a ferramenta `gerar_sql`. `explicacao` deve ter 1 ou 2 frases em português.
7. Em `grafico`, sugira: 'barra' para comparar categorias, 'linha' para evolução no tempo, \
'dispersao' para relação entre duas medidas numéricas, 'nenhum' para valor único ou lista sem \
comparação.

{contexto}
"""

FERRAMENTA = {
    "name": "gerar_sql",
    "description": "Registra a consulta SQLite que responde à pergunta do usuário, ou recusa a pergunta.",
    "input_schema": {
        "type": "object",
        "properties": {
            "sql": {
                "type": ["string", "null"],
                "description": "Consulta SQLite (somente leitura). null se a pergunta não puder ser respondida.",
            },
            "explicacao": {
                "type": "string",
                "description": "1 a 2 frases em português: o que a consulta calcula e as premissas assumidas.",
            },
            "grafico": {
                "type": "string",
                "enum": ["barra", "linha", "dispersao", "nenhum"],
                "description": "Melhor tipo de gráfico para o resultado.",
            },
            "motivo_recusa": {
                "type": ["string", "null"],
                "description": "Quando sql é null, por que a pergunta não pode ser respondida.",
            },
        },
        "required": ["sql", "explicacao", "grafico"],
    },
}


class GeradorSQL(Protocol):
    nome: str

    def gerar(self, pergunta: str, contexto: str, tentativas: list[Tentativa]) -> Geracao: ...


def montar_mensagens(pergunta: str, tentativas: list[Tentativa]) -> list[dict[str, str]]:
    """Histórico da conversa: pergunta + (SQL falho, erro) de cada tentativa anterior."""
    mensagens = [{"role": "user", "content": pergunta}]
    for t in tentativas:
        mensagens.append({"role": "assistant", "content": f"Consulta tentada:\n{t.sql}"})
        mensagens.append({
            "role": "user",
            "content": f"Essa consulta falhou com o erro: {t.erro}\n"
                       "Corrija e chame a ferramenta gerar_sql novamente.",
        })
    return mensagens


class GeradorClaude:
    """Usa a API da Anthropic com tool use forçado, para receber a resposta já estruturada."""

    def __init__(self, api_key: str | None, modelo: str, client: Any = None, max_tokens: int = 1500):
        self.modelo = modelo
        self.max_tokens = max_tokens
        self.nome = f"claude:{modelo}"
        if client is not None:
            self.client = client
            return
        if not api_key:
            raise ErroProvedor(
                "ANTHROPIC_API_KEY não definida. Crie um arquivo .env (veja .env.example) "
                "ou use --provedor offline."
            )
        try:
            import anthropic
        except ImportError as exc:
            raise ErroProvedor("Pacote 'anthropic' não instalado. Rode: pip install anthropic") from exc
        self.client = anthropic.Anthropic(api_key=api_key)

    def gerar(self, pergunta: str, contexto: str, tentativas: list[Tentativa]) -> Geracao:
        try:
            resposta = self.client.messages.create(
                model=self.modelo,
                max_tokens=self.max_tokens,
                system=[{
                    "type": "text",
                    "text": PROMPT_SISTEMA.format(contexto=contexto),
                    "cache_control": {"type": "ephemeral"},  # o esquema é igual em todas as perguntas
                }],
                tools=[FERRAMENTA],
                tool_choice={"type": "tool", "name": FERRAMENTA["name"]},
                messages=montar_mensagens(pergunta, tentativas),
            )
        except Exception as exc:  # erros de rede, autenticação, limite de uso...
            raise ErroProvedor(f"Falha ao chamar a API da Anthropic: {exc}") from exc

        for bloco in resposta.content:
            if getattr(bloco, "type", None) == "tool_use":
                dados = dict(bloco.input or {})
                sql = dados.get("sql")
                return Geracao(
                    sql=sql.strip() if isinstance(sql, str) and sql.strip() else None,
                    explicacao=str(dados.get("explicacao") or ""),
                    grafico=dados.get("grafico"),
                    motivo_recusa=dados.get("motivo_recusa"),
                )
        raise ErroProvedor("A resposta do modelo não trouxe a chamada de ferramenta esperada.")
