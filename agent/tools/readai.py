import httpx
from config import READAI_BASE_URL, READAI_API_KEY


def _headers() -> dict:
    return {"Authorization": f"Bearer {READAI_API_KEY}", "Accept": "application/json"}


def list_meetings(limit: int = 10, query: str = None) -> list:
    params = {"size": limit}
    if query:
        params["query"] = query
    r = httpx.get(f"{READAI_BASE_URL}/meetings", headers=_headers(), params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    meetings = data.get("meetings", data.get("data", []))
    return [
        {
            "id": m.get("id"),
            "title": m.get("title"),
            "date": m.get("date") or m.get("created_at"),
            "duration_minutes": m.get("duration"),
            "participants": [p.get("name") or p.get("email") for p in m.get("participants", [])],
        }
        for m in meetings
    ]


def get_meeting_summary(meeting_id: str) -> dict:
    r = httpx.get(
        f"{READAI_BASE_URL}/meetings/{meeting_id}/report",
        headers=_headers(),
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    report = data.get("meeting_report", data)
    summary = report.get("summary", {})
    return {
        "title": report.get("title"),
        "date": report.get("date") or report.get("created_at"),
        "overview": summary.get("overview") or summary.get("summary"),
        "key_points": summary.get("key_questions") or summary.get("key_points", []),
        "action_items": report.get("action_items", []),
        "participants": [
            p.get("name") or p.get("email")
            for p in report.get("participants", [])
        ],
    }


def get_meeting_transcript(meeting_id: str) -> dict:
    r = httpx.get(
        f"{READAI_BASE_URL}/meetings/{meeting_id}/transcript",
        headers=_headers(),
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    segments = data.get("transcript", data.get("segments", []))
    # Return first 50 segments to avoid huge responses
    truncated = segments[:50]
    return {
        "meeting_id": meeting_id,
        "segments": [
            {
                "speaker": s.get("speaker_name") or s.get("speaker"),
                "text": s.get("text") or s.get("content"),
                "time": s.get("start_time") or s.get("timestamp"),
            }
            for s in truncated
        ],
        "total_segments": len(segments),
        "showing": len(truncated),
    }
