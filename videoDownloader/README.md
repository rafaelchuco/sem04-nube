# Video Downloader

Aplicación web construida con Flask para analizar enlaces de video, mostrar una vista previa y permitir la descarga en distintas calidades usando `yt-dlp`.

La interfaz está pensada para que el flujo sea simple:

1. El usuario pega una URL.
2. La app detecta la plataforma.
3. Se obtiene la metadata del video sin descargarlo.
4. Se muestra una vista previa con miniatura, duración, autor y calidades disponibles.
5. El usuario elige una calidad y descarga el archivo.

## Funcionalidad principal

- Analiza enlaces de video desde una sola interfaz.
- Detecta automáticamente la plataforma según el dominio.
- Muestra vista previa antes de descargar.
- Lista las calidades compatibles disponibles.
- Descarga el archivo final desde el backend.
- Usa `ffmpeg` cuando está disponible para combinar video y audio en mejores calidades.
- Mantiene un historial reciente en el navegador.

## Plataformas soportadas

Actualmente la app reconoce enlaces de:

- YouTube
- TikTok
- Instagram
- Facebook
- X / Twitter
- Vimeo

## Como funciona internamente

### 1. Analisis del enlace

Cuando se envía una URL al endpoint `/preview`, la app usa `yt-dlp` para extraer información como:

- título
- creador o canal
- duración
- miniatura
- resoluciones disponibles
- URL original del contenido

En esta etapa no se descarga el video completo, solo se consulta su metadata.

### 2. Seleccion de calidad

La app filtra los formatos disponibles y arma una lista de opciones más claras para el usuario. Si `ffmpeg` no está instalado, se limitan algunos formatos que requieren unir video y audio por separado.

### 3. Descarga del archivo

Cuando el usuario confirma la descarga, el backend usa `yt-dlp` para obtener el archivo en una carpeta temporal. Después lo devuelve al navegador como archivo adjunto y limpia los temporales al finalizar.

### 4. Miniaturas y vista previa

Las miniaturas se sirven a través del endpoint `/thumbnail` para evitar problemas de carga directa desde el navegador. En videos de YouTube, la app también intenta construir una URL de `embed` para mostrar una vista previa más rica.

## Endpoints principales

- `GET /`
  Sirve la interfaz principal.

- `GET /health`
  Endpoint de salud para verificar si la app está activa y si `ffmpeg` está disponible.

- `GET /thumbnail`
  Hace de proxy para servir la miniatura del video.

- `POST /preview`
  Recibe una URL y responde con la metadata y las opciones de calidad.

- `POST /download`
  Descarga el video según la URL y calidad seleccionada.

## Tecnologias usadas

- Python
- Flask
- yt-dlp
- ffmpeg
- Bootstrap
- Bootstrap Icons

## Estructura principal

```text
practica/
├── app.py
├── requirements.txt
├── Dockerfile
├── Dockerfile.multistage
├── Dockerfile.optimizado
├── wsgi.py
└── README.md
```

## Ejecucion local

### Opcion 1: Python

```bash
cd practica
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Luego abre `http://localhost:5000`.

### Opcion 2: Docker

```bash
cd practica
docker build -t practica-video-downloader .
docker run --rm -p 5000:10000 practica-video-downloader
```

Luego abre `http://localhost:5000`.

## Despliegue recomendado

### Render

Esta app funciona mejor en Render porque:

- permite ejecutar contenedores Docker sin problema
- soporta `ffmpeg` dentro de la imagen
- tolera mejor descargas pesadas
- no depende del modelo serverless para responder con archivos grandes

El repositorio ya incluye un [render.yaml](../render.yaml) para facilitar ese despliegue.

Pasos:

1. Sube el proyecto a GitHub.
2. En Render, crea un nuevo servicio desde ese repositorio.
3. Acepta el Blueprint si Render detecta `render.yaml`.
4. Espera el build y abre la URL pública generada.

Configuración esperada:

- `rootDir: practica`
- `dockerContext: .`
- `dockerfilePath: ./Dockerfile`
- `healthCheckPath: /health`

### Vercel

Vercel no es la mejor opción para esta app. Aunque puede ejecutar aplicaciones Python/Flask, este proyecto depende de descargas de archivos de video y del uso de almacenamiento temporal, algo que encaja mucho mejor en Render que en una arquitectura basada en Functions.

## Consideraciones

- La disponibilidad real de formatos depende de la plataforma origen.
- Algunas resoluciones altas requieren `ffmpeg` para unir audio y video.
- El tiempo de descarga puede variar según el tamaño del archivo y la fuente.
- Es importante usar la herramienta respetando los términos de servicio y derechos del contenido que se descarga.
