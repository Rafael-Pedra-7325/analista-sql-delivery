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
    """Imita `anthropic.Anthropic()` devolvendo respostas pré-programadas de tool use."""

    def __init__(self, *respostas: dict):
        self.respostas = list(respostas)
        self.chamadas: list[dict] = []
        self.messages = SimpleNamespace(create=self._criar)

    def _criar(self, **kwargs):
        self.chamadas.append(kwargs)
        dados = self.respostas.pop(0)
        bloco = SimpleNamespace(type="tool_use", name="gerar_sql", input=dados)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="..."), bloco])


@pytest.fixture()
def cliente_falso():
    return ClienteFalso
