#!/bin/sh
# Descarga partidas nuevas de la API de Riot y regenera data/comps.json
cd "$(dirname "$0")"
python3 -u scripts/riot_fetch.py --max-minutes "${1:-60}" --days 7 && python3 scripts/analyze.py --days 7
