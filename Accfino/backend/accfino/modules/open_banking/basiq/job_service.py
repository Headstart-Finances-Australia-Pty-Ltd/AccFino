import requests
from accfino.modules.open_banking.basiq.auth import get_access_token

BASE_URL = "https://au-api.basiq.io"


def get_job_status(job_id: str):
    """
    Retrieve the status of a Basiq job.
    Returns job details including step status (pending, in-progress, success, failed).
    """
    if not job_id:
        raise ValueError("job_id must be provided")

    token = get_access_token()

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    res = requests.get(f"{BASE_URL}/jobs/{job_id}", headers=headers, timeout=60)
    res.raise_for_status()
    return res.json()


def get_accounts(user_id: str):
    """
    Retrieve all accounts for a user after successful connection.
    """
    if not user_id:
        raise ValueError("user_id must be provided")

    token = get_access_token()

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    res = requests.get(f"{BASE_URL}/users/{user_id}/accounts", headers=headers, timeout=60)
    res.raise_for_status()
    return res.json().get("data", [])


def get_account_details(account_id: str):
    """
    Retrieve detailed account information for a specific account.
    """
    if not account_id:
        raise ValueError("account_id must be provided")

    token = get_access_token()

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    res = requests.get(f"{BASE_URL}/accounts/{account_id}", headers=headers, timeout=60)
    res.raise_for_status()
    return res.json()


def get_transactions(account_id: str, from_date: str = None, to_date: str = None):
    """
    Retrieve transactions for a specific account.

    from_date / to_date (YYYY-MM-DD, inclusive) limit the period pulled from Basiq
    (filter on transaction.postDate). Follows Basiq's `links.next` paging so a long
    period isn't silently cut off at the first page.
    """
    if not account_id:
        raise ValueError("account_id must be provided")

    token = get_access_token()

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    params = {"limit": 500}
    filters = []
    if from_date:
        filters.append(f"transaction.postDate.gteq('{from_date}')")
    if to_date:
        filters.append(f"transaction.postDate.lteq('{to_date}')")
    if filters:
        params["filter"] = ",".join(filters)

    out = []
    url = f"{BASE_URL}/accounts/{account_id}/transactions"
    for _ in range(200):  # hard stop against a runaway next-link loop
        res = requests.get(url, headers=headers, params=params, timeout=60)
        res.raise_for_status()
        body = res.json()
        out.extend(body.get("data", []))
        url = (body.get("links") or {}).get("next")
        if not url:
            break
        params = None  # the next link already carries the query string
    return out


def get_transaction(user_id: str, transaction_id: str):
    """
    Retrieve a single transaction for a specific user.
    """
    if not user_id:
        raise ValueError("user_id must be provided")
    if not transaction_id:
        raise ValueError("transaction_id must be provided")

    token = get_access_token()

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    res = requests.get(
        f"{BASE_URL}/users/{user_id}/transactions/{transaction_id}",
        headers=headers,
        timeout=60,
    )
    res.raise_for_status()
    return res.json()


def create_statement(user_id: str, institution_id: str, file_name: str, file_bytes: bytes, content_type: str):
    """
    Create a statement upload job for a user.
    """
    if not user_id:
        raise ValueError("user_id must be provided")
    if not institution_id:
        raise ValueError("institution_id must be provided")
    if not file_name or not file_bytes:
        raise ValueError("statement file must be provided")

    token = get_access_token()

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    data = {
        "institutionId": institution_id,
    }

    files = {
        "statement": (file_name, file_bytes, content_type or "application/octet-stream"),
    }

    res = requests.post(
        f"{BASE_URL}/users/{user_id}/statements",
        headers=headers,
        data=data,
        files=files,
        timeout=120,
    )
    res.raise_for_status()
    return res.json()

