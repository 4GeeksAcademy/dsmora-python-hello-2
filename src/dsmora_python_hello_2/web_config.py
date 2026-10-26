import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    environment: str = os.getenv("APP_ENV", "development")
    codespaces: bool = os.getenv("CODESPACES", "false").lower() == "true"
    origin: str = os.getenv("APP_ORIGIN", "http://localhost:3000")
    issuer: str = os.getenv("JWT_ISSUER", "http://backend:8000")
    jwks_url: str = os.getenv("JWKS_URL", "http://backend:8000/.well-known/jwks.json")
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
    agent_url: str = os.getenv("AGENT_URL", "http://agent:8001")
    data_dir: Path = Path(os.getenv("DATA_DIR", "/data"))
    approval_db: Path = Path(
        os.getenv("APPROVAL_DB_FILE", str(data_dir / "agent-approvals.sqlite"))
    )
    private_key: Path = Path(os.getenv("JWT_KEY_FILE", "/data/jwt.pem"))
    demo_password_file: Path = Path(os.getenv("DEMO_PASSWORD_FILE", "/run/secrets/demo_password"))
    demo_enabled: bool = os.getenv("SEED_DEMO_USER", "false").lower() == "true"
    session_ttl: int = 3600
    delegated_ttl: int = 660
    job_timeout: int = 600
    consent_timeout: int = 90
    history_ttl: int = 3600
    max_plans: int = 50

    def validate(self) -> None:
        if self.environment != "development":
            if self.demo_enabled:
                raise RuntimeError("La cuenta demo solo se permite en desarrollo.")
            if not self.origin.startswith("https://"):
                raise RuntimeError("Fuera de desarrollo se requiere APP_ORIGIN HTTPS.")


settings = Settings()
