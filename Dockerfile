# Imagen base - Python oficial
FROM python:3.11-slim


# Metadata
LABEL maintainer="rafael.chuco@tecsup.edu.com"




LABEL description="Mi primera aplicación Docker"


# Establecer directorio de trabajo
WORKDIR /app


# Copiar archivo de dependencias
COPY requirements.txt .


# Instalar dependencias
RUN pip install --no-cache-dir -r requirements.txt


# Copiar código de la aplicación
COPY app.py .


# Exponer el puerto
EXPOSE 5000


# Comando por defecto
CMD ["python", "app.py"]

