import httpx
from config import PIPEDRIVE_BASE_URL, PIPEDRIVE_API_TOKEN


def _get(path: str, params: dict = None) -> dict:
    params = params or {}
    params["api_token"] = PIPEDRIVE_API_TOKEN
    r = httpx.get(f"{PIPEDRIVE_BASE_URL}{path}", params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def _post(path: str, json: dict) -> dict:
    r = httpx.post(
        f"{PIPEDRIVE_BASE_URL}{path}",
        params={"api_token": PIPEDRIVE_API_TOKEN},
        json=json,
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def _put(path: str, json: dict) -> dict:
    r = httpx.put(
        f"{PIPEDRIVE_BASE_URL}{path}",
        params={"api_token": PIPEDRIVE_API_TOKEN},
        json=json,
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def search_deals(term: str, status: str = None, limit: int = 10) -> dict:
    params = {"term": term, "limit": limit}
    if status:
        params["status"] = status
    data = _get("/deals/search", params)
    items = data.get("data", {}).get("items", []) if data.get("data") else []
    return [
        {
            "id": i["item"]["id"],
            "title": i["item"]["title"],
            "status": i["item"]["status"],
            "value": i["item"].get("value"),
            "currency": i["item"].get("currency"),
            "stage": i["item"].get("stage", {}).get("name") if i["item"].get("stage") else None,
            "owner": i["item"].get("owner", {}).get("name") if i["item"].get("owner") else None,
        }
        for i in items
    ]


def get_deal(deal_id: int) -> dict:
    data = _get(f"/deals/{deal_id}")
    d = data.get("data", {})
    return {
        "id": d.get("id"),
        "title": d.get("title"),
        "status": d.get("status"),
        "value": d.get("value"),
        "currency": d.get("currency"),
        "stage": d.get("stage_id"),
        "owner": d.get("owner_name"),
        "org_name": d.get("org_name"),
        "person_name": d.get("person_name"),
        "expected_close_date": d.get("expected_close_date"),
        "add_time": d.get("add_time"),
        "update_time": d.get("update_time"),
    }


def update_deal(deal_id: int, fields: dict) -> dict:
    data = _put(f"/deals/{deal_id}", fields)
    d = data.get("data", {})
    return {"success": data.get("success"), "id": d.get("id"), "title": d.get("title"), "status": d.get("status")}


def search_persons(term: str, limit: int = 10) -> dict:
    data = _get("/persons/search", {"term": term, "limit": limit})
    items = data.get("data", {}).get("items", []) if data.get("data") else []
    return [
        {
            "id": i["item"]["id"],
            "name": i["item"]["name"],
            "emails": [e["value"] for e in i["item"].get("emails", [])],
            "phones": [p["value"] for p in i["item"].get("phones", [])],
            "org_name": i["item"].get("organization", {}).get("name") if i["item"].get("organization") else None,
        }
        for i in items
    ]


def search_organizations(term: str, limit: int = 10) -> dict:
    data = _get("/organizations/search", {"term": term, "limit": limit})
    items = data.get("data", {}).get("items", []) if data.get("data") else []
    return [
        {
            "id": i["item"]["id"],
            "name": i["item"]["name"],
            "address": i["item"].get("address"),
            "open_deals_count": i["item"].get("open_deals_count"),
        }
        for i in items
    ]


def create_note(content: str, deal_id: int = None, person_id: int = None, org_id: int = None) -> dict:
    payload = {"content": content}
    if deal_id:
        payload["deal_id"] = deal_id
    if person_id:
        payload["person_id"] = person_id
    if org_id:
        payload["org_id"] = org_id
    data = _post("/notes", payload)
    return {"success": data.get("success"), "id": data.get("data", {}).get("id")}


def create_activity(
    subject: str,
    type: str,
    due_date: str = None,
    due_time: str = None,
    deal_id: int = None,
    person_id: int = None,
    note: str = None,
) -> dict:
    payload = {"subject": subject, "type": type}
    if due_date:
        payload["due_date"] = due_date
    if due_time:
        payload["due_time"] = due_time
    if deal_id:
        payload["deal_id"] = deal_id
    if person_id:
        payload["person_id"] = person_id
    if note:
        payload["note"] = note
    data = _post("/activities", payload)
    return {"success": data.get("success"), "id": data.get("data", {}).get("id")}


def list_activities(done: int = 0, limit: int = 10) -> list:
    data = _get("/activities", {"done": done, "limit": limit})
    items = data.get("data") or []
    return [
        {
            "id": a.get("id"),
            "subject": a.get("subject"),
            "type": a.get("type"),
            "due_date": a.get("due_date"),
            "due_time": a.get("due_time"),
            "deal_title": a.get("deal_title"),
            "person_name": a.get("person_name"),
            "done": a.get("done"),
        }
        for a in items
    ]
