# Python con uv

Este proyecto usa [uv](https://docs.astral.sh/uv/) como gestor de paquetes y de entornos virtuales de Python.

## Entorno virtual

Crear o recrear el entorno virtual:

```bash
uv venv
```

Activarlo en Linux/macOS:

```bash
source .venv/bin/activate
```

## Ejecutar el programa

```bash
uv run python main.py
```

También puede ejecutarse directamente con Python:

```bash
python main.py
```

## Ejemplo con Redis, Celery y FastAPI

El archivo `docker-compose.yml` levanta:

- **Redis** en `localhost:6379`, como broker de mensajes y backend de resultados.
- **Tres workers Celery** (`worker-1`, `worker-2` y `worker-3`) que consumen las tareas en paralelo.
- **FastAPI** en <http://localhost:8000>.
- **Flower** en <http://localhost:5555> para monitorizar los workers.

El worker está configurado con concurrencia 1 y `prefetch-multiplier=1`, por lo
que no reserva tareas antes de tiempo. Cada tarea tiene un timeout suave de 25
segundos y un límite máximo de 30 segundos. Si el worker se pierde antes de
confirmar una tarea, Redis puede volver a entregarla.

Iniciar todos los servicios:

```bash
docker compose up --build
```

Cada worker tiene concurrencia 1. Celery distribuye las tareas entre los tres
workers conectados al mismo broker Redis. Para verlos en ejecución:

```bash
docker compose ps
docker compose logs -f worker-1 worker-2 worker-3
```

Encolar una suma:

```bash
curl -X POST "http://localhost:8000/tasks/add?x=2&y=3"
```

La respuesta incluye un `task_id`. Consultar el resultado sustituyendo ese valor:

```bash
curl "http://localhost:8000/tasks/<task_id>"
```

Para validar el manejo de errores, la tarea genera fallos simulados. Los
`soft error` son transitorios y se reintentan hasta tres veces. Los `hard
error`, o los `soft error` que agotan sus reintentos, se guardan en una DLQ
(Redis) clasificados por criticidad. Consultar la DLQ:

```bash
curl "http://localhost:8000/dlq"
```

Una tarea fallida puede reprocesarse posteriormente con el identificador
original:

```bash
curl -X POST "http://localhost:8000/dlq/<task_id>/reprocess"
```

Al reprocesarla se elimina de la DLQ y se crea un nuevo `task_id`.

Para iniciar únicamente el broker Redis, equivalente al comando `docker run` del ejemplo:

```bash
docker compose up -d redis
```

Detener los servicios y eliminar el volumen de datos:

```bash
docker compose down -v
```
