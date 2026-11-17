import json
from types import SimpleNamespace

import pytest

from analista_sql.executor import Executor
from analista_sql.synthetic import gerar_banco


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    caminho = tmp_path_factory.mktemp("dados") / "delivery_teste.db"
    gerar_banco(caminho, semente=7, escala=0.2)
    return caminho


@pytest.fixture()
def executor(db_path):
    ex = Executor(db_path, max_linhas=1000, timeout_s=5.0)
    yield ex
    ex.fechar()


class ClienteFalso:
    """Imita `openai.OpenAI()` (endpoint xAI Grok) devolvendo respostas pré-programadas de tool call."""

    def __init__(self, *respostas: dict):
        self.respostas = list(respostas)
        self.chamadas: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._criar))

    def _criar(self, **kwargs):
        self.chamadas.append(kwargs)
        dados = self.respostas.pop(0)
        chamada = SimpleNamespace(
            id=f"call_{len(self.chamadas)}",
            type="function",
            function=SimpleNamespace(name="gerar_sql", arguments=json.dumps(dados, ensure_ascii=False)),
        )
        mensagem = SimpleNamespace(content=None, tool_calls=[chamada])
        return SimpleNamespace(choices=[SimpleNamespace(message=mensagem)])


@pytest.fixture()
def cliente_falso():
    return ClienteFalso
