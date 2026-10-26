import os
import secrets
from threading import RLock

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from tinydb import Query, TinyDB

from ..web_config import settings


class Users:
    def __init__(self) -> None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = TinyDB(settings.data_dir / "users.json")
        self.lock = RLock()
        self.hasher = PasswordHasher()
        self.dummy_hash = self.hasher.hash(secrets.token_urlsafe(32))

    def seed(self) -> None:
        settings.validate()
        if not settings.demo_enabled:
            return
        with self.lock:
            if self.db.get(Query().email == "test@test.com"):
                return
        password = (
            settings.demo_password_file.read_text().strip()
            if settings.demo_password_file.is_file()
            else os.getenv("DEMO_USER_PASSWORD", "")
        )
        if len(password) < 8:
            raise RuntimeError("La contrasena demo debe tener al menos 8 caracteres.")
        self.create("test@test.com", password)

    def create(self, email: str, password: str) -> bool:
        email = email.strip().casefold()
        with self.lock:
            if self.db.get(Query().email == email):
                return False
            self.db.insert({
                "id": secrets.token_urlsafe(24), "email": email,
                "password_hash": self.hasher.hash(password),
            })
        return True

    def authenticate(self, email: str, password: str) -> dict[str, str] | None:
        with self.lock:
            user = self.db.get(Query().email == email.strip().casefold())
            try:
                self.hasher.verify(user["password_hash"] if user else self.dummy_hash, password)
            except VerifyMismatchError:
                return None
            if user and self.hasher.check_needs_rehash(user["password_hash"]):
                self.db.update(
                    {"password_hash": self.hasher.hash(password)}, doc_ids=[user.doc_id]
                )
        return {"id": user["id"], "email": user["email"]} if user else None
