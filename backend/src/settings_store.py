import base64
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

DATA_DIR = Path(os.environ.get("OCR_DATA_DIR", "/app/data"))


class SettingsStore:
    """Almacén cifrado (Fernet) para la configuración de la IA local."""

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = Path(base_dir) if base_dir else DATA_DIR
        self.key_path = self.base_dir / ".secret_key"
        self.settings_path = self.base_dir / "ai_settings.enc"
        self._fernet = None
        self._raw_key = None

    def _load_key(self):
        self.base_dir.mkdir(parents=True, exist_ok=True)
        if self.key_path.exists():
            key = self.key_path.read_bytes().strip()
            try:
                os.chmod(self.key_path, 0o600)
            except OSError:
                pass
        else:
            key = Fernet.generate_key()
            self.key_path.write_bytes(key)
            os.chmod(self.key_path, 0o600)
        self._fernet = Fernet(key)
        self._raw_key = base64.urlsafe_b64decode(key)
        return key

    @property
    def fernet(self) -> Fernet:
        if self._fernet is None:
            self._load_key()
        return self._fernet

    @property
    def raw_key(self) -> bytes:
        if self._raw_key is None:
            self._load_key()
        return self._raw_key

    def load(self) -> dict | None:
        if not self.settings_path.exists():
            return None
        try:
            raw = self.fernet.decrypt(self.settings_path.read_bytes())
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except (InvalidToken, ValueError, TypeError):
            return None

    def save(self, data: dict) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        token = self.fernet.encrypt(json.dumps(data, ensure_ascii=False).encode())
        self.settings_path.write_bytes(token)
        os.chmod(self.settings_path, 0o600)

    def mask_key(self, key: str) -> str:
        if not key:
            return ""
        if len(key) > 4:
            return "\u2022\u2022\u2022\u2022" + key[-4:]
        return "\u2022\u2022\u2022\u2022"

    def public(self, data: dict | None) -> dict:
        if not data:
            return {
                "configured": False,
                "provider": "local",
                "api_key_masked": "",
                "local_path": "",
                "base_url": "",
                "models_url": "",
                "model": "",
                "updated_at": "",
            }
        return {
            "configured": True,
            "provider": data.get("provider", "local"),
            "api_key_masked": self.mask_key(data.get("api_key", "")),
            "local_path": data.get("local_path", ""),
            "base_url": data.get("base_url", ""),
            "models_url": data.get("models_url", ""),
            "model": data.get("model", ""),
            "updated_at": data.get("updated_at", ""),
        }

    def clear(self) -> bool:
        if self.settings_path.exists():
            self.settings_path.unlink()
            return True
        return False


STORE = SettingsStore()
