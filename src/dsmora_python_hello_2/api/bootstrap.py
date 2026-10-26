import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from ..web_config import settings


def initialize_key() -> None:
    if settings.private_key.exists():
        return
    if settings.environment != "development":
        raise RuntimeError("Configura una clave de firma privada antes de iniciar.")
    settings.private_key.parent.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    encoded = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    fd = os.open(settings.private_key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as target:
        target.write(encoded)
