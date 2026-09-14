# Ejecucion programada con cron y APScheduler

## Cron

Inicialmente se utilizo esta entrada en el `crontab`:

```cron
* * * * * /usr/bin/python3 /workspaces/dsmora-python-hello-2/sayHi.py
```

Los cinco campos tienen este significado:

```text
minuto hora dia-del-mes mes dia-de-la-semana
```

El valor `*` significa cualquier valor. Por eso `* * * * *` representa una ejecucion cada minuto, todos los dias y todos los meses.

La entrada de cron se retiro cuando `sayHi.py` paso a usar APScheduler. Mantener ambas configuraciones activas iniciaria un nuevo proceso cada minuto y produciria varios schedulers ejecutandose en paralelo.

## APScheduler

La dependencia se declara en `requirements.txt` y se instala con:

```bash
python3 -m pip install -r requirements.txt
```

El script crea un `BlockingScheduler` y programa `sayHi` con un intervalo de un minuto:

```python
scheduler.add_job(sayHi, "interval", minutes=1, id="saludo-cada-minuto")
scheduler.start()
```

APScheduler necesita que el proceso permanezca activo. Para iniciarlo:

```bash
python3 /workspaces/dsmora-python-hello-2/sayHi.py
```

Para dejarlo ejecutandose en segundo plano:

```bash
nohup python3 /workspaces/dsmora-python-hello-2/sayHi.py \
  >> /workspaces/dsmora-python-hello-2/apscheduler.log 2>&1 &
```

Las ejecuciones se guardan en `saludo_cron.log`. La salida del proceso se puede revisar en `apscheduler.log` cuando se utiliza el comando con `nohup`.

## Hora de Espana

El script calcula la hora a partir de UTC para no depender de la configuracion horaria del contenedor:

- Del 20 de mayo al 23 de octubre, ambos incluidos: UTC+2, horario de verano.
- Del 24 de octubre al 19 de mayo: UTC+1, horario de invierno.

Estas fechas son las reglas personalizadas solicitadas para este ejercicio y no el calendario oficial habitual de cambio horario en Espana.