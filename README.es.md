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

### Contribuidores

Esta plantilla fue creada como parte de los [Recursos de Python de 4Geeks](https://4geeks.com/es/technology/python) para el aprendizaje en [4Geeks.com](https://4geeks.com) por [Alejandro Sanchez](https://twitter.com/alesanchezr) y [muchos otros contribuyentes](https://github.com/4GeeksAcademy/python-hello/graphs/contributors).

## Servidor MCP de clima protegido

El servidor MCP valida access tokens JWT con `mcpauth`. Configura en el archivo `.env`:

```dotenv
MCP_AUTH_ISSUER=https://<project-ref>.supabase.co/auth/v1
MCP_AUTH_AUDIENCE=authenticated
MCP_RESOURCE_URL=http://localhost:8000/mcp
```

En Supabase, reemplaza `<project-ref>` por el identificador del proyecto y habilita OAuth Server. `MCP_AUTH_ISSUER` puede contener la URL base `https://<project-ref>.supabase.co` o el issuer completo `https://<project-ref>.supabase.co/auth/v1`; la aplicación añade `/auth/v1` automáticamente si recibe la URL base. El discovery OAuth se consulta en `https://<project-ref>.supabase.co/.well-known/oauth-authorization-server/auth/v1`. Habilita una clave JWT asimétrica para que Supabase publique JWKS y `mcpauth` pueda verificar las firmas. Los access tokens de usuario de Supabase usan `aud=authenticated`, configurado por defecto en `MCP_AUTH_AUDIENCE`.

`MCP_RESOURCE_URL` identifica el servidor MCP, no la audiencia del JWT. En despliegues públicos, reemplázala por la URL HTTPS pública del endpoint MCP. El servidor expone Protected Resource Metadata y rechaza solicitudes MCP sin un Bearer válido.

En el proceso del agente configura `MCP_ACCESS_TOKEN` con el access token obtenido al autorizar un cliente OAuth con ese proveedor. No es el `id_token` y no hace falta entregárselo al proceso servidor. `mcpauth` valida el token, pero no lo obtiene ni lo renueva. No publiques ni guardes este valor en el repositorio.

Inicia el servidor y, en otra terminal, ejecuta el agente:

```bash
uv run python -m dsmora_python_hello_2.mcp_weather.server
uv run python main.py
```

Para probar el inicio de sesión interactivo con `uv run python test_supabase_mcp.py`, puedes guardar la clave pública `anon`/`publishable` en `.env` como `SUPABASE_ANON_KEY` (o `SUPABASE_PUBLISHABLE_KEY`) para no introducirla en cada ejecución. No uses la clave `service_role`. El script seguirá solicitando el correo y la contraseña del usuario; la contraseña no se guarda.
