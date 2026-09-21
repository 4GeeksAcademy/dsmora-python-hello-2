import redis
import json

            # Message Broker 
## Productor - Cola - Consumidor
                                    
r = redis.Redis(host="localhost", port=6379, decode_responses=True)

QUEUE = "tasks"

def produce(task: dict):
    task_json = json.dumps(task)
    r.rpush(QUEUE, task_json)


def consume(timeout: int = 30):
    result = r.blpop(QUEUE, timeout=timeout)
    if result:
        _, task_json = result
        return json.loads(task_json)
    return None

if __name__ == "__main__":
    print("Hola desde Python con uv")
