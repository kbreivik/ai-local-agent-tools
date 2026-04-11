"""Docker SDK operations on registered docker_host connections.

Uses Docker SDK directly — no SSH, no timeout issues, structured data.
Reuses _build_docker_client_for_conn from swarm.py so all auth modes
(TCP, TLS, SSH tunnel) are handled automatically.
"""
from datetime import datetime, timezone


def _ts():
    return datetime.now(timezone.utc).isoformat()

def _ok(data, msg=""):
    return {"status": "ok", "data": data, "message": msg, "timestamp": _ts()}

def _err(msg, data=None):
    return {"status": "error", "data": data, "message": msg, "timestamp": _ts()}

def _bytes_to_human(n):
    if n is None:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024.0:
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PB"


def _get_client(host_label=""):
    """Get Docker client for a docker_host connection.
    If host_label provided, finds matching connection.
    If empty, uses swarm manager. Falls back to local socket.
    """
    from api.collectors.swarm import _build_docker_client_for_conn, _build_swarm_docker_client
    from api.connections import get_all_connections_for_platform

    if host_label:
        conns = get_all_connections_for_platform("docker_host")
        q = host_label.lower()
        conn = next(
            (c for c in conns if c.get("label", "").lower() == q
             or c.get("host", "") == host_label
             or q in c.get("label", "").lower()),
            None
        )
        if not conn:
            labels = [c.get("label", "?") for c in conns]
            raise ValueError(
                f"No docker_host connection for {host_label!r}. "
                f"Available: {labels}. Add a docker_host connection in Settings → Connections."
            )
        return _build_docker_client_for_conn(conn), conn.get("label", host_label)

    return _build_swarm_docker_client(), "swarm-manager"


def docker_df(host: str = "") -> dict:
    """Get Docker disk usage: images, containers, volumes, build cache.

    Returns structured breakdown with sizes in bytes and human-readable.
    Use before and after prune operations to measure reclaimed space.
    Faster and more accurate than 'docker system df' via SSH.

    Args:
        host: docker_host connection label. Empty = swarm manager.
    """
    try:
        client, label = _get_client(host)
        df = client.df()
        client.close()

        images = df.get("Images") or []
        image_total = sum(i.get("Size", 0) for i in images)
        image_shared = sum(i.get("SharedSize", 0) for i in images if i.get("SharedSize", -1) >= 0)
        dangling = [i for i in images if not i.get("RepoTags") or i["RepoTags"] == ["<none>:<none>"]]
        dangling_size = sum(i.get("Size", 0) for i in dangling)

        containers = df.get("Containers") or []
        container_rw = sum(c.get("SizeRw", 0) or 0 for c in containers)
        stopped = [c for c in containers if c.get("Status", "").startswith(("Exited", "Dead"))]

        volumes = df.get("Volumes") or []
        vol_total = sum((v.get("UsageData") or {}).get("Size", 0) or 0 for v in volumes)
        vol_details = sorted(
            [{"name": v.get("Name", "?"),
              "size": (v.get("UsageData") or {}).get("Size", 0) or 0,
              "size_human": _bytes_to_human((v.get("UsageData") or {}).get("Size", 0) or 0),
              "ref_count": (v.get("UsageData") or {}).get("RefCount", 0) or 0}
             for v in volumes],
            key=lambda x: x["size"], reverse=True
        )

        cache = df.get("BuildCache") or []
        cache_total = sum(c.get("Size", 0) for c in cache)
        grand_total = image_total + container_rw + vol_total + cache_total

        return _ok({
            "host": label,
            "grand_total_bytes": grand_total, "grand_total": _bytes_to_human(grand_total),
            "images": {"count": len(images), "total_bytes": image_total, "total": _bytes_to_human(image_total),
                       "shared_bytes": image_shared, "dangling_count": len(dangling),
                       "dangling_bytes": dangling_size, "dangling": _bytes_to_human(dangling_size)},
            "containers": {"count": len(containers), "stopped_count": len(stopped),
                           "rw_size_bytes": container_rw, "rw_size": _bytes_to_human(container_rw)},
            "volumes": {"count": len(volumes), "total_bytes": vol_total, "total": _bytes_to_human(vol_total),
                        "details": vol_details[:10]},
            "build_cache": {"total_bytes": cache_total, "total": _bytes_to_human(cache_total), "count": len(cache)},
        }, f"Docker disk usage on {label}: {_bytes_to_human(grand_total)} total")
    except Exception as e:
        return _err(f"docker_df failed: {e}")


def docker_prune(host: str = "", target: str = "images", force: bool = True) -> dict:
    """Prune unused Docker resources and return before/after disk delta.

    Captures disk usage before, runs the prune, captures after,
    and returns both snapshots plus the exact reclaimed amount.

    ALWAYS call plan_action() before calling this tool.

    Args:
        host: docker_host connection label. Empty = swarm manager.
        target: what to prune — "images", "images_all", "containers",
                "volumes", "cache", "system".
        force: if False, dry-run (shows what would be removed).
    """
    try:
        client, label = _get_client(host)

        df_before = client.df()
        def _total(df_data):
            imgs = sum(i.get("Size", 0) for i in (df_data.get("Images") or []))
            ctrs = sum(c.get("SizeRw", 0) or 0 for c in (df_data.get("Containers") or []))
            vols = sum((v.get("UsageData") or {}).get("Size", 0) or 0 for v in (df_data.get("Volumes") or []))
            cch = sum(c.get("Size", 0) for c in (df_data.get("BuildCache") or []))
            return imgs + ctrs + vols + cch

        before_bytes = _total(df_before)

        if not force:
            client.close()
            return _ok({"host": label, "dry_run": True, "before": _bytes_to_human(before_bytes),
                        "before_bytes": before_bytes,
                        "note": "dry_run — nothing removed. Set force=True after plan_action approval."},
                       "Dry run — no changes made")

        reclaimed = 0
        pruned = {}

        if target == "images":
            result = client.images.prune(filters={"dangling": True})
            pruned["images_deleted"] = len(result.get("ImagesDeleted") or [])
            reclaimed = result.get("SpaceReclaimed", 0)
        elif target == "images_all":
            result = client.images.prune(filters={"dangling": False})
            pruned["images_deleted"] = len(result.get("ImagesDeleted") or [])
            reclaimed = result.get("SpaceReclaimed", 0)
        elif target == "containers":
            result = client.containers.prune()
            pruned["containers_deleted"] = len(result.get("ContainersDeleted") or [])
            reclaimed = result.get("SpaceReclaimed", 0)
        elif target == "volumes":
            result = client.volumes.prune()
            pruned["volumes_deleted"] = len(result.get("VolumesDeleted") or [])
            reclaimed = result.get("SpaceReclaimed", 0)
        elif target == "cache":
            result = client.api.prune_builds()
            pruned["cache_items_deleted"] = result.get("CachesDeleted", 0)
            reclaimed = result.get("SpaceReclaimed", 0)
        elif target == "system":
            r1 = client.containers.prune()
            reclaimed += r1.get("SpaceReclaimed", 0)
            r2 = client.images.prune(filters={"dangling": True})
            reclaimed += r2.get("SpaceReclaimed", 0)
            client.api.prune_networks()
            pruned["summary"] = "containers + dangling images + networks"

        df_after = client.df()
        after_bytes = _total(df_after)
        client.close()

        reported_reclaimed = max(reclaimed, max(0, before_bytes - after_bytes))

        return _ok({
            "host": label, "target": target,
            "before_bytes": before_bytes, "after_bytes": after_bytes,
            "before": _bytes_to_human(before_bytes), "after": _bytes_to_human(after_bytes),
            "reclaimed_bytes": reported_reclaimed, "reclaimed": _bytes_to_human(reported_reclaimed),
            "pruned": pruned,
        }, f"Pruned {target} on {label}: freed {_bytes_to_human(reported_reclaimed)} "
           f"({_bytes_to_human(before_bytes)} → {_bytes_to_human(after_bytes)})")
    except Exception as e:
        return _err(f"docker_prune failed: {e}")


def docker_images(host: str = "", include_dangling: bool = True) -> dict:
    """List Docker images with sizes, tags, and age.

    Returns sorted by size descending. Useful before pruning.

    Args:
        host: docker_host connection label. Empty = swarm manager.
        include_dangling: include untagged (<none>) images.
    """
    try:
        client, label = _get_client(host)
        images = client.images.list(all=False)
        client.close()

        result = []
        for img in images:
            tags = img.tags
            is_dangling = not tags or tags == ["<none>:<none>"]
            if is_dangling and not include_dangling:
                continue
            created = img.attrs.get("Created", "")
            result.append({
                "id": img.short_id, "tags": tags or ["<none>"],
                "size_bytes": img.attrs.get("Size", 0),
                "size": _bytes_to_human(img.attrs.get("Size", 0)),
                "created": created[:10] if created else "?",
                "dangling": is_dangling,
            })

        result.sort(key=lambda x: x["size_bytes"], reverse=True)
        total = sum(r["size_bytes"] for r in result)
        dangling_total = sum(r["size_bytes"] for r in result if r["dangling"])

        return _ok({
            "host": label, "count": len(result),
            "total_bytes": total, "total": _bytes_to_human(total),
            "dangling_count": sum(1 for r in result if r["dangling"]),
            "dangling_bytes": dangling_total, "dangling_total": _bytes_to_human(dangling_total),
            "images": result[:30],
        }, f"{len(result)} images on {label}, {_bytes_to_human(total)} total")
    except Exception as e:
        return _err(f"docker_images failed: {e}")
