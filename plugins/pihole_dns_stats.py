"""Pi-hole DNS statistics — query counts, blocked domains, top clients."""
import os
from datetime import datetime, timezone

import httpx


PLUGIN_META = {
    "name": "pihole_dns_stats",
    "description": "Query Pi-hole DNS statistics: total queries, blocked count, top blocked domains, top clients.",
    "platform": "pihole",
    "category": "monitoring",
    "agent_types": ["investigate", "execute"],
    "requires_plan": False,
    "params": {
        "host": {"type": "string", "required": False, "description": "Pi-hole host (default: env PIHOLE_HOST)"},
    },
}


def _ts():
    return datetime.now(timezone.utc).isoformat()

def _ok(data, message="OK"):
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}

def _err(message, data=None):
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}


def execute(**kwargs) -> dict:
    """Fetch Pi-hole summary and top lists."""
    host = kwargs.get("host") or os.environ.get("PIHOLE_HOST", "")
    api_key = os.environ.get("PIHOLE_API_KEY", "")
    if not host:
        return _err("PIHOLE_HOST not configured")

    base = f"http://{host}/admin/api.php"
    try:
        # Summary stats
        r = httpx.get(f"{base}?summaryRaw", timeout=10)
        r.raise_for_status()
        summary = r.json()

        result = {
            "dns_queries_today": summary.get("dns_queries_today", 0),
            "ads_blocked_today": summary.get("ads_blocked_today", 0),
            "ads_percentage_today": summary.get("ads_percentage_today", 0),
            "domains_being_blocked": summary.get("domains_being_blocked", 0),
            "unique_clients": summary.get("unique_clients", 0),
            "status": summary.get("status", "unknown"),
        }

        # Top blocked domains (if API key available)
        if api_key:
            try:
                tr = httpx.get(f"{base}?topItems=10&auth={api_key}", timeout=10)
                if tr.status_code == 200:
                    top = tr.json()
                    result["top_blocked"] = list(top.get("top_ads", {}).keys())[:10]
                    result["top_queries"] = list(top.get("top_queries", {}).keys())[:10]
            except Exception:
                pass

        return _ok(result, f"Pi-hole: {result['dns_queries_today']} queries, {result['ads_blocked_today']} blocked")

    except httpx.HTTPStatusError as e:
        return _err(f"Pi-hole API error: HTTP {e.response.status_code}")
    except Exception as e:
        return _err(f"Pi-hole connection failed: {e}")
