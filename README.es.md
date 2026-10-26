# Mexico Lindo: agent de viajes con autenticacion

Frontend TanStack Start (React/TypeScript), backend FastAPI, agente LangGraph
existente, servidor FastMCP protegido con MCPAuth y Redis. Dependencias Python
fijadas con uv y frontend con el lockfile de npm.

## Arranque con un comando

Requisitos: Docker, Compose v2 y acceso a un proveedor LLM compatible con OpenAI.
Configura tu archivo local `.env`, ignorado por Git, o exporta estas variables:

```dotenv
LLM_API_URL='https://tu-proveedor.example/v1'
LLM_MODEL='tu-modelo'
LLM_API_KEY='tu-clave-privada'
APP_ORIGIN='http://localhost:3000'
```

Las comillas simples conservan `$` literalmente en el parser dotenv de Compose.
No subas credenciales reales al repositorio.

```sh
./scripts/up.sh
```

Construye y levanta **cinco servicios en segundo plano**, espera sus healthchecks
y verifica HTTP/MCP. Interfaz: <http://localhost:3000>.
Solo el frontend publica un puerto, ligado a loopback; backend, agente, MCP y
Redis quedan en la red interna de Docker; no es necesario reenviar el puerto 8000
ni el 8002. En Codespaces, el script detecta el origen HTTPS del puerto 3000
automaticamente y lo muestra al terminar. Para usar otro origen, exporta
`APP_ORIGIN` antes de ejecutar el script; en Codespaces, esta deteccion tiene
prioridad sobre el valor de `.env`. Otros origenes no pueden enviar operaciones.
Solo en desarrollo con `CODESPACES=true`, tambien se permite
`http://localhost:3000` y `https://localhost:3000`, porque el proxy de Codespaces
reescribe el encabezado Origin con esas variantes. La comprobacion del token
CSRF sigue siendo obligatoria.

**Cuenta demo de desarrollo:** `test@test.com` / `test1234$`.
El script proporciona esta contrasena conocida solo para desarrollo. Puedes
exportar `DEMO_USER_PASSWORD` antes del arranque para cambiar la semilla inicial.
TinyDB almacena exclusivamente el hash Argon2id. La semilla es idempotente:
reiniciar no duplica cuentas ni cambia contrasenas existentes.
Este Compose es exclusivamente para **desarrollo local**, no para produccion.

```sh
docker compose ps
docker compose logs --tail=50 backend agent mcp
docker compose down
```

El apagado normal conserva los datos. `down -v` borraria usuarios, claves,
preferencias y planes; no lo uses como apagado habitual.

## Arquitectura y permisos

```text
navegador -> TanStack Start /api -> FastAPI -> agente LangGraph -> FastMCP
                                      |             |              |
                                    TinyDB        Redis       Open-Meteo
```

- Invitados: solo planifican viajes por Mexico; su agente no registra herramientas MCP.
- Autenticados: clima y guardar/listar/eliminar exclusivamente sus propios planes.
- El clima y las escrituras requieren una confirmacion explicita, de un solo
  uso y ligada a la accion. Rechazar o dejar caducar no ejecuta la accion.
- Iniciar sesion no implica consentimiento. No hay reservas, pagos, registro
  publico ni recuperacion de contrasenas.
- Se conserva el evaluador/optimizador del planner: hasta 15 evaluaciones y
  propuestas de hasta 1.500 caracteres, sin afirmar disponibilidad verificada.

TinyDB guarda usuarios en el volumen privado `backend-data`; solo escribe un
proceso backend. No aumentes el numero de workers. Redis con AOF persiste
preferencias y planes y almacena sesiones, historiales, trabajos y confirmaciones
con caducidad. No se comparte el usuario CLI `default` con usuarios web.
Los invitados no tienen memoria personal persistente; las conversaciones se
aislan por sesion y conversacion, sin fusion automatica al iniciar sesion.
Recargar la pagina inicia una conversacion nueva; los planes guardados permanecen.

### JWT de aplicacion y autorizacion MCP

FastAPI autentica contra TinyDB y emite JWT RS256 en cookie HttpOnly,
SameSite=Strict y Secure fuera de desarrollo. Las mutaciones comprueban token
CSRF y origen exacto. No se guarda ningun JWT en localStorage.

Los tokens son distintos: aplicacion (`aud=backend`), llamada interna al agente
(`aud=agent`) y acceso delegado a herramientas (`aud=mcp`, con scopes).
El token MCP nunca se entrega al JavaScript del navegador ni al LLM.
Redis permite revocar sesiones al salir; los servicios comprueban la revocacion,
tambien antes de ejecutar una operacion ya confirmada.

Se utiliza el middleware `create_bearer_auth` de **MCPAuth 0.1.1**, con verificacion
RS256/JWKS estricta. No se usa su constructor de descubrimiento OAuth, que exige
un proveedor authorization-code/PKCE completo: esta integracion interna no publica
endpoints OAuth ficticios ni promete interoperabilidad OAuth 2.1.
Cada herramienta comprueba scope y propietario usando la identidad de MCPAuth.
El transporte MCP conserva sesiones para la elicitacion clasica y las vincula
a la sesion autenticada, evitando reutilizarlas con otra identidad.

La clave privada se genera una vez en desarrollo, con permisos 0600 en el volumen
del backend. Los otros servicios solo reciben claves publicas por JWKS.
La clave LLM se entrega exclusivamente al agente. Fuera de desarrollo se rechaza
la semilla demo, se exige HTTPS y hay que aportar la clave de firma.
Produccion y clientes MCP externos requieren otro diseno OAuth/OIDC/TLS.

Limites: sesiones/historiales de una hora, trabajos de diez minutos, confirmaciones
de 90 segundos, cuatro trabajos concurrentes, limites de login/chat/herramientas
y 50 planes por usuario. Los trabajos interrumpidos no se repiten automaticamente.

## Comprobaciones y CLI

El smoke de arranque no llama al LLM de pago ni consulta Open-Meteo:

```sh
docker compose exec -T backend python /app/scripts/smoke.py
docker compose exec -T backend python /app/scripts/smoke.py --extended
```

El extendido crea y elimina un plan temporal, comprobando consentimiento,
aislamiento, scopes, claims JWT y vinculacion de sesiones MCP. Utiliza la cuenta
demo configurada. Son comprobaciones operativas, no una suite nueva de pruebas.
Para verificar el proveedor LLM, pide un itinerario mexicano al agent.
Los healthchecks no garantizan disponibilidad o cuota de servicios externos.
Build y tipos del frontend: `cd frontend && npm ci && npm run build`.

La CLI original sigue disponible con `uv run python main.py` en modo planificacion,
salvo que se proporcione un `MCP_ACCESS_TOKEN` delegado valido.
Para autenticarte y confirmar herramientas sin exportar tokens:

```sh
uv run python main.py --web
uv run python main.py --web --login
```

Solicita credenciales y consentimiento por terminal y cierra la sesion al salir.
El servidor Flask heredado `server.py` no se utiliza en este despliegue.

## Plantilla Python original

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

### Validación del planificador

El planificador revisa cada propuesta con un evaluador y la optimiza si hace falta, hasta un máximo de 15 evaluaciones. El progreso se muestra junto al enrutado de agentes. El plan debe incluir itinerario diario, traslados, actividades concretas, presupuesto desglosado y no superar 1.500 caracteres.

El planificador no consulta fuentes de horarios, cierres, obras ni disponibilidad de recintos. Presenta esas actividades como propuestas y no debe afirmar que su disponibilidad esté verificada.

### Contribuidores

Esta plantilla fue creada como parte de los [Recursos de Python de 4Geeks](https://4geeks.com/es/technology/python) para el aprendizaje en [4Geeks.com](https://4geeks.com) por [Alejandro Sanchez](https://twitter.com/alesanchezr) y [muchos otros contribuyentes](https://github.com/4GeeksAcademy/python-hello/graphs/contributors).
