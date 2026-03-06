"""
MuninnDB cognitive memory layer — Phase 5.

Usage:
    from api.memory import client, hooks
    from api.memory.client import get_client
"""
from api.memory.client import get_client, close_client

__all__ = ["get_client", "close_client"]
