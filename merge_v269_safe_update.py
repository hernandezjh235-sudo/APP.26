# -*- coding: utf-8 -*-
"""
Merge V2.6.9 Savant safe-update helper restored for Railway/Undefeated.

This module keeps the production projection contract unchanged while restoring
the current-season Baseball Savant batter-vs-pitcher-hand cache used by the
existing shadow/enrichment layer.

Source of truth:
- Baseball Savant MLB Statcast Search
- Current regular season only
- Batter grouped summary
- Pitcher handedness R / L
- K% requested directly from Savant; PA requested directly from Savant
"""
import io
import json
import math
import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

SAVANT_SCHEMA_VERSION = "SAVANT_BATTER_PLATOON_SCHEMA_V1"
_V1104_SOURCE = "BASEBALL_SAVANT_CURRENT_SEASON_VS_HAND"
_V1104_URL = "https://baseballsavant.mlb.com/statcast_search/csv"
_V1104_TIMEOUT = (8, 45)
_V1104_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; OneWayPickz/1.0; +https://baseballsavant.mlb.com/)",
    "Accept": "text/csv,text/plain,*/*",
}

def _v269_fb_num(value, default=None):
    try:
        if value is None or value == '':
            return default
        out = float(str(value).replace('%', '').replace(',', '').strip())
        return out if math.isfinite(out) else default
    except Exception:
        return default

def _v269_fb_pct(value, default=None):
    out = _v269_fb_num(value, default)
    if out is None:
        return default
    return out * 100.0 if abs(out) <= 1.0 else out

def _v269_fb_norm_name(value):
    try:
        raw = ''.join((ch for ch in unicodedata.normalize('NFKD', str(value or '')) if not unicodedata.combining(ch))).lower()
        raw = re.sub('[^a-z0-9 ]+', ' ', raw)
        raw = re.sub('\\b(jr|sr|ii|iii|iv)\\b', ' ', raw)
        return ' '.join(raw.split())
    except Exception:
        return str(value or '').lower().strip()

def _v269_fb_id(value):
    try:
        if value in (None, ''):
            return ''
        return str(int(float(value)))
    except Exception:
        return ''

def _v269_fb_read_csv(path):
    try:
        if Path(path).exists():
            frame = pd.read_csv(path)
            return frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    except Exception:
        pass
    return pd.DataFrame()

class SavantDataService:
    """Safe current/LAST_GOOD cache service for batter vs-hand Savant data."""

    def __init__(self, cache_dir='learning_data', season=None):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.season = int(season or datetime.now().year)
        self.active_path = self.cache_dir / f'savant_batter_platoon_{self.season}.csv'
        self.last_good_path = self.cache_dir / f'savant_batter_platoon_{self.season}.last_good.csv'
        self.targeted_path = self.cache_dir / f'savant_batter_platoon_{self.season}.targeted.csv'
        self.manifest_path = self.cache_dir / 'savant_refresh_manifest.json'

    def _valid(self, frame):
        required = {'mlbam_id', 'player_name', 'season', 'vs_rhp_pa', 'vs_rhp_so', 'vs_rhp_k_pct', 'vs_lhp_pa', 'vs_lhp_so', 'vs_lhp_k_pct'}
        return isinstance(frame, pd.DataFrame) and (not frame.empty) and required.issubset(frame.columns)

    def load(self):
        active = _v269_fb_read_csv(self.active_path)
        fallback_used = False
        if not self._valid(active):
            active = _v269_fb_read_csv(self.last_good_path)
            fallback_used = self._valid(active)
        targeted = _v269_fb_read_csv(self.targeted_path)
        if self._valid(targeted):
            if self._valid(active):
                active = pd.concat([active, targeted], ignore_index=True, sort=False)
            else:
                active = targeted
        if self._valid(active):
            active = active.copy()
            active['mlbam_id'] = active['mlbam_id'].map(_v269_fb_id)
            if 'season' in active.columns:
                active = active[pd.to_numeric(active['season'], errors='coerce').fillna(self.season).astype(int) == self.season]
            active = active.drop_duplicates(subset=['mlbam_id'], keep='last').reset_index(drop=True)
            try:
                active.attrs['fallback_used'] = fallback_used
            except Exception:
                pass
            return active
        return pd.DataFrame()

    def _manifest(self):
        try:
            if self.manifest_path.exists():
                obj = json.loads(self.manifest_path.read_text(encoding='utf-8'))
                return obj if isinstance(obj, dict) else {}
        except Exception:
            pass
        return {}

    def health(self):
        frame = self.load()
        manifest = self._manifest()
        last_success = manifest.get('last_success_at') or manifest.get('refresh_completed_at')
        age_days = None
        try:
            stamp = datetime.fromisoformat(str(last_success).replace('Z', '+00:00'))
            now = datetime.now(stamp.tzinfo) if stamp.tzinfo else datetime.now()
            age_days = max(0, int((now - stamp).total_seconds() // 86400))
        except Exception:
            try:
                source = self.active_path if self.active_path.exists() else self.last_good_path
                if source.exists():
                    age_days = max(0, int((datetime.now().timestamp() - source.stat().st_mtime) // 86400))
            except Exception:
                age_days = None
        if frame.empty:
            status = 'FAILED'
        elif age_days is None or age_days <= 1:
            status = 'CURRENT'
        elif age_days == 2:
            status = 'AGING'
        else:
            status = 'STALE'
        return {'status': status, 'row_count': int(len(frame)), 'age_days': age_days, 'last_success_at': last_success, 'active_path': str(self.active_path), 'last_good_path': str(self.last_good_path), 'fallback_status': 'LAST_GOOD' if not self.active_path.exists() and self.last_good_path.exists() else 'ACTIVE_CACHE', 'compatibility_fallback': True}

    def refresh(self, force=False):
        out = self.health()
        out.update({'refresh_requested': True, 'force': bool(force), 'refresh_mode': 'LOCAL_CACHE_COMPATIBILITY_FALLBACK', 'warning': 'live Savant refresh not initialized; using validated current/LAST_GOOD cache'})
        return out

    def refresh_missing_players(self, player_ids, force=False):
        frame = self.load()
        have = set(frame.get('mlbam_id', pd.Series(dtype=str)).astype(str)) if not frame.empty else set()
        wanted = {_v269_fb_id(v) for v in player_ids or [] if _v269_fb_id(v)}
        missing = sorted(wanted - have)
        return {'status': 'CACHE_ONLY', 'requested': len(wanted), 'matched': len(wanted) - len(missing), 'missing': missing, 'force': bool(force), 'compatibility_fallback': True}

def _v269_fb_expected_slot_counts(expected_bf, slots=9):
    bf = max(0.0, _v269_fb_num(expected_bf, 0.0) or 0.0)
    lo = int(math.floor(bf))
    frac = bf - lo

    def counts(n):
        out = []
        for slot in range(1, slots + 1):
            if n < slot:
                out.append(0.0)
            else:
                out.append(float(1 + (n - slot) // slots))
        return out
    a, b = (counts(lo), counts(lo + 1))
    return [a[i] * (1.0 - frac) + b[i] * frac for i in range(slots)]

def attach_savant_shadow(lineup_rows, pitcher_hand, platoon_frame, expected_bf):
    rows = [dict(item) for item in lineup_rows or [] if isinstance(item, dict)][:9]
    frame = platoon_frame.copy() if isinstance(platoon_frame, pd.DataFrame) else pd.DataFrame()
    hand = str(pitcher_hand or '').upper()
    split = 'lhp' if hand.startswith('L') else 'rhp'
    pa_col, so_col, k_col = (f'vs_{split}_pa', f'vs_{split}_so', f'vs_{split}_k_pct')
    if frame.empty or not {'mlbam_id', 'player_name', pa_col, so_col, k_col}.issubset(frame.columns):
        return (rows, {'status': 'UNAVAILABLE', 'matched': 0, 'simple_savant_lineup_k_pct': None, 'order_weighted_savant_k_pct': None, 'top3_savant_k_pct': None, 'middle3_savant_k_pct': None, 'bottom3_savant_k_pct': None})
    frame = frame.copy()
    frame['_id'] = frame['mlbam_id'].map(_v269_fb_id)
    frame['_name'] = frame['player_name'].map(_v269_fb_norm_name)
    by_id = {r['_id']: r for _, r in frame.iterrows() if r.get('_id')}
    by_name = {}
    for _, r in frame.iterrows():
        key = r.get('_name')
        if key and key not in by_name:
            by_name[key] = r
    counts = _v269_fb_expected_slot_counts(expected_bf, 9)
    matched_values, weighted_pairs = ([], [])
    buckets = {'top': [], 'middle': [], 'bottom': []}
    enriched = []
    for idx, item in enumerate(rows):
        out = dict(item)
        pid = ''
        for key in ('mlbam_id', 'MLBAM ID', 'player_id', 'Player ID', 'Batter ID'):
            pid = _v269_fb_id(item.get(key))
            if pid:
                break
        name = item.get('Batter') or item.get('Player') or item.get('Name') or ''
        norm = _v269_fb_norm_name(name)
        rec = by_id.get(pid) if pid else None
        match_method = 'MLBAM_ID' if rec is not None else ''
        if rec is None and norm:
            rec = by_name.get(norm)
            match_method = 'NORMALIZED_NAME' if rec is not None else ''
        raw_k = raw_pa = raw_so = None
        if rec is not None:
            raw_k = _v269_fb_num(rec.get(k_col), None)
            raw_pa = _v269_fb_num(rec.get(pa_col), None)
            raw_so = _v269_fb_num(rec.get(so_col), None)
            if raw_k is not None and raw_pa is not None and raw_pa > 0:
                out['savant_raw_vs_hand_k_pct'] = round(raw_k, 3)
                out['savant_raw_vs_hand_pa'] = int(round(raw_pa))
                out['savant_raw_vs_hand_so'] = int(round(raw_so or 0))
                out['Savant Match Status'] = match_method
                model_used = None
                for key in ('Used K%', 'K% Used', 'Raw_K_Rate', 'Split K%', 'Season K%'):
                    model_used = _v269_fb_pct(item.get(key), None)
                    if model_used is not None:
                        break
                out['model_minus_savant_pp'] = None if model_used is None else round(model_used - raw_k, 3)
                matched_values.append(raw_k)
                order = int(_v269_fb_num(item.get('Order'), idx + 1) or idx + 1)
                order = min(9, max(1, order))
                weight = counts[order - 1]
                weighted_pairs.append((raw_k, weight))
                if order <= 3:
                    buckets['top'].append(raw_k)
                elif order <= 6:
                    buckets['middle'].append(raw_k)
                else:
                    buckets['bottom'].append(raw_k)
            else:
                out['Savant Match Status'] = 'SAVANT_SPLIT_MISSING'
        else:
            out['Savant Match Status'] = 'SAVANT_PLAYER_MATCH_UNCERTAIN'
        enriched.append(out)

    def avg(vals):
        return round(float(np.mean(vals)), 3) if vals else None
    weight_sum = sum((w for _, w in weighted_pairs))
    weighted = None
    if weighted_pairs and weight_sum > 0:
        weighted = round(sum((v * w for v, w in weighted_pairs)) / weight_sum, 3)
    matched = len(matched_values)
    status = 'READY' if matched >= min(7, max(1, len(rows))) else 'PARTIAL' if matched else 'UNAVAILABLE'
    return (enriched, {'status': status, 'matched': matched, 'simple_savant_lineup_k_pct': avg(matched_values), 'order_weighted_savant_k_pct': weighted, 'top3_savant_k_pct': avg(buckets['top']), 'middle3_savant_k_pct': avg(buckets['middle']), 'bottom3_savant_k_pct': avg(buckets['bottom']), 'pitcher_hand': hand, 'compatibility_fallback': True})

def is_first_inning_k_market(value):
    text = re.sub('[^a-z0-9]+', ' ', str(value or '').lower()).strip()
    if 'strikeout' not in text and not re.search('\\bks?\\b', text):
        return False
    return bool(re.search('\\b(first|1st)\\s+inning\\b', text) or 'first inning pitcher' in text or 'pitcher first inning' in text)

def line_difficulty(projection, line, recent_ks=None):
    proj = _v269_fb_num(projection, None)
    ln = _v269_fb_num(line, None)
    vals = [float(v) for v in (_v269_fb_num(x, None) for x in recent_ks or []) if v is not None and math.isfinite(v)]
    if ln is None:
        return {'line_difficulty_state': 'NO_LINE', 'line_percentile_of_pitcher_distribution': None}
    percentile = None
    if vals:
        percentile = 100.0 * sum((1 for v in vals if v <= ln)) / len(vals)
        if percentile <= 20:
            state = 'VERY_LOW_LINE'
        elif percentile <= 35:
            state = 'LOW_LINE'
        elif percentile >= 80:
            state = 'VERY_HIGH_LINE'
        elif percentile >= 65:
            state = 'HIGH_LINE'
        else:
            state = 'NORMAL_LINE'
    elif proj is not None:
        gap = ln - proj
        if gap <= -1.5:
            state = 'VERY_LOW_LINE'
        elif gap <= -0.65:
            state = 'LOW_LINE'
        elif gap >= 1.5:
            state = 'VERY_HIGH_LINE'
        elif gap >= 0.65:
            state = 'HIGH_LINE'
        else:
            state = 'NORMAL_LINE'
    else:
        state = 'NORMAL_LINE'
    return {'line_difficulty_state': state, 'line_percentile_of_pitcher_distribution': None if percentile is None else round(percentile, 1), 'recent_sample': len(vals), 'compatibility_fallback': True}

def opportunity_conversion_audit(row):
    row = dict(row or {})

    def first_pct(keys):
        for key in keys:
            value = _v269_fb_pct(row.get(key), None)
            if value is not None:
                return value
        return None
    lineup = first_pct(['order_weighted_savant_k_pct', 'raw_savant_lineup_k_pct', 'Opponent K% vs Pitcher Hand', 'Opp K%'])
    season = first_pct(['team_k_pct_season_vs_hand', 'Opponent K% vs Pitcher Hand'])
    recent = [first_pct([f'team_k_pct_l{n}_vs_hand']) for n in (15, 10, 5)]
    recent = [v for v in recent if v is not None]
    bf = _v269_fb_num(row.get('projected_bf', row.get('expected_bf')), 20.0) or 20.0
    opportunity_parts = []
    if lineup is not None:
        opportunity_parts.append(max(0.0, min(100.0, (lineup - 12.0) / 20.0 * 100.0)))
    if season is not None:
        opportunity_parts.append(max(0.0, min(100.0, (season - 12.0) / 20.0 * 100.0)))
    if recent:
        r = float(np.mean(recent))
        opportunity_parts.append(max(0.0, min(100.0, (r - 12.0) / 20.0 * 100.0)))
    opportunity_parts.append(max(0.0, min(100.0, (bf - 15.0) / 15.0 * 100.0)))
    opportunity = float(np.mean(opportunity_parts)) if opportunity_parts else 50.0
    pitcher_k = first_pct(['Canonical Pitcher K%', 'Pitcher K%', 'pitcher_k_pct', 'pitcher_k', 'season_pitcher_k_pct'])
    whiff = first_pct(['Whiff%', 'whiff_pct', 'Pitcher Whiff%'])
    csw = first_pct(['CSW%', 'csw_pct', 'Pitcher CSW%'])
    putaway = first_pct(['PutAway%', 'putaway_pct', 'Pitcher PutAway%'])
    k9 = _v269_fb_num(row.get('K/9', row.get('APP100 Pitcher K/9')), None)
    conversion_parts = []
    if pitcher_k is not None:
        conversion_parts.append(max(0.0, min(100.0, (pitcher_k - 12.0) / 24.0 * 100.0)))
    if whiff is not None:
        conversion_parts.append(max(0.0, min(100.0, (whiff - 15.0) / 25.0 * 100.0)))
    if csw is not None:
        conversion_parts.append(max(0.0, min(100.0, (csw - 20.0) / 18.0 * 100.0)))
    if putaway is not None:
        conversion_parts.append(max(0.0, min(100.0, (putaway - 10.0) / 25.0 * 100.0)))
    if k9 is not None:
        conversion_parts.append(max(0.0, min(100.0, (k9 - 4.5) / 8.0 * 100.0)))
    conversion = float(np.mean(conversion_parts)) if conversion_parts else 50.0
    if opportunity >= 55.0 and conversion >= 55.0 and bf >= 20.0:
        gate = 'SUPPORTED'
    elif opportunity < 42.0 or conversion < 42.0:
        gate = 'WEAK_SUPPORT'
    else:
        gate = 'REVIEW'
    return {'k_opportunity_score': round(opportunity, 1), 'k_conversion_score': round(conversion, 1), 'over_validation_gate': gate, 'compatibility_fallback': True}

def validate_data_pack_frame(filename, frame, season=None):
    name = Path(str(filename or '')).name
    df = frame if isinstance(frame, pd.DataFrame) else pd.DataFrame(frame or [])
    errors, warnings = ([], [])
    if df.empty:
        errors.append('EMPTY_OR_TEMPLATE_ONLY')
        return {'ok': False, 'errors': errors, 'warnings': warnings, 'row_count': 0}
    cols = {str(c).strip() for c in df.columns}
    required_map = {'Pitch.csv': {'Date', 'Pitcher', 'IP', 'BF', 'K'}, 'Batter.csv': {'Date', 'Player', 'PA', 'K'}, 'graded_history.csv': {'Date', 'Pitcher', 'Pick', 'Actual_K', 'Result'}, 'savant_pitcher_stats.csv': {'player_id', 'player_name', 'season', 'PA', 'SO', 'K%'}, 'savant_batter_profiles.csv': {'player_id', 'player_name', 'season', 'PA', 'SO', 'K%'}, 'pitch_mix_matchups.csv': {'player_id', 'player_name', 'season', 'pitch_type', 'pitch_usage'}}
    if name.startswith('savant_batter_platoon_') and name.endswith('.csv'):
        required = {'mlbam_id', 'player_name', 'season', 'vs_rhp_pa', 'vs_rhp_so', 'vs_rhp_k_pct', 'vs_lhp_pa', 'vs_lhp_so', 'vs_lhp_k_pct'}
    else:
        required = required_map.get(name, set())
    missing = sorted(required - cols)
    if missing:
        errors.append('MISSING_COLUMNS: ' + ', '.join(missing))
    if 'season' in cols and season is not None:
        vals = pd.to_numeric(df['season'], errors='coerce').dropna().astype(int)
        if len(vals) and int(season) not in set(vals.tolist()):
            errors.append(f'TARGET_SEASON_{int(season)}_MISSING')
    if name == 'Pitch.csv' and 'Date' in cols:
        dates = pd.to_datetime(df['Date'], errors='coerce')
        if dates.notna().any():
            age = (pd.Timestamp.now().normalize() - dates.max().normalize()).days
            if age > 3:
                errors.append(f'STALE PITCH GAME LOGS: latest {dates.max().date()}')
        if {'Pitcher', 'GamePk'}.issubset(cols):
            dup = int(df.duplicated(subset=['Pitcher', 'GamePk'], keep=False).sum())
            if dup:
                errors.append(f'DUPLICATE_PITCHER_GAMEPK_ROWS: {dup}')
    if name == 'graded_history.csv' and {'Date', 'Pitcher', 'Pick'}.issubset(cols):
        dup = int(df.duplicated(subset=['Date', 'Pitcher', 'Pick'], keep=False).sum())
        if dup:
            errors.append(f'DUPLICATE_GRADED_ROWS: {dup}')
    return {'ok': not errors, 'errors': errors, 'warnings': warnings, 'row_count': int(len(df)), 'schema_version': 'V269_COMPAT_VALIDATOR_V1', 'compatibility_fallback': True}

# ---- V1.10.4 live current-season batter-vs-hand bridge ----
def _v1104_col(frame, candidates):
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return None
    norm_map = {}
    for col in frame.columns:
        key = re.sub(r"[^a-z0-9]+", "", str(col).lower())
        norm_map.setdefault(key, col)
    for candidate in candidates:
        key = re.sub(r"[^a-z0-9]+", "", str(candidate).lower())
        if key in norm_map:
            return norm_map[key]
    return None

def _v1104_name(value):
    text = str(value or "").strip()
    if "," in text:
        left, right = text.split(",", 1)
        if left.strip() and right.strip():
            return f"{right.strip()} {left.strip()}".strip()
    return text

def _v1104_pct_points(value):
    try:
        x = float(str(value).replace("%", "").replace(",", "").strip())
        if not math.isfinite(x):
            return None
        if abs(x) <= 1.0:
            x *= 100.0
        return float(x)
    except Exception:
        return None

def _v1104_savant_params(season, hand):
    return {
        "all": "true", "hfPT": "", "hfAB": "", "hfGT": "R|", "hfPR": "", "hfZ": "",
        "hfStadium": "", "hfBBL": "", "hfNewZones": "", "hfPull": "", "hfC": "",
        "hfSea": f"{int(season)}|", "hfSit": "", "player_type": "batter", "hfOuts": "",
        "hfOpponent": "", "pitcher_throws": str(hand).upper(), "batter_stands": "", "hfSA": "",
        "game_date_gt": "", "game_date_lt": "", "hfMo": "", "hfTeam": "", "home_road": "",
        "hfRO": "", "position": "", "hfInfield": "", "hfOutfield": "", "hfInn": "",
        "hfBBT": "", "hfFlag": "", "metric_1": "", "group_by": "name", "min_pitches": "0",
        "min_results": "0", "min_pas": "0", "sort_col": "pitches",
        "player_event_sort": "api_p_release_speed", "sort_order": "desc",
        "chk_stats_pa": "on", "chk_stats_k_percent": "on", "type": "details",
    }

def _v1104_fetch_hand(season, hand, session=None):
    sess = session or requests
    response = sess.get(_V1104_URL, params=_v1104_savant_params(season, hand), headers=_V1104_HEADERS, timeout=_V1104_TIMEOUT)
    response.raise_for_status()
    text = response.content.decode("utf-8-sig", errors="replace")
    if not text.strip():
        raise RuntimeError(f"Empty Baseball Savant response for {hand}HP")
    frame = pd.read_csv(io.StringIO(text))
    if frame.empty:
        raise RuntimeError(f"Empty Baseball Savant table for {hand}HP")
    if "error" in {str(c).lower() for c in frame.columns}:
        raise RuntimeError(f"Baseball Savant returned an error table for {hand}HP")
    id_col = _v1104_col(frame, ["player_id", "mlbam_id", "batter", "batter_id", "id"])
    name_col = _v1104_col(frame, ["player_name", "last_name, first_name", "name", "batter_name"])
    pa_col = _v1104_col(frame, ["pa", "plate_appearances", "plate appearances", "pas"])
    kpct_col = _v1104_col(frame, ["k_percent", "k%", "strikeout_percent", "strikeout %", "so_percent"])
    if id_col is None or name_col is None or pa_col is None or kpct_col is None:
        raise RuntimeError(f"Unexpected Savant grouped schema; id={id_col}, name={name_col}, pa={pa_col}, k%={kpct_col}; columns={list(frame.columns)[:40]}")
    out_rows = []
    split = "rhp" if str(hand).upper().startswith("R") else "lhp"
    for _, rec in frame.iterrows():
        pid = _v269_fb_id(rec.get(id_col))
        name = _v1104_name(rec.get(name_col))
        pa = _v269_fb_num(rec.get(pa_col), None)
        kpct = _v1104_pct_points(rec.get(kpct_col))
        if not pid or not name or pa is None or pa <= 0 or kpct is None:
            continue
        kpct = float(max(0.0, min(100.0, kpct)))
        so = int(round(float(pa) * kpct / 100.0))
        out_rows.append({"mlbam_id": pid, "player_name": name, "season": int(season), f"vs_{split}_pa": int(round(float(pa))), f"vs_{split}_so": int(so), f"vs_{split}_k_pct": round(kpct, 3)})
    result = pd.DataFrame(out_rows)
    if result.empty or len(result) < 100:
        raise RuntimeError(f"Baseball Savant {hand}HP grouped result failed sanity check: {len(result)} rows")
    return result.drop_duplicates(subset=["mlbam_id"], keep="last").reset_index(drop=True)

def _v1104_build_platoon(season, session=None):
    right = _v1104_fetch_hand(season, "R", session=session)
    left = _v1104_fetch_hand(season, "L", session=session)
    merged = right.merge(left, on=["mlbam_id", "season"], how="outer", suffixes=("_r", "_l"))
    if "player_name_r" in merged.columns or "player_name_l" in merged.columns:
        rname = merged.get("player_name_r", pd.Series(index=merged.index, dtype=object))
        lname = merged.get("player_name_l", pd.Series(index=merged.index, dtype=object))
        merged["player_name"] = rname.where(rname.notna() & (rname.astype(str).str.strip() != ""), lname)
        merged = merged.drop(columns=[c for c in ("player_name_r", "player_name_l") if c in merged.columns])
    for col in ("vs_rhp_pa", "vs_rhp_so", "vs_rhp_k_pct", "vs_lhp_pa", "vs_lhp_so", "vs_lhp_k_pct"):
        if col not in merged.columns:
            merged[col] = np.nan
    stamp = datetime.now(timezone.utc).isoformat()
    merged["source"] = _V1104_SOURCE
    merged["source_timestamp"] = stamp
    merged["mlbam_id"] = merged["mlbam_id"].map(_v269_fb_id)
    merged["season"] = pd.to_numeric(merged["season"], errors="coerce").fillna(int(season)).astype(int)
    merged = merged[merged["mlbam_id"].astype(bool)].copy().drop_duplicates(subset=["mlbam_id"], keep="last").reset_index(drop=True)
    if len(merged) < 200:
        raise RuntimeError(f"Merged Savant platoon sanity check failed: {len(merged)} rows")
    return merged[["mlbam_id", "player_name", "season", "vs_rhp_pa", "vs_rhp_so", "vs_rhp_k_pct", "vs_lhp_pa", "vs_lhp_so", "vs_lhp_k_pct", "source", "source_timestamp"]]

def _v1104_atomic_csv(frame, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(tmp, index=False)
    os.replace(tmp, path)

def _v1104_write_manifest(service, status, row_count=0, error="", extra=None):
    now = datetime.now(timezone.utc).isoformat()
    previous = service._manifest() if hasattr(service, "_manifest") else {}
    obj = {
        "schema_version": SAVANT_SCHEMA_VERSION, "season": int(service.season), "status": str(status),
        "source": _V1104_SOURCE, "last_success_at": now if status == "SUCCESS" else previous.get("last_success_at"),
        "refresh_started_at": now, "refresh_completed_at": now, "row_count": int(row_count or 0),
        "error": str(error or "")[:500], "query_mode": "ALL_MLB_BATTERS_GROUP_BY_NAME_VS_PITCHER_HAND",
    }
    if isinstance(extra, dict): obj.update(extra)
    try: service.manifest_path.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")
    except Exception: pass
    return obj

def _v1104_service_refresh(self, force=False):
    before = self.health()
    if not force and before.get("status") == "CURRENT" and int(before.get("row_count") or 0) >= 200:
        return {**before, "refresh": "SKIPPED_CURRENT", "refresh_mode": "LIVE_SAVANT_GROUPED_CACHE", "source": _V1104_SOURCE}
    started = datetime.now(timezone.utc).isoformat()
    try:
        frame = _v1104_build_platoon(self.season)
        _v1104_atomic_csv(frame, self.active_path)
        _v1104_atomic_csv(frame, self.last_good_path)
        try:
            if self.targeted_path.exists(): self.targeted_path.unlink()
        except Exception: pass
        manifest = _v1104_write_manifest(self, "SUCCESS", len(frame), extra={"refresh_started_at": started, "matched_rhp": int(pd.to_numeric(frame["vs_rhp_pa"], errors="coerce").gt(0).sum()), "matched_lhp": int(pd.to_numeric(frame["vs_lhp_pa"], errors="coerce").gt(0).sum())})
        return {**self.health(), "refresh": "SUCCESS", "refresh_mode": "LIVE_SAVANT_GROUPED_CACHE", "source": _V1104_SOURCE, "manifest": manifest}
    except Exception as exc:
        health = self.health()
        _v1104_write_manifest(self, "FAILED", health.get("row_count", 0), error=f"{type(exc).__name__}: {exc}", extra={"refresh_started_at": started})
        return {**health, "refresh": "FAILED", "refresh_mode": "LIVE_SAVANT_GROUPED_CACHE", "source": _V1104_SOURCE, "error": f"{type(exc).__name__}: {exc}"[:500]}

def _v1104_service_refresh_missing_players(self, player_ids, force=False):
    wanted = {_v269_fb_id(v) for v in player_ids or [] if _v269_fb_id(v)}
    frame = self.load(); have = set(frame.get("mlbam_id", pd.Series(dtype=str)).astype(str)) if not frame.empty else set()
    missing_before = sorted(wanted - have); refresh_result = None
    if missing_before or force:
        refresh_result = self.refresh(force=True)
        frame = self.load(); have = set(frame.get("mlbam_id", pd.Series(dtype=str)).astype(str)) if not frame.empty else set()
    missing_after = sorted(wanted - have)
    return {"status": "READY" if not missing_after else "PARTIAL" if have & wanted else "UNAVAILABLE", "requested": len(wanted), "matched": len(wanted) - len(missing_after), "missing": missing_after, "missing_before": missing_before, "force": bool(force), "refresh_mode": "LIVE_SAVANT_GROUPED_CACHE", "source": _V1104_SOURCE, "refresh_result": None if refresh_result is None else refresh_result.get("refresh")}

SavantDataService.refresh = _v1104_service_refresh
SavantDataService.refresh_missing_players = _v1104_service_refresh_missing_players

_v1104_original_health = SavantDataService.health
def _v1104_service_health(self):
    out = dict(_v1104_original_health(self) or {})
    out["compatibility_fallback"] = False
    out["refresh_mode"] = "LIVE_SAVANT_GROUPED_CACHE"
    out["source"] = _V1104_SOURCE
    return out
SavantDataService.health = _v1104_service_health

_v1104_original_attach = attach_savant_shadow
def _v1104_attach_savant_shadow(lineup_rows, pitcher_hand, platoon_frame, expected_bf):
    enriched, audit = _v1104_original_attach(lineup_rows, pitcher_hand, platoon_frame, expected_bf)
    audit = dict(audit or {})
    audit["compatibility_fallback"] = False
    audit["source"] = _V1104_SOURCE
    return enriched, audit
attach_savant_shadow = _v1104_attach_savant_shadow
