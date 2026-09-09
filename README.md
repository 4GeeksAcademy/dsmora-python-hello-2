# Pipeline resiliente con Python, Prefect 3 y uv

Demo didactica y ejecutable de una canalizacion de telemetria. El codigo separa
el trabajo de datos (ejecutar) de la coordinacion, estados y politicas de
resiliencia (orquestar).

## Preparacion

Requiere Python 3.12 o posterior y
[uv](https://docs.astral.sh/uv/getting-started/installation/). Desde la raiz:

```bash
uv sync
```

El proyecto fue configurado con:

```bash
uv init --bare --name resilient-data-pipeline
uv add "prefect>=3"
```

No se usan dependencias adicionales: JSON, fechas y SQLite proceden de la
biblioteca estandar de Python.

## Ejecucion local

Ejecuta el camino normal:

```bash
uv run python data/pipelines/pipeline.py
```

Provoca el fallo controlado del paso opcional:

```bash
uv run python data/pipelines/pipeline.py --fail-optional-snapshot
```

La segunda orden muestra `export_eval_snapshot` como `Failed`, pero el flow
principal termina como `Completed` porque la task se invoca con
`return_state=True` y el flow inspecciona su estado sin propagar el error.

## Prefect UI

En un entorno local, inicia el servidor en una terminal:

```bash
uv run prefect server start
```

Abre <http://localhost:4200>. En otra terminal conecta el cliente y ejecuta:

```bash
export PREFECT_API_URL=http://localhost:4200/api
uv run python data/pipelines/pipeline.py
```

En GitHub Codespaces, el navegador no puede usar `127.0.0.1` del contenedor.
Publica la API mediante el puerto reenviado:

```bash
export PREFECT_PUBLIC_URL="https://${CODESPACE_NAME}-4200.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}"
PREFECT_UI_API_URL="${PREFECT_PUBLIC_URL}/api" \
	uv run prefect server start --host 0.0.0.0 --port 4200
```

Cuando Codespaces muestre el aviso del puerto 4200, abre la URL reenviada. En
otra terminal, los flows pueden hablar directamente con el servidor dentro del
contenedor:

```bash
export PREFECT_API_URL=http://127.0.0.1:4200/api
uv run python data/pipelines/pipeline.py
```

La UI permite inspeccionar el flow `business-performance-pipeline`, sus tasks,
estados, parametros, duraciones, reintentos y logs.

## Etapas de la demo

| Concepto | Implementacion |
| --- | --- |
| Fuente | `data/raw/telemetry_events.jsonl`, con IDs y fechas heterogeneos, nulos, duplicados y montos invalidos. |
| Ingesta | `extract_events` lee objetos crudos sin limpiarlos. Si falta la fuente, crea la muestra reproducible. |
| Transformacion | `transform_events` normaliza IDs, acciones, fechas y montos; descarta invalidos y duplicados. |
| KPIs | `calculate_kpis` calcula volumen, usuarios, compras, ingresos, conversion, errores y ventana. |
| Carga | `load_kpis` guarda en SQLite mediante UPSERT sobre `(window_start, window_end)`. |
| Entrega | `latest_kpis.json` ofrece el resultado actual y `export_eval_snapshot` deja una muestra validable. |
| Observabilidad | `@flow`, `@task`, estados y `get_run_logger()` hacen visible cada paso en Prefect. |
| Reintentos | Lectura y escritura tienen tres intentos con dos segundos de espera. |
| Cache | La transformacion usa una clave derivada de sus entradas y expira tras una hora. |
| Fallos | Las tasks criticas propagan errores; el snapshot opcional devuelve su estado y permite continuar. |

La ingesta y la transformacion son deliberadamente distintas: leer JSON y
devolver sus diccionarios es ingesta; cambiar tipos, validar, normalizar y
deduplicar ocurre solo durante la transformacion.

## Archivos generados

```text
data/
	raw/telemetry_events.jsonl
	processed/eval_snapshot.json
	reporting/business_kpis.sqlite
	reporting/pipeline_runs.jsonl
	reporting/latest_kpis.json
```

`pipeline_runs.jsonl` agrega una entrada por corrida con ID, inicio, fin,
estado, conteos y error. `latest_kpis.json` y `eval_snapshot.json` se reemplazan
atomicamente para representar la ultima entrega.

## Comprobar idempotencia

Ejecuta dos veces el mismo rango:

```bash
uv run python data/pipelines/pipeline.py
uv run python data/pipelines/pipeline.py
```

Consulta SQLite sin instalar otra herramienta:

```bash
uv run python -c "import sqlite3; db=sqlite3.connect('data/reporting/business_kpis.sqlite'); print(db.execute('SELECT window_start, window_end, COUNT(*) FROM reporting_kpis GROUP BY window_start, window_end').fetchall())"
```

Cada ventana muestra conteo `1`: la segunda corrida actualiza la fila existente
en vez de duplicarla. El historial de corridas si agrega una linea por ejecucion,
porque su objetivo es auditoria y no representa el resultado de negocio.
