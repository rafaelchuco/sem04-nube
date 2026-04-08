from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Any

from playwright.sync_api import (
    Browser,
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

ONPE_URL = "https://consultaelectoral.onpe.gob.pe/inicio"
API_PATH_BUSQUEDA_DNI = "/v1/api/busqueda/dni"
API_PATH_RESULTADO_DEFINITIVO = "/v1/api/consulta/definitiva"


class OnpeLookupError(Exception):
    """Error general al consultar ONPE."""


class CaptchaRequiredError(OnpeLookupError):
    """Se detecto captcha y no se pudo completar la consulta automaticamente."""


@dataclass
class ParsedResult:
    nombre: str | None
    es_miembro_mesa: bool | None
    local_votacion: str | None


class OnpePlaywrightClient:
    """Cliente Playwright reutilizable para consultas ONPE."""

    def __init__(self, headless: bool = False):
        self.headless = headless
        self._playwright = None
        self._browser: Browser | None = None
        self._startup_lock = threading.Lock()
        self._consulta_lock = threading.Lock()

    def _ensure_browser(self) -> Browser:
        if self._browser:
            return self._browser

        with self._startup_lock:
            if self._browser:
                return self._browser

            self._playwright = sync_playwright().start()
            # Canal Chromium normal para que el usuario pueda interactuar si aparece reCAPTCHA.
            self._browser = self._playwright.chromium.launch(headless=self.headless)
            return self._browser

    def close(self) -> None:
        with self._startup_lock:
            if self._browser:
                try:
                    self._browser.close()
                except Exception:
                    # En cierre de proceso (atexit) puede no existir el mismo contexto/hilo.
                    pass
                self._browser = None
            if self._playwright:
                try:
                    self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None

    def consultar_dni_playwright(self, dni: str, timeout_ms: int = 90000) -> dict[str, Any]:
        """
        Consulta ONPE e intercepta la respuesta de red de la API interna.

        Si aparece reCAPTCHA, deja la ventana abierta (headless=False) para resolverlo manualmente.
        """
        browser = self._ensure_browser()

        # Serializa consultas para minimizar bloqueos por anti-bot y facilitar captcha manual.
        with self._consulta_lock:
            context = browser.new_context(locale="es-PE")
            page = context.new_page()

            captured: dict[str, Any] = {}
            captcha_visto = {"value": False}

            def on_response(response):
                if API_PATH_BUSQUEDA_DNI not in response.url and API_PATH_RESULTADO_DEFINITIVO not in response.url:
                    return

                payload: dict[str, Any]
                try:
                    payload = response.json()
                except PlaywrightError:
                    try:
                        payload = {"raw": response.text()}
                    except PlaywrightError:
                        payload = {
                            "raw": None,
                            "error": "No se pudo leer el body de la respuesta ONPE.",
                        }

                if API_PATH_BUSQUEDA_DNI in response.url:
                    captured["busqueda"] = {
                        "status": response.status,
                        "url": response.url,
                        "body": payload,
                    }

                if API_PATH_RESULTADO_DEFINITIVO in response.url:
                    captured["definitiva"] = {
                        "status": response.status,
                        "url": response.url,
                        "body": payload,
                    }

            page.on("response", on_response)

            try:
                page.goto(ONPE_URL, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_load_state("networkidle")

                self._llenar_dni(page, dni)
                self._click_consultar(page)

                start = time.monotonic()
                timeout_s = timeout_ms / 1000

                while "definitiva" not in captured and (time.monotonic() - start) < timeout_s:
                    if self._captcha_visible(page):
                        captcha_visto["value"] = True
                    # Espera corta cooperativa del propio Playwright (sin time.sleep).
                    page.wait_for_timeout(300)

                if "definitiva" not in captured:
                    # Si hubo respuesta de busqueda con error, devolvemos ese detalle.
                    if "busqueda" in captured:
                        mensaje_busqueda = self._extraer_mensaje_error(captured["busqueda"]["body"])
                        if mensaje_busqueda:
                            raise OnpeLookupError(f"ONPE (busqueda DNI): {mensaje_busqueda}")

                    if captcha_visto["value"]:
                        raise CaptchaRequiredError(
                            "Se detecto reCAPTCHA. Resuelvelo manualmente en la ventana abierta y vuelve a intentar."
                        )
                    raise OnpeLookupError(
                        "No se pudo capturar el resultado definitivo de ONPE. Verifica captcha o cambios en la UI."
                    )

                respuesta_final = captured["definitiva"]["body"]
                mensaje_error = self._extraer_mensaje_error(respuesta_final)
                success_final = self._extraer_success(respuesta_final)
                if mensaje_error:
                    mensaje_norm = mensaje_error.lower()
                    # Si success=true y hay mensaje, no lo tratamos como error fatal.
                    if success_final is True:
                        mensaje_error = None
                        mensaje_norm = ""
                    if "captcha" in mensaje_norm:
                        raise CaptchaRequiredError(
                            "ONPE solicito verificacion captcha. Resuelvelo en la ventana del navegador y vuelve a consultar."
                        )
                    if "formato" in mensaje_norm and "dni" in mensaje_norm:
                        raise OnpeLookupError(
                            "ONPE rechazo el formato del DNI. Verifica que ingreses 8 digitos y vuelve a intentar."
                        )
                    if "formato solicitado" in mensaje_norm:
                        raise OnpeLookupError(
                            "ONPE rechazo la solicitud por formato. Reintenta la consulta y, si aparece captcha, resuelvelo manualmente."
                        )
                    if mensaje_error:
                        raise OnpeLookupError(f"ONPE respondio con error: {mensaje_error}")

                parsed = self._parsear_resultado(respuesta_final)
                return {
                    "dni": dni,
                    "nombre": parsed.nombre,
                    "es_miembro_mesa": parsed.es_miembro_mesa,
                    "local_votacion": parsed.local_votacion,
                    "onpe_response": respuesta_final,
                }
            except PlaywrightTimeoutError as exc:
                raise OnpeLookupError("La consulta excedio el tiempo de espera.") from exc
            except PlaywrightError as exc:
                raise OnpeLookupError(f"Fallo de Playwright durante la consulta: {exc}") from exc
            finally:
                page.remove_listener("response", on_response)
                page.close()
                context.close()

    def _llenar_dni(self, page: Page, dni: str) -> None:
        """Busca el input DNI con varios selectores robustos para tolerar cambios de UI."""
        candidatos = [
            # Selectores observados en ONPE (input tel con placeholder Numero de DNI)
            page.locator("input[placeholder*='DNI' i]").first,
            page.locator("input[type='tel']").first,
            page.locator("input[required][maxlength='8']").first,
            page.locator("input[formcontrolname='dni']").first,
            page.locator("input[id*='dni' i]").first,
            page.locator("input[name='dni']").first,
            page.get_by_label(re.compile("dni", re.IGNORECASE)).first,
            page.get_by_role("textbox", name=re.compile("dni", re.IGNORECASE)).first,
        ]

        for locator in candidatos:
            try:
                locator.wait_for(state="visible", timeout=1500)
                if not locator.is_enabled(timeout=500):
                    continue
                locator.click()
                # Escribimos con teclado para disparar validaciones de Angular/Material.
                page.keyboard.press("Control+a")
                page.keyboard.type(dni, delay=30)
                value = locator.input_value(timeout=500)
                if value and re.sub(r"\D", "", value) == dni:
                    return
                # Reintento por si hubo mascara/autoformato en la primera escritura.
                page.keyboard.press("Control+a")
                page.keyboard.type(dni, delay=60)
                value = locator.input_value(timeout=500)
                if value and (re.sub(r"\D", "", value) == dni or dni in value):
                    return
            except PlaywrightError:
                continue

        raise OnpeLookupError("No se encontro el campo DNI en la pagina de ONPE.")

    def _click_consultar(self, page: Page) -> None:
        botones = [
            page.locator("button.button_consulta").first,
            page.get_by_role("button", name=re.compile("consultar", re.IGNORECASE)).first,
            page.get_by_text(re.compile("consultar", re.IGNORECASE)).first,
            page.locator("button[type='submit']").first,
            page.locator("button:has-text('Consultar')").first,
        ]

        for boton in botones:
            try:
                boton.wait_for(state="visible", timeout=1500)
                if boton.is_disabled(timeout=500):
                    continue
                boton.click()
                return
            except PlaywrightError:
                continue

        raise OnpeLookupError("No se encontro el boton de consulta en la pagina de ONPE.")

    @staticmethod
    def _captcha_visible(page: Page) -> bool:
        captcha_selectores = [
            "iframe[src*='recaptcha']",
            "div.g-recaptcha",
            "text=No soy un robot",
        ]
        for selector in captcha_selectores:
            try:
                if page.locator(selector).first.is_visible(timeout=200):
                    return True
            except PlaywrightError:
                continue
        return False

    def _parsear_resultado(self, payload: Any) -> ParsedResult:
        """Normaliza datos principales aunque cambie ligeramente la estructura del JSON."""
        data = payload
        if isinstance(payload, dict):
            for key in ["data", "resultado", "result", "contenido"]:
                if isinstance(payload.get(key), dict):
                    data = payload[key]
                    break

        nombre = self._buscar_texto(data, ["nombreCompleto", "nombre_completo", "nombre", "nombres"])
        local = self._buscar_texto(
            data,
            ["localVotacion", "local_votacion", "local", "nombreLocal", "direccionLocal"],
        )

        miembro_raw = self._buscar_valor(
            data,
            ["esMiembroMesa", "miembroMesa", "miembro_mesa", "es_miembro_mesa", "condicionMiembroMesa"],
        )
        miembro = self._normalizar_bool(miembro_raw)

        return ParsedResult(
            nombre=nombre,
            es_miembro_mesa=miembro,
            local_votacion=local,
        )

    @staticmethod
    def _buscar_valor(data: Any, keys: list[str]) -> Any:
        if not isinstance(data, dict):
            return None
        lowered = {k.lower(): v for k, v in data.items()}
        for key in keys:
            if key.lower() in lowered:
                return lowered[key.lower()]
        return None

    def _buscar_texto(self, data: Any, keys: list[str]) -> str | None:
        value = self._buscar_valor(data, keys)
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _normalizar_bool(value: Any) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)

        normalized = str(value).strip().lower()
        if normalized in {"si", "sí", "true", "1", "yes", "y"}:
            return True
        if normalized in {"no", "false", "0", "n"}:
            return False
        return None

    def _extraer_mensaje_error(self, payload: Any) -> str | None:
        """Intenta extraer mensajes de error comunes aunque ONPE cambie nombres de campos."""
        if isinstance(payload, str):
            text = payload.strip()
            return text or None

        if not isinstance(payload, dict):
            return None

        # Campos frecuentes de mensaje/estado de error.
        posibles_mensajes = ["mensaje", "message", "error", "detalle", "detail", "descripcion"]
        for key in posibles_mensajes:
            value = self._buscar_valor(payload, [key])
            if value:
                text = str(value).strip()
                if text:
                    return text

        # Algunos backends envian arrays de errores o payloads anidados.
        errores = self._buscar_valor(payload, ["errores", "errors"])
        if isinstance(errores, list) and errores:
            return str(errores[0]).strip() or None

        for nested in ["data", "resultado", "result", "contenido"]:
            child = payload.get(nested)
            if isinstance(child, dict):
                nested_msg = self._extraer_mensaje_error(child)
                if nested_msg:
                    return nested_msg

        return None

    @staticmethod
    def _extraer_success(payload: Any) -> bool | None:
        if not isinstance(payload, dict):
            return None
        value = payload.get("success")
        if isinstance(value, bool):
            return value
        if value is None:
            return None
        text = str(value).strip().lower()
        if text in {"true", "1", "si", "sí"}:
            return True
        if text in {"false", "0", "no"}:
            return False
        return None
