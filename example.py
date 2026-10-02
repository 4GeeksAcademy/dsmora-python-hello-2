from time import sleep
from datetime import timedelta

from prefect import flow, task
from prefect.cache_policies import INPUTS


@task(cache_policy=INPUTS, cache_expiration=timedelta(hours=1), persist_result=True)
def sum_task(a, b):
    sleep(3)
    return a + b

@flow
def iterator(values):
    for item in values:
        print(sum_task(item, item))


if __name__ == "__main__":
    # Solo las primeras cinco llamadas tienen entradas únicas y ejecutan sleep.
    # El resto reutiliza el resultado persistido en la caché de Prefect.
    iterator([1, 2, 3, 4, 5] * 12)
