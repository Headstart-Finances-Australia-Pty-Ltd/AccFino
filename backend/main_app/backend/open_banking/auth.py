import os
from time import time
import requests
from dotenv import load_dotenv
from pathlib import Path
from backend.utils.logger import logger

# Load environment variables from standard .env and HSLedger/basiqenv.
load_dotenv()
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / "basiqenv")

def _cfg() -> dict:
    """Live Basiq settings: server environment first, else what the AccFino administrator saved in Admin Console > Open Banking."""
    try:
        from accfino_core.openbanking_setup import basiq_config
        return basiq_config()
    except Exception:
        return {"base_url": (os.getenv("BASIQ_BASE_URL") or "https://au-api.basiq.io").rstrip("/"), "api_key": os.getenv("BASIQ_API_KEY"),
                "version": os.getenv("BASIQ_VERSION") or "3.0", "source": "environment"}

ACCESS_TOKEN = None
TOKEN_EXPIRY = 0  # epoch timestamp
_TOKEN_KEY = None  # the API key the cached token was issued for

def _require_basiq_config():
    c = _cfg()
    if not c["api_key"]:
        raise ValueError("Basiq is not set up yet. The AccFino administrator can add the API key in Admin Console > Open Banking.")
    return f"{c['base_url']}/token"

def get_access_token():
    global ACCESS_TOKEN, TOKEN_EXPIRY, _TOKEN_KEY
    basiq_token_url = _require_basiq_config()
    if _TOKEN_KEY != _cfg()["api_key"]:                      # the key was replaced: never reuse a token issued for the old one
        ACCESS_TOKEN, TOKEN_EXPIRY = None, 0

    current_time = time()

    # Reuse token if still valid (with buffer)
    if ACCESS_TOKEN and current_time < TOKEN_EXPIRY:
        logger.info("Reusing Basiq access token (expires at %s)", TOKEN_EXPIRY)
        return ACCESS_TOKEN
    
    # Otherwise, fetch new token
    headers = {
        "accept": "application/json",
        "basiq-version": _cfg()["version"],
        "content-type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {_cfg()['api_key']}"
    }

    logger.info("Requesting new Basiq access token")
    response = requests.post(basiq_token_url, headers=headers)
    response.raise_for_status()

    data = response.json()

    ACCESS_TOKEN = data["access_token"]
    _TOKEN_KEY = _cfg()["api_key"]

    # token valid for 60 min - refresh at 55 min
    TOKEN_EXPIRY = current_time + (55 * 60)
    logger.info("New Basiq access token acquired (expires at %s)", TOKEN_EXPIRY)

    return ACCESS_TOKEN


def get_client_access_token(user_id: str):
    basiq_token_url = _require_basiq_config()

    if not user_id:
        raise ValueError("user_id must be provided")

    headers = {
        "accept": "application/json",
        "basiq-version": _cfg()["version"],
        "content-type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {_cfg()['api_key']}",
    }

    data = {
        "scope": "CLIENT_ACCESS",
        "userId": user_id,
    }

    logger.info("Requesting Basiq client access token for user %s", user_id)
    response = requests.post(basiq_token_url, headers=headers, data=data)
    response.raise_for_status()

    return response.json()["access_token"]

def create_auth_link(user_id, mobile: str | None = None):
    _require_basiq_config()
    auth_url = f"{_cfg()['base_url']}/users/{user_id}/auth_link"
    payload = {"mobile": mobile} if mobile else {}
    
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": f"Bearer {get_access_token()}"
    }
    
    response = requests.post(auth_url, json=payload, headers=headers)
    response.raise_for_status()
    return response.json()


def get_auth_link(user_id):
    _require_basiq_config()
    auth_url = f"{_cfg()['base_url']}/users/{user_id}/auth_link"

    headers = {
        "accept": "application/json",
        "authorization": f"Bearer {get_access_token()}"
    }

    response = requests.get(auth_url, headers=headers)
    response.raise_for_status()
    return response.json()

if __name__ == "__main__":
    token = get_access_token()
    print(TOKEN_EXPIRY)
    print("Access Token:", token)