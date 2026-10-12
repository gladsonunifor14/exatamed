"""Observabilidade: logs estruturados, identificador de requisição e log de acesso.

- Cada requisição recebe um identificador (cabeçalho X-Request-ID, aceito do proxy ou gerado),
  devolvido na resposta e incluído em todos os logs da requisição.
- Log de acesso por requisição: método, rota, status, duração, usuário e IP. A query string
  NÃO é registrada, pois pode conter dados pessoais (ex.: nome digitado na busca de pacientes).
- Em produção os logs saem em JSON (uma linha por evento), prontos para agregadores
  (Render, Datadog, Loki, CloudWatch...). Em desenvolvimento, texto legível.
"""

import json
import logging
import re
import sys
import time
import uuid
from datetime import datetime, timezone

from flask import g, has_request_context, request

FORMATO_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
logger_acesso = logging.getLogger("exatamed.acesso")


class FiltroContexto(logging.Filter):
    """Acrescenta o identificador da requisição e o usuário a cada registro de log."""

    def filter(self, registro):
        registro.request_id = g.get("request_id", "-") if has_request_context() else "-"
        usuario = g.get("_login_user") if has_request_context() else None
        registro.usuario_id = getattr(usuario, "id", None) if getattr(usuario, "is_authenticated", False) else None
        return True


class FormatadorJSON(logging.Formatter):
    CAMPOS_EXTRAS = ("metodo", "rota", "status", "duracao_ms", "ip", "endpoint")

    def format(self, registro):
        dados = {
            "momento": datetime.fromtimestamp(registro.created, timezone.utc).isoformat(timespec="milliseconds"),
            "nivel": registro.levelname,
            "logger": registro.name,
            "mensagem": registro.getMessage(),
            "request_id": getattr(registro, "request_id", "-"),
            "usuario_id": getattr(registro, "usuario_id", None),
        }
        for campo in self.CAMPOS_EXTRAS:
            if hasattr(registro, campo):
                dados[campo] = getattr(registro, campo)
        if registro.exc_info:
            dados["excecao"] = self.formatException(registro.exc_info)
        return json.dumps(dados, ensure_ascii=False)


def configurar_logs(app):
    formato = app.config.get("LOG_FORMATO") or ("json" if app.config.get("PRODUCAO") else "texto")
    manipulador = logging.StreamHandler(sys.stdout)
    manipulador.addFilter(FiltroContexto())
    if formato == "json":
        manipulador.setFormatter(FormatadorJSON())
    else:
        manipulador.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"))
    raiz = logging.getLogger("exatamed")
    raiz.handlers[:] = [manipulador]
    raiz.setLevel(app.config.get("LOG_NIVEL", "INFO"))
    raiz.propagate = False
    app.logger.handlers[:] = [manipulador]
    app.logger.setLevel(app.config.get("LOG_NIVEL", "INFO"))

    @app.before_request
    def _inicio():
        recebido = request.headers.get("X-Request-ID", "")
        g.request_id = recebido if FORMATO_ID.match(recebido) else uuid.uuid4().hex
        g.inicio_requisicao = time.perf_counter()

    @app.after_request
    def _fim(resposta):
        resposta.headers["X-Request-ID"] = g.get("request_id", "")
        if request.endpoint != "static" and not app.config.get("TESTING"):
            duracao = (time.perf_counter() - g.get("inicio_requisicao", time.perf_counter())) * 1000
            logger_acesso.info(
                "%s %s %s", request.method, request.path, resposta.status_code,
                extra={"metodo": request.method, "rota": request.path, "status": resposta.status_code,
                       "duracao_ms": round(duracao, 1), "ip": request.remote_addr, "endpoint": request.endpoint})
        return resposta
