"""Servidor web local (biblioteca padrão): uma página + API JSON.

Pensado para uso local/demonstração: escuta em 127.0.0.1 por padrão e não tem autenticação.
Não exponha na internet sem colocar autenticação na frente.
"""

from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import Config
from .modelos import ErroProvedor
from .pipeline import Analista
from .web_pagina import PAGINA

EXEMPLOS = [
    "Qual o faturamento por categoria de restaurante?",
    "Como evoluiu o faturamento mês a mês?",
    "Quais são os 5 restaurantes com maior faturamento?",
    "Qual a taxa de cancelamento por cidade?",
    "Quantos pedidos entregues temos por dia da semana?",
    "Qual o tempo médio de entrega por tipo de veículo do entregador?",
    "Quais cidades tiveram faturamento acima da média das cidades?",
]
LIMITE_CORPO = 8 * 1024


def resposta_json(res, analista: Analista) -> dict:
    png = analista.grafico_png(res)
    return {
        "pergunta": res.pergunta,
        "sql": res.sql,
        "explicacao": res.explicacao,
        "colunas": res.colunas,
        "linhas": [list(r) for r in res.linhas],
        "truncado": res.truncado,
        "grafico": res.grafico,
        "grafico_png": base64.b64encode(png).decode() if png else None,
        "recusa": res.recusa,
        "erro": res.erro,
        "tentativas": len(res.tentativas),
        "tempo_s": round(res.tempo_s, 3),
        "provedor": res.provedor,
    }


def criar_servidor(host: str, porta: int, analista: Analista) -> ThreadingHTTPServer:
    trava = threading.Lock()  # SQLite e matplotlib: uma pergunta por vez

    class Handler(BaseHTTPRequestHandler):
        server_version = "AnalistaSQL/0.1"

        def log_message(self, formato, *args):  # silencioso
            pass

        def _enviar(self, codigo: int, corpo: bytes, tipo: str) -> None:
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(corpo)

        def _json(self, codigo: int, dados: dict) -> None:
            self._enviar(codigo, json.dumps(dados, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def do_GET(self):  # noqa: N802
            if self.path in ("/", "/index.html"):
                self._enviar(200, PAGINA.encode(), "text/html; charset=utf-8")
            elif self.path == "/api/info":
                self._json(200, {"provedor": analista.gerador.nome, "exemplos": EXEMPLOS})
            elif self.path == "/health":
                self._json(200, {"status": "ok"})
            else:
                self._json(404, {"erro": "Não encontrado."})

        def do_POST(self):  # noqa: N802
            if self.path != "/api/perguntar":
                return self._json(404, {"erro": "Não encontrado."})
            try:
                tamanho = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return self._json(400, {"erro": "Content-Length inválido."})
            if tamanho <= 0 or tamanho > LIMITE_CORPO:
                return self._json(413 if tamanho > LIMITE_CORPO else 400, {"erro": "Corpo da requisição inválido."})
            try:
                pergunta = str(json.loads(self.rfile.read(tamanho))["pergunta"])[:500]
            except (ValueError, KeyError, TypeError):
                return self._json(400, {"erro": 'Envie JSON no formato {"pergunta": "..."}.'})
            try:
                with trava:
                    res = analista.perguntar(pergunta)
                    dados = resposta_json(res, analista)
            except ErroProvedor as exc:
                dados = {"erro": str(exc)}
            except Exception as exc:  # nunca derruba o servidor
                dados = {"erro": f"Erro interno: {exc}"}
            self._json(200, dados)

    return ThreadingHTTPServer((host, porta), Handler)


def servir(host: str, porta: int, provedor: str) -> None:
    config = Config.do_ambiente()
    analista = Analista.criar(config, provedor)
    servidor = criar_servidor(host, porta, analista)
    print(f"Analista SQL Delivery em http://{host}:{porta}  (provedor: {analista.gerador.nome})  — Ctrl+C para sair")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando.")
    finally:
        servidor.server_close()
        analista.fechar()
