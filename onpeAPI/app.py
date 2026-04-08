from __future__ import annotations

import atexit
import re
from http import HTTPStatus

from flask import Flask, jsonify, render_template, request

from onpe_service import (
    CaptchaRequiredError,
    OnpeLookupError,
    OnpePlaywrightClient,
)

app = Flask(__name__)

# Reutiliza la misma instancia de navegador para evitar el costo de abrir Chromium por request.
client = OnpePlaywrightClient(headless=False)


def _validar_dni(dni: str) -> bool:
    return bool(re.fullmatch(r"\d{8}", dni))


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/consultar")
def consultar_dni():
    payload = request.get_json(silent=True) or {}
    dni = str(payload.get("dni", "")).strip()

    if not _validar_dni(dni):
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "El DNI debe tener exactamente 8 digitos numericos.",
                }
            ),
            HTTPStatus.BAD_REQUEST,
        )

    try:
        resultado = client.consultar_dni_playwright(dni)
        return jsonify({"ok": True, **resultado}), HTTPStatus.OK
    except CaptchaRequiredError as exc:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": str(exc),
                    "code": "captcha_required",
                }
            ),
            HTTPStatus.CONFLICT,
        )
    except OnpeLookupError as exc:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": str(exc),
                    "code": "lookup_error",
                }
            ),
            HTTPStatus.BAD_GATEWAY,
        )
    except Exception:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "Ocurrio un error inesperado durante la consulta.",
                    "code": "unexpected_error",
                }
            ),
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )


@atexit.register
def _shutdown_browser() -> None:
    client.close()


if __name__ == "__main__":
    # Playwright sync no es thread-safe entre hilos; ejecutamos en modo de un solo hilo.
    app.run(debug=True, use_reloader=False, threaded=False, host="0.0.0.0", port=5000)
