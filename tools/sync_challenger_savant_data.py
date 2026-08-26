#!/usr/bin/env python3
"""Mirror Challenger's validated Savant data pack into Undefeated.

DATA-ONLY TEST HARNESS
----------------------
This script intentionally does not import, edit, patch, or rewrite app.py.
It copies only the validated current/LAST_GOOD Savant cache files that the
Challenger repository already produced from Baseball Savant.

Why mirror instead of independently refreshing?
- Challenger and Undefeated receive the exact same data snapshot.
- Projection differences are therefore model differences, not refresh-time drift.
- Challenger's validation/last-good protections remain the upstream gate.

This script never copies graded history, projection code, model weights,
confidence logic, sportsbook lines, lineup logic, or any app/bootstrap file.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

SOURCE_REPO = "hernandezjh235-sudo/chanllger"
SOURCE_REF = "main"
DEST = Path(__file__).resolve().parents[1] / "learning_data"
USER_AGENT = "OneWayPickz-Undefeated-Savant-Data-Only/1.0"

# Exact Challenger Savant pack. Do not add model/history files here.
FILES = {
    "savant_batter_platoon_2026.csv": {
        "required": {"mlbam_id", "player_name", "season", "vs_rhp_pa", "vs_rhp_so", "vs_rhp_k_pct", "vs_lhp_pa", "vs_lhp_so", "vs_lhp_k_pct"},
        "min_rows": 500,
    },
    "savant_batter_platoon_2026.last_good.csv": {
        "required": {"mlbam_id", "player_name", "season", "vs_rhp_pa", "vs_rhp_so", "vs_rhp_k_pct", "vs_lhp_pa", "vs_lhp_so", "vs_lhp_k_pct"},
        "min_rows": 500,
    },
    "savant_batter_profiles.csv": {
        "required": {"player_id", "player_name", "season", "PA", "SO", "K%"},
        "min_rows": 500,
    },
    "savant_batter_profiles.last_good.csv": {
        "required": {"player_id", "player_name", "season", "PA", "SO", "K%"},
        "min_rows": 500,
    },
    "savant_pitcher_stats.csv": {
        "required": {"player_id", "player_name", "season", "PA", "SO", "K%"},
        "min_rows": 650,
    },
    "savant_pitcher_stats.last_good.csv": {
        "required": {"player_id", "player_name", "season", "PA", "SO", "K%"},
        "min_rows": 650,
    },
    "pitch_mix_matchups.csv": {
        "required": {"player_id", "player_name", "season", "pitch_type", "pitch_usage", "Pitches"},
        "min_rows": 1500,
    },
    "pitch_mix_matchups.last_good.csv": {
        "required": {"player_id", "player_name", "season", "pitch_type", "pitch_usage", "Pitches"},
        "min_rows": 1500,
    },
    "savant_refresh_manifest.json": {"json": True},
    "savant_aux_refresh_manifest.json": {"json": True},
}


def _request(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/plain,text/csv,*/*"})
    with urlopen(req, timeout=90) as response:
        data = response.read()
    if not data:
        raise RuntimeError(f"empty response: {url}")
    return data


def _source_sha() -> str:
    payload = json.loads(_request(f"https://api.github.com/repos/{SOURCE_REPO}/commits/{SOURCE_REF}").decode("utf-8"))
    sha = str(payload.get("sha") or "").strip()
    if len(sha) != 40:
        raise RuntimeError("could not resolve Challenger source commit")
    return sha


def _validate_csv(name: str, raw: bytes, spec: dict) -> dict:
    text = raw.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise RuntimeError(f"{name}: empty CSV")
    header_set = {str(x).strip() for x in header}
    missing = set(spec["required"]) - header_set
    if missing:
        raise RuntimeError(f"{name}: missing required columns {sorted(missing)}")
    rows = sum(1 for row in reader if any(str(cell).strip() for cell in row))
    if rows < int(spec["min_rows"]):
        raise RuntimeError(f"{name}: only {rows} data rows; minimum is {spec['min_rows']}")
    return {"rows": rows, "sha256": hashlib.sha256(raw).hexdigest()}


def _validate_json(name: str, raw: bytes) -> dict:
    obj = json.loads(raw.decode("utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError(f"{name}: JSON root is not an object")
    status = str(obj.get("status") or "").upper()
    if status and status not in {"SUCCESS", "OK", "CURRENT"}:
        raise RuntimeError(f"{name}: upstream manifest status is {status!r}")
    season = obj.get("season")
    if season is not None and int(season) != 2026:
        raise RuntimeError(f"{name}: unexpected season {season}")
    return {"status": status or "PRESENT", "sha256": hashlib.sha256(raw).hexdigest()}


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".new", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    source_sha = _source_sha()
    print(f"Undefeated data-only Savant sync from Challenger commit {source_sha}")

    staged: dict[str, bytes] = {}
    checks: dict[str, dict] = {}
    base = f"https://raw.githubusercontent.com/{SOURCE_REPO}/{source_sha}/learning_data"

    # Download and validate the full set before replacing a single local file.
    for name, spec in FILES.items():
        raw = _request(f"{base}/{name}")
        check = _validate_json(name, raw) if spec.get("json") else _validate_csv(name, raw, spec)
        staged[name] = raw
        checks[name] = check
        print(f"validated {name}: {check}")

    # Cross-check Challenger manifests against the downloaded tables.
    main_manifest = json.loads(staged["savant_refresh_manifest.json"].decode("utf-8"))
    aux_manifest = json.loads(staged["savant_aux_refresh_manifest.json"].decode("utf-8"))
    expected_platoon = int(main_manifest.get("row_count") or 0)
    if expected_platoon and checks["savant_batter_platoon_2026.csv"]["rows"] != expected_platoon:
        raise RuntimeError("platoon row count disagrees with Challenger manifest")

    aux = aux_manifest.get("datasets") or {}
    expected = {
        "savant_batter_profiles.csv": int((aux.get("batter_profiles") or {}).get("row_count") or 0),
        "savant_pitcher_stats.csv": int((aux.get("pitcher_stats") or {}).get("row_count") or 0),
        "pitch_mix_matchups.csv": int((aux.get("pitch_mix_matchups") or {}).get("row_count") or 0),
    }
    for name, rows in expected.items():
        if rows and checks[name]["rows"] != rows:
            raise RuntimeError(f"{name}: row count disagrees with Challenger manifest")

    for name, raw in staged.items():
        _atomic_write(DEST / name, raw)

    audit = {
        "mode": "DATA_ONLY_SAME_SNAPSHOT_AS_CHALLENGER",
        "source_repo": SOURCE_REPO,
        "source_commit": source_sha,
        "synced_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "files": checks,
        "app_py_touched": False,
        "projection_formula_touched": False,
        "graded_history_touched": False,
    }
    _atomic_write(DEST / "undefeated_savant_sync_manifest.json", (json.dumps(audit, indent=2) + "\n").encode("utf-8"))
    print("SUCCESS: Savant data synchronized. app.py/model logic were not touched.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
