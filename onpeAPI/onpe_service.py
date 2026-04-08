from __future__ import annotations

import re
import threading
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


class OnpeLookupError(Exception):
    """Error general al consultar ONPE."""


class OnpeTemporaryError(OnpeLookupError):
    """Error temporal de la web de ONPE que puede resolverse con reintento."""


class CaptchaRequiredError(OnpeLookupError):
    """Se detecto captcha y no se pudo completar la consulta automaticamente."""


@dataclass
class ParsedResult:
    nombre: str | None
    es_miembro_mesa: bool | None
    rol_mesa: str | None = None
    ubicacion_local: str | None = None
    local_votacion: str | None = None
    region_provincia_distrito: str | None = None
    direccion_local: str | None = None
    referencia_local: str | None = None
    numero_mesa: str | None = None
    numero_orden: str | None = None
    pabellon: str | None = None
    piso: str | None = None
    aula: str | None = None


class OnpePlaywrightClient:
    """Cliente Playwright reutilizable para consultas ONPE."""

    def __init__(self, headless: bool = False):
        self.headless = headless
        self._playwright = None
        self._browser: Browser | None = None
        self._startup_lock = threading.Lock()
        self._consulta_lock = threading.Lock()
        self._manual_context = None
        self._manual_page: Page | None = None

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
            self._cleanup_manual_session()
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

    def _take_manual_session(self) -> tuple[Any | None, Page | None]:
        context = self._manual_context
        page = self._manual_page
        self._manual_context = None
        self._manual_page = None

        if not context or not page:
            return None, None

        try:
            if page.is_closed():
                context.close()
                return None, None
        except Exception:
            try:
                context.close()
            except Exception:
                pass
            return None, None

        return context, page

    def _store_manual_session(self, context: Any, page: Page) -> None:
        self._cleanup_manual_session()
        self._manual_context = context
        self._manual_page = page

    def _cleanup_manual_session(self) -> None:
        page = self._manual_page
        context = self._manual_context
        self._manual_page = None
        self._manual_context = None

        if page:
            try:
                if not page.is_closed():
                    page.close()
            except Exception:
                pass

        if context:
            try:
                context.close()
            except Exception:
                pass

    def consultar_dni_playwright(
        self,
        dni: str,
        timeout_ms: int = 90000,
        _retry_on_closed: bool = True,
    ) -> dict[str, Any]:
        """
        Consulta ONPE interactuando con la web publica y leyendo el estado desde el DOM.

        Si aparece reCAPTCHA, deja la ventana abierta (headless=False) para resolverlo manualmente.
        """
        browser = self._ensure_browser()

        # Serializa consultas para minimizar bloqueos por anti-bot y facilitar captcha manual.
        with self._consulta_lock:
            context, page = self._take_manual_session()
            if context is None or page is None:
                context = browser.new_context(locale="es-PE")
                page = context.new_page()

            try:
                max_intentos = 3
                parsed: ParsedResult | None = None
                body_text = ""

                for intento in range(1, max_intentos + 1):
                    try:
                        self._abrir_inicio_o_reutilizar(page, timeout_ms)
                        self._llenar_dni(page, dni)
                        self._click_consultar(page)
                        parsed, body_text = self._esperar_estado_final(page, timeout_ms)
                        break
                    except OnpeTemporaryError:
                        if intento == max_intentos:
                            raise
                        # Espera corta para que ONPE se estabilice y reintenta toda la secuencia.
                        page.wait_for_timeout(1200 * intento)

                if parsed is None:
                    raise OnpeLookupError(
                        "No se pudo obtener un resultado valido de ONPE tras varios intentos."
                    )

                response = {
                    "dni": dni,
                    "es_miembro_mesa": parsed.es_miembro_mesa,
                    "region_provincia_distrito": parsed.region_provincia_distrito,
                    "ubicacion_local": parsed.ubicacion_local,
                    "local_votacion": parsed.local_votacion,
                    "onpe_response": {
                        "source": "dom",
                        "body_excerpt": body_text[:1200],
                    },
                }

                if parsed.es_miembro_mesa is True:
                    response.update(
                        {
                            "nombre": parsed.nombre,
                            "rol_mesa": parsed.rol_mesa,
                            "direccion_local": parsed.direccion_local,
                            "referencia_local": parsed.referencia_local,
                            "numero_mesa": parsed.numero_mesa,
                            "numero_orden": parsed.numero_orden,
                            "pabellon": parsed.pabellon,
                            "piso": parsed.piso,
                            "aula": parsed.aula,
                        }
                    )

                return response
            except CaptchaRequiredError:
                self._store_manual_session(context, page)
                raise
            except PlaywrightTimeoutError as exc:
                if self._captcha_visible(page):
                    self._store_manual_session(context, page)
                    raise CaptchaRequiredError(
                        "Se detecto reCAPTCHA. Resuelvelo manualmente en la ventana abierta y vuelve a intentar."
                    ) from exc
                raise OnpeLookupError("La consulta excedio el tiempo de espera.") from exc
            except PlaywrightError as exc:
                msg = str(exc).lower()
                if _retry_on_closed and (
                    "target page, context or browser has been closed" in msg
                    or "browser has been closed" in msg
                ):
                    self._cleanup_manual_session()
                    return self.consultar_dni_playwright(
                        dni,
                        timeout_ms=timeout_ms,
                        _retry_on_closed=False,
                    )
                raise OnpeLookupError(f"Fallo de Playwright durante la consulta: {exc}") from exc
            finally:
                if self._manual_page is page and self._manual_context is context:
                    pass
                else:
                    try:
                        if not page.is_closed():
                            page.close()
                    except Exception:
                        pass

                    try:
                        context.close()
                    except Exception:
                        pass

    def _abrir_inicio_o_reutilizar(self, page: Page, timeout_ms: int) -> None:
        try:
            current_url = page.url
        except PlaywrightError:
            current_url = ""

        if current_url.startswith(ONPE_URL):
            if self._esperar_formulario(page, timeout_ms=8000):
                return

        max_intentos = 3
        for intento in range(1, max_intentos + 1):
            try:
                page.goto(ONPE_URL, wait_until="domcontentloaded", timeout=timeout_ms)
            except PlaywrightError:
                if intento == max_intentos:
                    raise
            if self._esperar_formulario(page, timeout_ms=6000):
                return
            page.wait_for_timeout(800 * intento)

        body_text = self._leer_texto_pagina(page).lower()
        if "error interno del servidor" in body_text:
            raise OnpeTemporaryError("La web de ONPE abrio en 'Error interno del servidor'.")
        if "pagina no encontrada" in body_text or "página no encontrada" in body_text:
            raise OnpeTemporaryError("La web de ONPE abrio en 'Pagina no encontrada'.")
        raise OnpeLookupError("La web de ONPE no mostro el formulario de consulta.")

    def _esperar_formulario(self, page: Page, timeout_ms: int) -> bool:
        waited = 0
        while waited < timeout_ms:
            if self._pagina_inicio_lista(page):
                return True
            page.wait_for_timeout(500)
            waited += 500

        return self._pagina_inicio_lista(page)

    def _pagina_inicio_lista(self, page: Page) -> bool:
        try:
            return page.locator("input[placeholder*='DNI' i]").first.is_visible(timeout=1200)
        except PlaywrightError:
            return False

    def _esperar_estado_final(self, page: Page, timeout_ms: int) -> tuple[ParsedResult, str]:
        deadline = timeout_ms
        started = 0
        while started < deadline:
            body_text = self._leer_texto_pagina(page)
            normalized = body_text.lower()

            parsed = self._parsear_resultado_desde_pagina(page)
            if parsed and self._resultado_consistente(parsed):
                return parsed, body_text

            if "error interno del servidor" in normalized:
                if self._captcha_visible(page):
                    raise CaptchaRequiredError(
                        "ONPE mostro captcha y luego un error temporal. Resuelvelo en la ventana del navegador y vuelve a intentar."
                    )
                raise OnpeTemporaryError("ONPE mostro 'Error interno del servidor' en la web.")

            if "pagina no encontrada" in normalized or "página no encontrada" in normalized:
                if self._captcha_visible(page):
                    raise CaptchaRequiredError(
                        "ONPE mostro captcha y luego una pagina de error temporal. Resuelvelo en la ventana del navegador y vuelve a intentar."
                    )
                raise OnpeTemporaryError("ONPE mostro 'Pagina no encontrada' en la web.")

            if "captcha" in normalized or "no soy un robot" in normalized:
                raise CaptchaRequiredError(
                    "Se detecto reCAPTCHA. Resuelvelo manualmente en la ventana abierta y vuelve a intentar."
                )

            if "formato" in normalized and "dni" in normalized:
                raise OnpeLookupError(
                    "ONPE rechazo el formato del DNI. Verifica que ingreses 8 digitos y vuelve a intentar."
                )

            page.wait_for_timeout(500)
            started += 500

        raise PlaywrightTimeoutError("Tiempo de espera agotado al observar la web de ONPE.")

    @staticmethod
    def _leer_texto_pagina(page: Page) -> str:
        try:
            return page.locator("body").inner_text(timeout=1500)
        except PlaywrightError:
            return ""

    def _parsear_resultado_desde_pagina(self, page: Page) -> ParsedResult | None:
        """Fallback por DOM cuando ONPE no expone el JSON de respuesta."""
        # Primero usamos la estructura actual de la vista de resultado de ONPE.
        try:
            root = page.locator("app-local-de-votacion").first
            if root.count() > 0:
                parsed = self._parsear_resultado_desde_texto(root.inner_text(timeout=1500))
                if parsed:
                    return parsed
        except PlaywrightError:
            pass

        # Fallback textual por si ONPE cambia ligeramente la maqueta.
        try:
            text = page.inner_text("body")
        except PlaywrightError:
            return None

        if not text:
            return None

        return self._parsear_resultado_desde_texto(text)

    def _parsear_resultado_desde_texto(self, text: str) -> ParsedResult | None:
        if not text:
            return None

        nombre_match = re.search(r"Nombres y Apellidos\s+([^\n]+)", text, flags=re.IGNORECASE)
        region_match = re.search(r"Regi[oó]n / Provincia / Distrito\s+([^\n]+)", text, flags=re.IGNORECASE)
        local_match = re.search(
            r"Tu local de votaci[oó]n\s+ver\s+Mapa\s+([^\n]+)",
            text,
            flags=re.IGNORECASE,
        )
        direccion_match = re.search(
            r"Tu local de votaci[oó]n\s+ver\s+Mapa\s+[^\n]+\s+([^\n]+)",
            text,
            flags=re.IGNORECASE,
        )
        referencia_match = re.search(r"Referencia:\s*([^\n]+)", text, flags=re.IGNORECASE)
        mesa_match = re.search(r"N[°ºo] de Mesa:\s*([0-9]+)", text, flags=re.IGNORECASE)
        orden_match = re.search(r"N[°ºo] de Orden:\s*([0-9]+)", text, flags=re.IGNORECASE)
        pabellon_match = re.search(r"Pabell[oó]n\s+([0-9A-Z-]+)", text, flags=re.IGNORECASE)
        piso_match = re.search(r"Piso\s+([0-9A-Z-]+)", text, flags=re.IGNORECASE)
        aula_match = re.search(r"Aula\s+([0-9A-Z-]+)", text, flags=re.IGNORECASE)

        nombre = nombre_match.group(1).strip() if nombre_match else None
        region = region_match.group(1).strip() if region_match else None
        local = local_match.group(1).strip() if local_match else None
        direccion = direccion_match.group(1).strip() if direccion_match else None
        referencia_local = referencia_match.group(1).strip() if referencia_match else None
        numero_mesa = mesa_match.group(1).strip() if mesa_match else None
        numero_orden = orden_match.group(1).strip() if orden_match else None
        pabellon = pabellon_match.group(1).strip() if pabellon_match else None
        piso = piso_match.group(1).strip() if piso_match else None
        aula = aula_match.group(1).strip() if aula_match else None

        es_miembro_mesa, rol_mesa = self._extraer_rol_mesa_texto(text)

        # Si solo hay etiquetas sin valores reales, no consideramos que el resultado este listo.
        valores_invalidos = {
            "dni",
            "nombres y apellidos",
            "región / provincia / distrito",
            "region / provincia / distrito",
            "consultar",
            "oficina central",
        }
        if nombre and nombre.strip().casefold() in valores_invalidos:
            nombre = None
        if region and region.strip().casefold() in valores_invalidos:
            region = None
        if local and local.strip().casefold() in valores_invalidos:
            local = None
        if direccion and direccion.strip().casefold() in valores_invalidos:
            direccion = None

        if not any(
            [
                nombre,
                local,
                direccion,
                referencia_local,
                numero_mesa,
                numero_orden,
                pabellon,
                piso,
                aula,
                rol_mesa,
                es_miembro_mesa is not None,
            ]
        ):
            return None

        ubicacion_local = " - ".join(part for part in [region, local] if part)

        return ParsedResult(
            nombre=nombre,
            es_miembro_mesa=es_miembro_mesa,
            rol_mesa=rol_mesa,
            ubicacion_local=ubicacion_local or None,
            local_votacion=local,
            region_provincia_distrito=region,
            direccion_local=direccion,
            referencia_local=referencia_local,
            numero_mesa=numero_mesa,
            numero_orden=numero_orden,
            pabellon=pabellon,
            piso=piso,
            aula=aula,
        )

    @staticmethod
    def _resultado_consistente(parsed: ParsedResult) -> bool:
        # Regla solicitada: o es miembro de mesa (con datos completos), o no lo es (con datos basicos).
        if parsed.es_miembro_mesa is True:
            return bool(parsed.rol_mesa and parsed.local_votacion and parsed.region_provincia_distrito)

        if parsed.es_miembro_mesa is False:
            return bool(parsed.local_votacion and parsed.region_provincia_distrito)

        return False

    @staticmethod
    def _extraer_valor_seguidor(lines: list[str], etiqueta: str) -> str | None:
        patron = re.compile(etiqueta, re.IGNORECASE)
        for index, line in enumerate(lines):
            if patron.fullmatch(line):
                for siguiente in lines[index + 1 :]:
                    valor = siguiente.strip()
                    if valor:
                        return valor
                return None
        return None

    @staticmethod
    def _extraer_valor_en_linea(lines: list[str], etiqueta: str) -> str | None:
        patron = re.compile(etiqueta, re.IGNORECASE)
        for line in lines:
            match = patron.fullmatch(line)
            if match and match.group(1):
                valor = match.group(1).strip()
                if valor:
                    return valor
        return None

    @staticmethod
    def _extraer_valores_seguidos(
        lines: list[str],
        etiqueta: str,
        cantidad: int,
        omitir: set[str] | None = None,
    ) -> list[str]:
        patron = re.compile(etiqueta, re.IGNORECASE)
        omitidos = {value.strip().casefold() for value in (omitir or set())}
        for index, line in enumerate(lines):
            if patron.fullmatch(line):
                valores: list[str] = []
                for siguiente in lines[index + 1 :]:
                    valor = siguiente.strip()
                    if not valor or valor.casefold() in omitidos:
                        continue
                    valores.append(valor)
                    if len(valores) >= cantidad:
                        return valores
                return valores
        return []

    @staticmethod
    def _extraer_rol_mesa_texto(text: str) -> tuple[bool | None, str | None]:
        if re.search(r"^NO ERES MIEMBRO DE MESA$", text, flags=re.IGNORECASE | re.MULTILINE):
            return False, None

        rol_match = re.search(r"^ERES\s+([^\n]+)$", text, flags=re.IGNORECASE | re.MULTILINE)
        if rol_match:
            rol = rol_match.group(1).strip()
            if rol:
                return True, rol
        return None, None

    @staticmethod
    def _texto_locator(locator: Any) -> str | None:
        try:
            text = locator.inner_text(timeout=1000).strip()
        except PlaywrightError:
            return None
        return text or None

    @staticmethod
    def _safe_response_payload(response: Any) -> dict[str, Any]:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                return payload
            return {"raw": payload}
        except PlaywrightError:
            try:
                return {"raw": response.text()}
            except PlaywrightError:
                return {
                    "raw": None,
                    "error": "No se pudo leer el body de la respuesta ONPE.",
                }

    def _llenar_dni(self, page: Page, dni: str) -> None:
        """Busca el input DNI con varios selectores robustos para tolerar cambios de UI."""
        candidatos = [
            # Selectores exactos observados en la vista Angular de ONPE.
            page.locator("app-c-input[formcontrolname='numeroDocumento'] input").first,
            page.locator("input[placeholder='Número de DNI']").first,
            page.locator("input[placeholder='Numero de DNI']").first,
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
            page.locator("button.button_estilo4.button_consulta").first,
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
        rol_mesa = self._buscar_texto(
            data,
            ["rolMesa", "rol_mesa", "cargoMesa", "cargo_mesa", "cargo", "rol", "condicionMesa"],
        )
        local = self._buscar_texto(
            data,
            ["localVotacion", "local_votacion", "local", "nombreLocal", "direccionLocal"],
        )
        region = self._buscar_texto(
            data,
            ["regionProvinciaDistrito", "region_provincia_distrito", "ubigeo", "zona"],
        )

        miembro_raw = self._buscar_valor(
            data,
            ["esMiembroMesa", "miembroMesa", "miembro_mesa", "es_miembro_mesa", "condicionMiembroMesa"],
        )
        miembro = self._normalizar_bool(miembro_raw)

        ubicacion_local = " - ".join(part for part in [region, local] if part)

        return ParsedResult(
            nombre=nombre,
            es_miembro_mesa=miembro,
            rol_mesa=rol_mesa,
            ubicacion_local=ubicacion_local or None,
            local_votacion=local,
            region_provincia_distrito=region,
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
