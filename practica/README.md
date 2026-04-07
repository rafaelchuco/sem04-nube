# Despliegue de `practica`

Esta app funciona mejor en Render que en Vercel.

## Por que Render

La app descarga archivos de video y puede usar `ffmpeg`. En Vercel, las Functions tienen sistema de archivos de solo lectura salvo `/tmp` y un limite de respuesta de 4.5 MB, lo que rompe descargas reales de video. Render si soporta este caso usando Docker.

## Desplegar en Render

1. Sube este repo a GitHub.
2. En Render, crea un servicio nuevo desde el repo.
3. Si Render detecta el `render.yaml`, acepta el Blueprint.
4. El servicio ya quedara apuntando a:
   - `rootDir: practica`
   - `dockerfilePath: ./practica/Dockerfile`
   - `healthCheckPath: /health`
5. Espera el build y abre la URL `.onrender.com`.

## Ejecutar localmente con Docker

```bash
cd practica
docker build -t practica-video-downloader .
docker run --rm -p 5000:10000 practica-video-downloader
```

Luego abre `http://localhost:5000`.

## Ejecutar localmente sin Docker

```bash
cd practica
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

## Nota sobre Vercel

Vercel podria levantar la app Flask, pero no es una opcion confiable para esta funcionalidad de descarga de videos.
