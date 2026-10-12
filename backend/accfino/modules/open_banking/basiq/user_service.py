# backend/open_banking/user_service.py
import sys
from pathlib import Path

import requests

if False:                                    # stand-alone execution is not supported any more; run as part of the accfino package
    pass

    from accfino.modules.open_banking.basiq.auth import get_access_token
else:
    from accfino.modules.open_banking.basiq.auth import get_access_token

BASE_URL = "https://au-api.basiq.io"

def create_user_basiq_object(email, mobile):
    token = get_access_token()

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = {
        "email": email,
        "mobile": mobile
    }

    res = requests.post(f"{BASE_URL}/users", json=payload, headers=headers)
    print("res",res.json())
    res.raise_for_status()
    return res.json()["id"]



def get_user(user_id):
    token = get_access_token()

    headers = {
        "Authorization": f"Bearer {token}",
        "accept": "application/json"
    }

    res = requests.get(
        f"{BASE_URL}/users/{user_id}",
        headers=headers
    )

    res.raise_for_status()
    return res.json()