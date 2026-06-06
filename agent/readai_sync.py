"""
Read.ai → Pipedrive automatic sync service.

Connects to Read.ai via MCP (SSE) to get new meetings, then creates
meeting activities in Pipedrive using the admin API key.
Notifies via Telegram when a meeting is synced or needs manual attention.
"""

import asyncio
import json
import logging
import os
from typing import Any

import httpx
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.sse import sse_client

load_dotenv()

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

READAI_MCP_URL = "https://api.read.ai/mcp"
READAI_API_KEY = os.environ.get("READAI_API_KEY", "")
PIPEDRIVE_ADMIN_KEY = os.environ.get("PIPEDRIVE_ADMIN_KEY", "")
PIPEDRIVE_DOMAIN = os.environ.get("PIPEDRIVE_COMPANY_DOMAIN", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
NOTIFY_CHAT_ID = os.environ.get("NOTIFY_CHAT_ID", "")
SYNC_INTERVAL = int(os.environ.get("READAI_SYNC_INTERVAL", "300"))

PROCESSED_FILE = os.path.join(os.path.dirname(__file__), "processed_meetings.json")
PIPEDRIVE_BASE = f"https://{PIPEDRIVE_DOMAIN}.pipedrive.com/api/v1"


# ── Processed meetings tracker ─────────────────────────────────────────────

def load_processed() -> set:
    try:
        with open(PROCESSED_FILE) as f:
            return set(json.load(f))
    except FileNotFoundError:
        return set()


def save_processed(ids: set):
    with open(PROCESSED_FILE, "w") as f:
        json.dump(list(ids), f)


# ── Read.ai via MCP ────────────────────────────────────────────────────────

async def call_tool(session: ClientSession, name: str, args: dict) -> Any:
    result = await session.call_tool(name, args)
    text = "\n".join(
        block.text if hasattr(block, "text") else str(block)
        for block in result.content
    )
    try:
        return json.loads(text)
    except Exception:
        return text


async def get_meetings(session: ClientSession, tools: list[str]) -> list:
    # Try common tool names for listing meetings
    for name in ("list_meetings", "get_meetings", "meetings_list", "listMeetings"):
        if name in tools:
            result = await call_tool(session, name, {"limit": 50})
            if isinstance(result, list):
                return result
            if isinstance(result, dict):
                for key in ("meetings", "data", "items", "results"):
                    if key in result:
                        return result[key]
    return []


async def get_meeting_detail(session: ClientSession, tools: list[str], meeting_id: str) -> dict:
    for name in ("get_meeting", "meeting_details", "getMeeting", "get_meeting_details"):
        if name in tools:
            result = await call_tool(session, name, {"meeting_id": meeting_id, "id": meeting_id})
            if isinstance(result, dict):
                return result
    return {}


async def get_summary(session: ClientSession, tools: list[str], meeting_id: str) -> dict:
    for name in ("get_meeting_summary", "meeting_summary", "getMeetingSummary", "get_summary"):
        if name in tools:
            result = await call_tool(session, name, {"meeting_id": meeting_id, "id": meeting_id})
            if isinstance(result, dict):
                return result
    return {}


# ── Summary text formatter ─────────────────────────────────────────────────

def build_note(meeting: dict, detail: dict, summary: dict) -> str:
    merged = {**meeting, **detail, **summary}
    parts = []

    def extract(obj, *keys):
        for k in keys:
            v = obj.get(k, "")
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, dict):
                for sub in ("text", "content", "value"):
                    if v.get(sub, "").strip():
                        return v[sub].strip()
        return ""

    def extract_list(obj, *keys):
        for k in keys:
            v = obj.get(k)
            if isinstance(v, list) and v:
                return v
        return []

    overview = extract(merged, "overview", "gist", "summary", "description", "abstract")
    if overview:
        parts.append(f"*Resumo:*\n{overview}")

    key_points = extract_list(merged, "key_points", "highlights", "outline", "topics")
    if key_points:
        lines = [f"• {_item_text(i)}" for i in key_points[:8]]
        parts.append("*Pontos-chave:*\n" + "\n".join(lines))

    action_items = extract_list(merged, "action_items", "actionItems", "tasks", "next_steps")
    if action_items:
        lines = [f"• {_item_text(i)}" for i in action_items[:10]]
        parts.append("*Atividades previstas:*\n" + "\n".join(lines))

    return "\n\n".join(parts) or "Reunião registrada automaticamente via Read.ai."


def _item_text(item) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return item.get("text") or item.get("content") or item.get("title") or str(item)
    return str(item)


# ── Pipedrive REST API ─────────────────────────────────────────────────────

async def find_deal(client: httpx.AsyncClient, title: str, participants: list) -> dict | None:
    emails = [p.get("email", "") for p in participants if p.get("email")]

    for email in emails[:5]:
        try:
            r = await client.get(
                f"{PIPEDRIVE_BASE}/persons/search",
                params={"term": email, "api_token": PIPEDRIVE_ADMIN_KEY, "fields": "email"},
                timeout=10.0,
            )
            items = r.json().get("data", {}).get("items", [])
            if items:
                pid = items[0]["item"]["id"]
                dr = await client.get(
                    f"{PIPEDRIVE_BASE}/persons/{pid}/deals",
                    params={"api_token": PIPEDRIVE_ADMIN_KEY, "status": "open", "limit": 1},
                    timeout=10.0,
                )
                deals = dr.json().get("data") or []
                if deals:
                    return deals[0]
        except Exception:
            continue

    for word in [w for w in title.split() if len(w) > 3][:4]:
        try:
            r = await client.get(
                f"{PIPEDRIVE_BASE}/deals/search",
                params={"term": word, "api_token": PIPEDRIVE_ADMIN_KEY, "limit": 1},
                timeout=10.0,
            )
            items = r.json().get("data", {}).get("items", [])
            if items:
                return items[0]["item"]
        except Exception:
            continue

    return None


async def create_activity(client: httpx.AsyncClient, deal: dict, title: str, note: str) -> bool:
    try:
        r = await client.post(
            f"{PIPEDRIVE_BASE}/activities",
            params={"api_token": PIPEDRIVE_ADMIN_KEY},
            json={"subject": title, "type": "meeting", "deal_id": deal.get("id"), "done": 1, "note": note[:4000]},
            timeout=10.0,
        )
        return r.status_code in (200, 201)
    except Exception as e:
        logger.error("Erro ao criar atividade: %s", e)
        return False


# ── Telegram notification ──────────────────────────────────────────────────

async def notify(text: str):
    if not NOTIFY_CHAT_ID or not TELEGRAM_BOT_TOKEN:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": NOTIFY_CHAT_ID, "text": text, "parse_mode": "Markdown"},
                timeout=10.0,
            )
    except Exception as e:
        logger.warning("Telegram notify error: %s", e)


# ── Main sync ──────────────────────────────────────────────────────────────

async def sync_once():
    processed = load_processed()

    async with sse_client(
        READAI_MCP_URL,
        headers={"Authorization": f"Bearer {READAI_API_KEY}"},
    ) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_result = await session.list_tools()
            tool_names = [t.name for t in tools_result.tools]
            logger.info("Read.ai MCP tools: %s", tool_names)

            meetings = await get_meetings(session, tool_names)
            logger.info("%d reuniões encontradas", len(meetings))

            async with httpx.AsyncClient() as http:
                for meeting in meetings:
                    mid = str(
                        meeting.get("id") or meeting.get("meetingId") or meeting.get("meeting_id", "")
                    )
                    if not mid or mid in processed:
                        continue

                    title = meeting.get("title") or meeting.get("name") or f"Reunião {mid}"
                    logger.info("Processando: %s", title)

                    try:
                        detail = await get_meeting_detail(session, tool_names, mid)
                        summary = await get_summary(session, tool_names, mid)
                        merged = {**meeting, **detail}

                        participants = (
                            merged.get("participants")
                            or merged.get("attendees")
                            or []
                        )
                        note = build_note(meeting, detail, summary)
                        deal = await find_deal(http, title, participants)

                        if deal:
                            ok = await create_activity(http, deal, title, note)
                            if ok:
                                await notify(
                                    f"✅ *Reunião sincronizada*\n\n"
                                    f"📋 {title}\n"
                                    f"🤝 Deal: {deal.get('title', deal.get('name', 'N/A'))}"
                                )
                            else:
                                await notify(f"⚠️ Erro ao criar atividade no Pipedrive\n📋 {title}")
                        else:
                            names = ", ".join(
                                p.get("name") or p.get("email") or "?"
                                for p in participants[:5]
                            )
                            await notify(
                                f"⚠️ *Sem deal correspondente*\n\n"
                                f"📋 {title}\n"
                                f"👥 {names or 'Sem participantes'}\n\n"
                                f"Identifique o deal e me pergunte para registrar manualmente."
                            )

                        processed.add(mid)
                        save_processed(processed)

                    except Exception:
                        logger.exception("Erro ao processar reunião %s", mid)


async def main():
    if not READAI_API_KEY:
        raise RuntimeError("READAI_API_KEY não configurado no .env")
    if not PIPEDRIVE_ADMIN_KEY:
        raise RuntimeError("PIPEDRIVE_ADMIN_KEY não configurado no .env")

    logger.info("Read.ai sync iniciado — intervalo: %ds", SYNC_INTERVAL)
    await notify("🔄 *Read.ai sync iniciado* — verificando reuniões a cada 5 minutos.")

    while True:
        try:
            await sync_once()
        except Exception:
            logger.exception("Erro no ciclo de sync")
        await asyncio.sleep(SYNC_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
