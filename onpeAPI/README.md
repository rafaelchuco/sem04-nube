# ONPE API Demo con Flask + Playwright

Aplicacion web demo para consultar si una persona es miembro de mesa usando la web oficial de ONPE y automatizacion de navegador con Playwright.

## Requisitos

- Python 3.10+
- Linux / macOS / Windows

## Instalacion

```bash
pip install -r requirements.txt
playwright install
```

## Ejecucion

```bash
python app.py
```

Abrir en navegador:

- http://localhost:5000

## Endpoints

- `GET /`: interfaz web
- `POST /consultar`: consulta por DNI

Ejemplo de payload:

```json
{
  "dni": "12345678"
}
```

## Notas de funcionamiento

- Se usa `sync_playwright` con `headless=False` para permitir interaccion manual si aparece reCAPTCHA.
- Se intercepta respuesta de red mediante `page.on("response")` filtrando `"/v1/api/busqueda/dni"`.
- Se usan selectores robustos por `name`, `role`, texto y atributos alternativos para tolerar cambios de UI.
- El navegador se reutiliza entre solicitudes para mejor rendimiento.
- Si ONPE presenta captcha o cambia su UI, el backend devuelve errores claros para el frontend.
