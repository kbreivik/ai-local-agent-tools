#!/usr/bin/env bash
curl -sf "http://localhost:${API_PORT:-8000}/api/health" > /dev/null 2>&1 || exit 1
