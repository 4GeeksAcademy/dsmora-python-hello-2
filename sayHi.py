#!/usr/bin/env python3
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.blocking import BlockingScheduler
## crontab 
## apscheduler

def hora_espanola():
    ahora_utc = datetime.now(timezone.utc)
    fecha = (ahora_utc.month, ahora_utc.day)
    inicio_verano = (5, 20)
    inicio_invierno = (10, 24)
    es_verano = fecha >= inicio_verano and fecha < inicio_invierno
    diferencia_horaria = timedelta(hours=2 if es_verano else 1)

    return ahora_utc + diferencia_horaria


def sayHi():
    ahora = hora_espanola().strftime("%Y-%m-%d %H:%M:%S")
    mensaje = f"[{ahora}] ¡Hola! Saludo automático desde Python y APScheduler en Codespaces.\n"
    
    with open("/workspaces/dsmora-python-hello-2/saludo_cron.log", "a", encoding="utf-8") as f:
        f.write(mensaje)
    
    print(mensaje.strip())

if __name__ == "__main__":
    scheduler = BlockingScheduler()
    scheduler.add_job(sayHi, "interval", minutes=1, id="saludo-cada-minuto")

    print("APScheduler iniciado: el saludo se ejecutará cada minuto.")
    scheduler.start()
