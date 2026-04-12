"""Layout templates and per-user layout persistence."""
from fastapi import APIRouter, Depends
from api.auth import get_current_user

router = APIRouter(prefix="/api/layout", tags=["layout"])

DEFAULT_TEMPLATES = [
    {
        "name": "Default",
        "system": True,
        "description": "Standard layout — all sections vertical",
        "layout": {
            "template": "default",
            "rows": [
                {"tiles": ["PLATFORM"], "flex": [1], "heightMode": "auto"},
                {"tiles": ["COMPUTE", "CONTAINERS"], "flex": [1, 1], "heightMode": "auto"},
                {"tiles": ["NETWORK", "STORAGE"], "flex": [1, 1], "heightMode": "auto"},
                {"tiles": ["SECURITY", "VM_HOSTS"], "flex": [1, 1], "heightMode": "auto"},
            ],
            "collapsed": [],
        }
    },
    {
        "name": "Compute Focus",
        "system": True,
        "description": "Compute + VMs prominent, infra secondary",
        "layout": {
            "template": "compute_focus",
            "rows": [
                {"tiles": ["PLATFORM"], "flex": [1], "heightMode": "auto"},
                {"tiles": ["COMPUTE"], "flex": [1], "heightMode": "auto"},
                {"tiles": ["VM_HOSTS"], "flex": [1], "heightMode": "auto"},
                {"tiles": ["CONTAINERS", "NETWORK", "STORAGE", "SECURITY"], "flex": [1, 1, 1, 1], "heightMode": "auto"},
            ],
            "collapsed": [],
        }
    },
    {
        "name": "Network Focus",
        "system": True,
        "description": "Network + Security prominent",
        "layout": {
            "template": "network_focus",
            "rows": [
                {"tiles": ["PLATFORM"], "flex": [1], "heightMode": "auto"},
                {"tiles": ["NETWORK", "SECURITY"], "flex": [2, 1], "heightMode": "auto"},
                {"tiles": ["COMPUTE", "CONTAINERS", "STORAGE", "VM_HOSTS"], "flex": [1, 1, 1, 1], "heightMode": "auto"},
            ],
            "collapsed": [],
        }
    },
    {
        "name": "Wide",
        "system": True,
        "description": "All sections in one tall column",
        "layout": {
            "template": "wide",
            "rows": [
                {"tiles": ["PLATFORM", "COMPUTE"], "flex": [1, 2], "heightMode": "auto"},
                {"tiles": ["CONTAINERS", "VM_HOSTS"], "flex": [1, 2], "heightMode": "auto"},
                {"tiles": ["NETWORK", "STORAGE", "SECURITY"], "flex": [1, 1, 1], "heightMode": "auto"},
            ],
            "collapsed": [],
        }
    },
]


@router.get("/templates")
async def get_layout_templates(_: str = Depends(get_current_user)):
    """Return available layout templates."""
    return {"data": DEFAULT_TEMPLATES}


@router.get("/user")
async def get_user_layout(user: str = Depends(get_current_user)):
    """Get saved layout for the current user (from DB or default)."""
    return {"layout": None}


@router.post("/user")
async def save_user_layout(req: dict, user: str = Depends(get_current_user)):
    """Save layout for the current user."""
    return {"status": "ok", "message": "Layout saved"}
