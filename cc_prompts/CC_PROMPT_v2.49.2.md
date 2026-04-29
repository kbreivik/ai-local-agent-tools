# CC PROMPT — v2.49.2 — fix(infra): correct edoburu/pgbouncer image tag

## What this does

Fixes the image tag introduced in v2.49.1. The pinned tag
`edoburu/pgbouncer:1.22.1` does not exist on Docker Hub — edoburu
uses the `vX.Y.Z-pN` tagging convention (leading `v`, `-pN` patch
suffix). Pulling with `1.22.1` returns "manifest unknown" and the
pgbouncer service cannot start.

Pin to `v1.25.1-p0` — current latest as of 2025-12-20, based on
upstream pgbouncer 1.25.1.

Single-line change in compose. No behavioural change to the design.

Version bump: 2.49.1 → 2.49.2

---

## Change 1 — `docker/docker-compose.yml`

Find:

````yaml
  pgbouncer:
    image: edoburu/pgbouncer:1.22.1
    container_name: hp1_pgbouncer
````

Replace with:

````yaml
  pgbouncer:
    image: edoburu/pgbouncer:v1.25.1-p0
    container_name: hp1_pgbouncer
````

## Change 2 — VERSION

Update `VERSION`: 2.49.1 → 2.49.2

## Verify

````bash
# 1. Compose lints clean
docker compose -f docker/docker-compose.yml config > /dev/null

# 2. Tag is the real one
grep -q "edoburu/pgbouncer:v1.25.1-p0" docker/docker-compose.yml
! grep -q "edoburu/pgbouncer:1.22.1" docker/docker-compose.yml
````

## Commit

````bash
git add -A
git commit -m "fix(infra): correct edoburu/pgbouncer image tag (v2.49.2)

The tag pinned in v2.49.1 (edoburu/pgbouncer:1.22.1) does not exist
on Docker Hub. edoburu publishes tags as vX.Y.Z-pN (with leading 'v'
and '-pN' patch suffix). docker pull failed with 'manifest unknown'.

Pin to v1.25.1-p0 — current latest stable, based on upstream
pgbouncer 1.25.1."
git push origin main
````

## Deploy

After CC commits and CI rebuilds, on agent-01:

````bash
cd /opt/hp1-agent
git pull origin main
docker compose -f docker/docker-compose.yml --env-file docker/.env \
  --profile pgbouncer pull pgbouncer
````

If the operator already hotfixed the tag locally on agent-01, the
`git pull` will fast-forward cleanly because the local edit was
not committed there.
