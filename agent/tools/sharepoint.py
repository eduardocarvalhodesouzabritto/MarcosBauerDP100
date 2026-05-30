import httpx
import msal
from config import (
    AZURE_CLIENT_ID,
    AZURE_CLIENT_SECRET,
    AZURE_TENANT_ID,
    SHAREPOINT_SITE_ID,
    GRAPH_BASE_URL,
)

_token_cache: dict = {}


def _get_token() -> str:
    app = msal.ConfidentialClientApplication(
        AZURE_CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{AZURE_TENANT_ID}",
        client_credential=AZURE_CLIENT_SECRET,
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        raise RuntimeError(f"Falha ao obter token Azure: {result.get('error_description')}")
    return result["access_token"]


def _headers() -> dict:
    return {"Authorization": f"Bearer {_get_token()}", "Accept": "application/json"}


def search_sharepoint(query: str, limit: int = 10) -> list:
    payload = {
        "requests": [
            {
                "entityTypes": ["driveItem"],
                "query": {"queryString": query},
                "size": limit,
                "fields": ["name", "webUrl", "lastModifiedDateTime", "size", "createdBy"],
            }
        ]
    }
    r = httpx.post(f"{GRAPH_BASE_URL}/search/query", headers=_headers(), json=payload, timeout=20)
    r.raise_for_status()
    data = r.json()
    hits = (
        data.get("value", [{}])[0]
        .get("hitsContainers", [{}])[0]
        .get("hits", [])
    )
    return [
        {
            "name": h.get("resource", {}).get("name"),
            "url": h.get("resource", {}).get("webUrl"),
            "modified": h.get("resource", {}).get("lastModifiedDateTime"),
            "id": h.get("resource", {}).get("id"),
        }
        for h in hits
    ]


def list_files(folder_path: str = None, limit: int = 20) -> list:
    if folder_path:
        path = f"/sites/{SHAREPOINT_SITE_ID}/drive/root:/{folder_path}:/children"
    else:
        path = f"/sites/{SHAREPOINT_SITE_ID}/drive/root/children"
    params = {"$top": limit}
    r = httpx.get(f"{GRAPH_BASE_URL}{path}", headers=_headers(), params=params, timeout=15)
    r.raise_for_status()
    items = r.json().get("value", [])
    return [
        {
            "id": i.get("id"),
            "name": i.get("name"),
            "type": "folder" if "folder" in i else "file",
            "size": i.get("size"),
            "modified": i.get("lastModifiedDateTime"),
            "url": i.get("webUrl"),
        }
        for i in items
    ]


def read_file(item_id: str) -> dict:
    meta_r = httpx.get(
        f"{GRAPH_BASE_URL}/sites/{SHAREPOINT_SITE_ID}/drive/items/{item_id}",
        headers=_headers(),
        timeout=15,
    )
    meta_r.raise_for_status()
    meta = meta_r.json()
    name = meta.get("name", "")
    mime = meta.get("file", {}).get("mimeType", "")

    # Only attempt text extraction for readable formats
    readable_mimes = ("text/", "application/json", "application/xml")
    if not any(mime.startswith(m) for m in readable_mimes) and not name.endswith((".txt", ".csv", ".md")):
        return {
            "name": name,
            "url": meta.get("webUrl"),
            "size": meta.get("size"),
            "mime_type": mime,
            "content": None,
            "note": "Arquivo binário (Word/Excel/PDF). Acesse via URL para visualizar.",
        }

    content_r = httpx.get(
        f"{GRAPH_BASE_URL}/sites/{SHAREPOINT_SITE_ID}/drive/items/{item_id}/content",
        headers=_headers(),
        follow_redirects=True,
        timeout=20,
    )
    content_r.raise_for_status()
    text = content_r.text[:4000]  # Limit to avoid huge payloads
    return {"name": name, "mime_type": mime, "content": text, "truncated": len(content_r.text) > 4000}


def get_file_info(item_id: str) -> dict:
    r = httpx.get(
        f"{GRAPH_BASE_URL}/sites/{SHAREPOINT_SITE_ID}/drive/items/{item_id}",
        headers=_headers(),
        timeout=15,
    )
    r.raise_for_status()
    i = r.json()
    return {
        "id": i.get("id"),
        "name": i.get("name"),
        "size": i.get("size"),
        "modified": i.get("lastModifiedDateTime"),
        "created": i.get("createdDateTime"),
        "created_by": i.get("createdBy", {}).get("user", {}).get("displayName"),
        "modified_by": i.get("lastModifiedBy", {}).get("user", {}).get("displayName"),
        "url": i.get("webUrl"),
        "mime_type": i.get("file", {}).get("mimeType"),
    }
