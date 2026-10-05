---
name: review-pr-context
description: Revisa un Pull Request de GitHub contrastando sus cambios con un contexto, especificación o rúbrica proporcionada. Úsala cuando el usuario indique el proyecto/repositorio, la PR y el contexto de aceptación que debe cumplir.
---

# Revisión de Pull Request contra contexto

## Objetivo

Evaluar si una PR concreta satisface los requisitos funcionales, técnicos y de alcance proporcionados por el usuario. Entregar hallazgos priorizados y verificables; no cambiar ni aprobar la PR salvo que el usuario lo pida expresamente.

## Entradas necesarias

Solicita o identifica:

- **Proyecto/repositorio**: URL de GitHub, `owner/repo` o ruta local.
- **PR**: URL o número de PR.
- **Contexto**: brief, contexto de empresa, criterios de aceptación, issue, documento adjunto u otra especificación.
- **Alcance opcional**: revisar solo documentación, código, seguridad, pruebas, CI, o todos.

Si el usuario pide automatizar el flujo y faltan datos esenciales, formula preguntas concisas. No inventes el contexto de empresa ni des por hecho que un `CONTEXT.md` placeholder es el brief requerido.

## Procedimiento

1. **Asegurar el repositorio correcto**
   - Comprueba el workspace, `git status`, rama y remotos antes de ejecutar comandos destructivos.
   - Si hace falta clonar, crea una carpeta temporal (`projects/<repo>` o una ubicación acordada), clona el repositorio indicado y recupera la rama/head de la PR.
   - No sustituyas silenciosamente un repositorio similar. Confirma `owner/repo`, número, título, head/base y URL.
   - Si el usuario pidió eliminar el clon temporal, verifica que la ruta coincide exactamente con el clon de esta tarea y no contiene trabajo ajeno antes de borrarlo.

2. **Obtener la PR y su diff**
   - Obtén los metadatos, estado, rama base/head, lista de archivos, cambios, descripción, comentarios de review y checks cuando estén disponibles.
   - Revisa la PR activa/visible con las herramientas de PR si el usuario se refiere a ella; si dio URL/número explícito, usa esa PR.
   - Compara contra la base correcta; no evalúes solo la descripción escrita por el autor.
   - Lee archivos modificados y dependencias del dominio necesarias para verificar hechos.

3. **Descomponer el contexto en criterios comprobables**
   - Convierte cada requisito en un checklist: entregables, nombres exactos, métricas/KPIs, audiencia/frecuencia, datos de dominio, arquitectura, restricciones, pruebas y criterios de calidad.
   - Distingue requisitos obligatorios de recomendaciones.
   - Localiza los documentos canónicos del proyecto. Comprueba que corresponden al milestone y empresa correctos.
   - Si el contexto exigido no está en el repo/PR, dilo expresamente. No asumas equivalencia entre documentos solo por nombres parecidos.

4. **Validar afirmaciones y lógica de dominio**
   - Contrasta nombres de campos, IDs, enums, rutas, esquemas, tablas y cálculos contra los modelos, contratos, migraciones y servicios reales.
   - Comprueba implicaciones de granularidad temporal, actualizaciones, datos tardíos, duplicados, reintentos, concurrencia y recuperación si aplican.
   - En documentos de diseño, evalúa coherencia y ejecutabilidad conceptual, no exijas código que el milestone prohíbe.
   - En cambios de código, ejecuta las pruebas/lint/build pertinentes según el proyecto y reporta exactamente qué se ejecutó y el resultado.

5. **Clasificar los hallazgos**
   - Prioriza por severidad:
     - **Bloqueante / P1**: incumple una instrucción explícita, produce resultado de negocio incorrecto, vulnerabilidad crítica o rompe compatibilidad.
     - **Importante / P2**: gap funcional/técnico que debe resolverse antes de aprobar.
     - **Menor / P3**: claridad, mantenimiento o consistencia no bloqueante.
   - Cada hallazgo debe incluir: prioridad, ubicación (`archivo:línea` si es posible), problema, por qué contradice el contexto y recomendación concreta.
   - No presentes preferencias de estilo como errores.
   - Menciona también los requisitos que sí se cumplen y las limitaciones de evidencia.

6. **Emitir la revisión**
   - Da veredicto: **aprobar**, **aprobar con observaciones** o **solicitar cambios**.
   - Resume alcance y verificaciones en pocas líneas.
   - Lista primero los problemas que bloquean aprobación, después los menores.
   - Reporta pruebas ejecutadas/no ejecutadas y cualquier dato externo que falte.
   - Nunca afirmes que los checks pasan si no se consultaron/ejecutaron.

## Seguridad y límites

- No expongas secretos, tokens, URLs privadas ni variables sensibles en la respuesta o en logs.
- No hagas push, commits, merges, cierres de PR ni cambios al código de la PR sin autorización explícita.
- No borres carpetas del workspace salvo que el usuario lo solicite y la ruta haya sido verificada.
- No cambies de repositorio, rama base ni contexto objetivo sin avisar.
- Si GitHub o una herramienta devuelve error, informa la limitación; no presentes datos inferidos como verificados.

## Formato de salida sugerido

```markdown
## Veredicto: [aprobar | aprobar con observaciones | solicitar cambios]

### Hallazgos
1. **[P1/P2/P3]** `ruta/archivo:línea` — descripción verificable y cambio recomendado.

### Cumple
- Requisitos confirmados con evidencia.

### Validación
- Diff: ...
- Tests/checks: ...
- Contexto faltante o limitaciones: ...
```

## Ejemplo de invocación

> Revisa `https://github.com/acme/restaurant-platform/pull/42` contra el contexto de Brasaland adjunto. Valida nombres de KPI y destino, no modifiques la PR, y dame hallazgos priorizados.