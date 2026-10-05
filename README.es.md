# Python Hello

El boilerplate más básico para comenzar un proyecto en Python en 4Geeks. Inicia tu primer proyecto en Python desde cero.

## ¿Qué hacer a continuación?

Abre el archivo `main.py` y comienza a escribir tu código.

Ejecuta tu código escribiendo el siguiente comando en tu terminal:

```bash
$ python main.py
```

Puedes crear e incluir tantos archivos de Python (también conocidos como módulos) como desees utilizando las declaraciones de importación.

## Requisitos

Asegúrate de tener Python instalado en tu computadora. Te recomendamos encarecidamente [instalar Python a través de Pyenv](https://4geeks.com/es/how-to/que-es-pyenv-y-como-instalar-pyenv) para evitar conflictos de versiones en el futuro.

## Ejecutar la predicción y ver el dashboard de Prefect

`example.py` carga `model_pipeline.joblib` y predice una muestra del conjunto de
cáncer de mama de scikit-learn. Para registrar la ejecución y verla en el
dashboard, abre dos terminales:

1. Inicia el servidor y la interfaz web de Prefect. En Codespaces, la interfaz
	debe usar la URL reenviada del API, no `127.0.0.1` (esa dirección en el
	navegador apunta a la computadora del usuario). Ejecuta:

	```bash
	PREFECT_UI_API_URL="https://${CODESPACE_NAME}-4200.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}/api" uv run prefect server start --host 0.0.0.0
	```

	Deja esta terminal abierta. En la pestaña **Ports** de Codespaces, confirma
	que el puerto `4200` está reenviado.

2. Ejecuta el ejemplo apuntando a la API del servidor:

	```bash
	PREFECT_API_URL=http://127.0.0.1:4200/api uv run example.py
	```

Abre el enlace del puerto `4200` (o `http://localhost:4200` fuera de
Codespaces) para ver el dashboard y la ejecución del flow. Si aparece **Unable
to connect to Prefect server**, reinicia el servidor con el comando anterior y
verifica que estás abriendo el puerto `4200`, no el servidor Flask del puerto
`3000`.

### Contribuidores

Esta plantilla fue creada como parte de los [Recursos de Python de 4Geeks](https://4geeks.com/es/technology/python) para el aprendizaje en [4Geeks.com](https://4geeks.com) por [Alejandro Sanchez](https://twitter.com/alesanchezr) y [muchos otros contribuyentes](https://github.com/4GeeksAcademy/python-hello/graphs/contributors).
