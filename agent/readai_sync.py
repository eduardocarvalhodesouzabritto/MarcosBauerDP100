import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta

import httpx
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

READAI_API_KEY = os.environ.get("READAI_API_KEY", "")
PIPEDRIVE_ADMIN_KEY = os.environ.get("PIPEDRIVE_ADMIN_KEY", "")
PIPEDRIVE_DOMAIN = os.environ.get("PIPEDRIVE_COMPANY_DOMAIN", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
NOTIFY_CHAT_ID = os.environ.get("NOTIFY_CHAT_ID", "")
SYNC_INTERVAL = int(os.environ.get("READAI_SYNC_INTERVAL", "300"))  # 5 min default

PROCESSED_FILE = os.path.join(os.path.dirname(__file__), "processed_meetings.json")
READAI_BASE = "https://api.read.ai/api/v1"
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


# ── Read.ai API ────────────────────────────────────────────────────────────

async def readai_get(client: httpx.AsyncClient, path: str, **params) -> dict:
    resp = await client.get(
        f"{READAI_BASE}{path}",
        headers={"Authorization": f"Bearer {READAI_API_KEY}"},
        params=params,
        timeout=20.0,
    )
    resp.raise_for_status()
    return resp.json()


async def get_recent_meetings(client: httpx.AsyncClient) -> list:
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = await readai_get(client, "/meetings", limit=50)
    meetings = data.get("meetings") or data.get("data") or []
    # Filter to last 24h if API doesn't support date filter
    return [m for m in meetings if _is_recent(m, since)]


def _is_recent(meeting: dict, since: str) -> bool:
    for key in ("created_at", "createdAt", "start_time", "startTime", "date"):
        val = meeting.get(key, "")
        if val and val >= since:
            return True
    return True  # Include if no date field found


async def get_meeting_details(client: httpx.AsyncClient, meeting_id: str) -> dict:
    return await readai_get(client, f"/meetings/{meeting_id}")


async def get_meeting_summary(client: httpx.AsyncClient, meeting_id: str) -> dict:
    try:
        return await readai_get(client, f"/meetings/{meeting_id}/summaries")
    except Exception:
        return {}


# ── Summary formatter ──────────────────────────────────────────────────────

def format_summary(meeting: dict, summary: dict) -> str:
    parts = []

    # Overview / gist
    for key in ("overview", "gist", "summary", "description"):
        text = _extract_text(summary, key) or _extract_text(meeting, key)
        if text:
            parts.append(f"*Resumo:*\n{text}")
            break

    # Key points / outline
    for key in ("key_points", "outline", "highlights", "topics"):
        items = summary.get(key) or meeting.get(key) or []
        if isinstance(items, list) and items:
            lines = []
            for item in items[:8]:
                lines.append(f"• {_item_text(item)}")
            parts.append("*Pontos-chave:*\n" + "\n".join(lines))
            break

    # Action items
    for key in ("action_items", "actionItems", "tasks", "next_steps"):
        items = summary.get(key) or meeting.get(key) or []
        if isinstance(items, list) and items:
            lines = []
            for item in items[:10]:
                lines.append(f"• {_item_text(item)}")
            parts.append("*Atividades previstas:*\n" + "\n".join(lines))
            break

    if not parts:
        return f"Reunião registrada automaticamente via Read.ai."

    return "\n\n".join(parts)


def _extract_text(obj: dict, key: str) -> str:
    val = obj.get(key, "")
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, dict):
        return val.get("text", val.get("content", "")).strip()
    return ""


def _item_text(item) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return item.get("text") or item.get("content") or item.get("title") or str(item)
    return str(item)


# ── Pipedrive API ──────────────────────────────────────────────────────────

async def find_best_deal(client: httpx.AsyncClient, title: str, participants: list) -> dict | None:
    emails = [p.get("email", "") for p in participants if p.get("email")]

    # 1. Search by participant email → person → open deals
    for email in emails[:5]:
        try:
            resp = await client.get(
                f"{PIPEDRIVE_BASE}/persons/search",
                params={"term": email, "api_token": PIPEDRIVE_ADMIN_KEY, "fields": "email"},
                timeout=10.0,
            )
            items = resp.json().get("data", {}).get("items", [])
            if items:
                person_id = items[0]["item"]["id"]
                deals_resp = await client.get(
                    f"{PIPEDRIVE_BASE}/persons/{person_id}/deals",
                    params={"api_token": PIPEDRIVE_ADMIN_KEY, "status": "open", "limit": 1},
                    timeout=10.0,
                )
                deals = deals_resp.json().get("data") or []
                if deals:
                    return deals[0]
        except Exception:
            continue

    # 2. Search by significant words in the meeting title
    words = [w for w in title.split() if len(w) > 3][:4]
    for word in words:
        try:
            resp = await client.get(
                f"{PIPEDRIVE_BASE}/deals/search",
                params={"term": word, "api_token": PIPEDRIVE_ADMIN_KEY, "limit": 1},
                timeout=10.0,
            )
            items = resp.json().get("data", {}).get("items", [])
            if items:
                return items[0]["item"]
        except Exception:
            continue

    return None


async def create_activity(client: httpx.AsyncClient, deal: dict, title: str, note: str) -> bool:
    try:
        resp = await client.post(
            f"{PIPEDRIVE_BASE}/activities",
            params={"api_token": PIPEDRIVE_ADMIN_KEY},
            json={
                "subject": title,
                "type": "meeting",
                "deal_id": deal.get("id"),
                "done": 1,
                "note": note[:4000],
            },
            timeout=10.0,
        )
        return resp.status_code in (200, 201)
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
        logger.warning("Erro ao notificar Telegram: %s", e)


# ── Main sync loop ─────────────────────────────────────────────────────────

async def sync_once():
    processed = load_processed()

    async with httpx.AsyncClient() as client:
        try:
            meetings = await get_recent_meetings(client)
            logger.info("%d reuniões encontradas no Read.ai", len(meetings))
        except Exception as e:
            logger.error("Erro ao buscar reuniões: %s", e)
            return

        for meeting in meetings:
            meeting_id = str(
                meeting.get("id") or meeting.get("meetingId") or meeting.get("meeting_id", "")
            )
            if not meeting_id or meeting_id in processed:
                continue

            title = meeting.get("title") or meeting.get("name") or f"Reunião {meeting_id}"
            logger.info("Processando: %s", title)

            try:
                details = await get_meeting_details(client, meeting_id)
                summary_data = await get_meeting_summary(client, meeting_id)

                # Merge details with top-level meeting data
                full = {**meeting, **details}
                participants = (
                    full.get("participants")
                    or full.get("attendees")
                    or []
                )

                summary_text = format_summary(full, summary_data)
                deal = await find_best_deal(client, title, participants)

                if deal:
                    success = await create_activity(client, deal, title, summary_text)
                    if success:
                        await notify(
                            f"✅ *Reunião sincronizada com Pipedrive*\n\n"
                            f"📋 {title}\n"
                            f"🤝 Deal: {deal.get('title', deal.get('name', 'N/A'))}"
                        )
                        logger.info("Sincronizado: '%s' → deal '%s'", title, deal.get("title"))
                    else:
                        await notify(f"⚠️ Erro ao criar atividade no Pipedrive\n📋 {title}")
                else:
                    participant_names = ", ".join(
                        p.get("name") or p.get("email") or "?"
                        for p in participants[:5]
                    )
                    await notify(
                        f"⚠️ *Reunião sem deal correspondente*\n\n"
                        f"📋 {title}\n"
                        f"👥 {participant_names or 'Sem participantes'}\n\n"
                        f"Identifique o deal manualmente e me pergunte para registrar."
                    )

                processed.add(meeting_id)
                save_processed(processed)

            except Exception:
                logger.exception("Erro ao processar reunião %s", meeting_id)


async def main():
    logger.info("Read.ai sync iniciado — intervalo: %ds", SYNC_INTERVAL)
    await notify("🔄 *Read.ai sync iniciado* — verificando reuniões a cada 5 minutos.")
    while True:
        await sync_once()
        await asyncio.sleep(SYNC_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
