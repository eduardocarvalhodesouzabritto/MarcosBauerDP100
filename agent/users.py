import json
import logging
import os

logger = logging.getLogger(__name__)

_KEYS_FILE = os.path.join(os.path.dirname(__file__), "user_keys.json")


def _load_keys() -> dict:
    try:
        with open(_KEYS_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def get_pipedrive_key(user_id: int) -> str | None:
    return _load_keys().get(str(user_id))


def set_pipedrive_key(user_id: int, key: str):
    keys = _load_keys()
    keys[str(user_id)] = key
    with open(_KEYS_FILE, "w") as f:
        json.dump(keys, f, indent=2)


def is_allowed(user_id: int) -> bool:
    raw = os.environ.get("ALLOWED_USERS", "").strip()
    if not raw:
        logger.warning("ALLOWED_USERS não configurado — qualquer pessoa pode usar o bot")
        return True
    allowed = {int(uid.strip()) for uid in raw.split(",") if uid.strip()}
    return user_id in allowed
