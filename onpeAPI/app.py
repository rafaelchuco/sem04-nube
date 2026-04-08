from __future__ import annotations

import atexit
import os
import re
from http import HTTPStatus

from flask import Flask, jsonify, render_template, request

from onpe_service import (
    CaptchaRequiredError,
    OnpeLookupError,
    OnpePlaywrightClient,
)

app = Flask(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "si", "on"}


# Reutiliza la misma instancia de navegador para evitar el costo de abrir Chromium por request.
client = OnpePlaywrightClient(headless=_env_bool("ONPE_HEADLESS", default=False))


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
        msg = str(exc)
        msg_l = msg.lower()
        if (
            "500" in msg
            or "interno del servidor" in msg_l
            or "pagina no encontrada" in msg_l
            or "página no encontrada" in msg_l
        ):
            msg = (
                "ONPE devolvio un error interno temporal. Intenta nuevamente en unos segundos "
                "o resuelve captcha si aparece en la ventana del navegador."
            )
        return (
            jsonify(
                {
                    "ok": False,
                    "error": msg,
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


def _extraer_dnis_desde_texto(texto: str) -> list[str]:
    encontrados = re.findall(r"\b\d{8}\b", texto)
    # Mantiene orden de aparicion y elimina duplicados.
    return list(dict.fromkeys(encontrados))


@app.post("/consultar-lote")
def consultar_lote():
    archivo = request.files.get("archivo")
    if archivo is None or not archivo.filename:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "Debes adjuntar un archivo .txt o .csv con DNIs.",
                }
            ),
            HTTPStatus.BAD_REQUEST,
        )

    try:
        contenido = archivo.read().decode("utf-8", errors="ignore")
    except Exception:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "No se pudo leer el archivo enviado.",
                }
            ),
            HTTPStatus.BAD_REQUEST,
        )

    dnis = _extraer_dnis_desde_texto(contenido)
    if not dnis:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "No se encontraron DNIs validos (8 digitos) en el archivo.",
                }
            ),
            HTTPStatus.BAD_REQUEST,
        )

    resultados: list[dict[str, object]] = []

    for dni in dnis:
        try:
            data = client.consultar_dni_playwright(dni)
            resultados.append({"dni": dni, "ok": True, **data})
        except CaptchaRequiredError as exc:
            resultados.append(
                {
                    "dni": dni,
                    "ok": False,
                    "error": str(exc),
                    "code": "captcha_required",
                }
            )
        except OnpeLookupError as exc:
            resultados.append(
                {
                    "dni": dni,
                    "ok": False,
                    "error": str(exc),
                    "code": "lookup_error",
                }
            )
        except Exception:
            resultados.append(
                {
                    "dni": dni,
                    "ok": False,
                    "error": "Ocurrio un error inesperado durante la consulta.",
                    "code": "unexpected_error",
                }
            )

    return (
        jsonify(
            {
                "ok": True,
                "total": len(dnis),
                "procesados": len(resultados),
                "resultados": resultados,
            }
        ),
        HTTPStatus.OK,
    )


@atexit.register
def _shutdown_browser() -> None:
    client.close()


if __name__ == "__main__":
    # Playwright sync no es thread-safe entre hilos; ejecutamos en modo de un solo hilo.
    app.run(debug=True, use_reloader=False, threaded=False, host="0.0.0.0", port=5000)
