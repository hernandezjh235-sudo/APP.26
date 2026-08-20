import io
import json
import shutil
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

YEAR = 2026
OUT = Path('savant_refresh_output')
OUT.mkdir(parents=True, exist_ok=True)
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; OneWayPickz/1.0; +https://baseballsavant.mlb.com/)',
    'Accept': 'text/csv,text/plain,*/*',
}
STAMP = datetime.now(timezone.utc).isoformat()
SOURCE = 'BASEBALL_SAVANT_CURRENT_SEASON'


def read_required(name):
    path = OUT / name
    if not path.exists():
        raise RuntimeError(f'missing prerequisite {path}')
    return pd.read_csv(path, low_memory=False)


def profile(raw, schema):
    rename = {
        'last_name, first_name': 'player_name', 'year': 'season', 'pa': 'PA',
        'strikeout': 'SO', 'k_percent': 'K%', 'bb_percent': 'BB%',
        'whiff_percent': 'Whiff%', 'swing_percent': 'Swing%', 'xwoba': 'xwOBA',
        'xba': 'xBA', 'xslg': 'xSLG', 'hard_hit_percent': 'Hard-Hit%',
        'barrel_batted_rate': 'Barrel%', 'avg_swing_speed': 'average_swing_speed',
        'fast_swing_rate': 'fast_swing_rate', 'swords': 'swords',
        'squared_up_contact': 'squared_up_contact', 'woba': 'wOBA',
    }
    out = raw.rename(columns=rename).copy()
    cols = ['player_id','player_name','season','PA','SO','K%','BB%','Whiff%','Swing%',
            'xwOBA','xBA','xSLG','Hard-Hit%','Barrel%','average_swing_speed',
            'fast_swing_rate','swords','squared_up_contact','wOBA']
    for c in cols:
        if c not in out.columns:
            out[c] = pd.NA
    out = out[cols]
    out['source'] = SOURCE
    out['source_timestamp'] = STAMP
    out['schema_version'] = schema
    out['refresh_status'] = 'CURRENT'
    return out


def build_profiles():
    batter_raw = read_required('raw_custom_batter.csv')
    pitcher_raw = read_required('raw_custom_pitcher.csv')
    batter = profile(batter_raw, 'SAVANT_BATTER_PROFILE_SCHEMA_V1')
    pitcher = profile(pitcher_raw, 'SAVANT_PITCHER_SCHEMA_V1')
    batter.to_csv(OUT/'savant_batter_profiles.csv', index=False)
    pitcher.to_csv(OUT/'savant_pitcher_stats.csv', index=False)
    shutil.copyfile(OUT/'savant_batter_profiles.csv', OUT/'savant_batter_profiles.last_good.csv')
    shutil.copyfile(OUT/'savant_pitcher_stats.csv', OUT/'savant_pitcher_stats.last_good.csv')
    return batter, pitcher


def build_arsenal(pitcher):
    raw = read_required('raw_pitcher_arsenal.csv')
    base_cols = ['player_id','player_name','season','PA','SO','K%','BB%','Whiff%','Swing%',
                 'xwOBA','xBA','xSLG','Hard-Hit%','Barrel%','average_swing_speed',
                 'fast_swing_rate','swords','squared_up_contact']
    base = pitcher[base_cols].copy()
    r = raw.rename(columns={
        'last_name, first_name':'arsenal_player_name','year':'arsenal_season',
        'pitches':'Pitches','put_away':'PutAway%','ba':'BA','slg':'SLG','woba':'wOBA'
    }).copy()
    r['player_id'] = pd.to_numeric(r['player_id'], errors='coerce').astype('Int64')
    base['player_id'] = pd.to_numeric(base['player_id'], errors='coerce').astype('Int64')
    out = r.merge(base, on='player_id', how='left')
    out['player_name'] = out['player_name'].fillna(out.get('arsenal_player_name'))
    out['season'] = out['season'].fillna(out.get('arsenal_season')).fillna(YEAR)
    spec = ['player_id','player_name','season','PA','SO','K%','BB%','Whiff%','Swing%',
            'xwOBA','xBA','xSLG','Hard-Hit%','Barrel%','average_swing_speed',
            'fast_swing_rate','swords','squared_up_contact','pitch_type','pitch_name',
            'pitch_usage','Pitches','PutAway%','BA','SLG','wOBA','run_value_per_100']
    for c in spec:
        if c not in out.columns:
            out[c] = pd.NA
    out = out[spec]
    out['source'] = SOURCE
    out['source_timestamp'] = STAMP
    out['schema_version'] = 'SAVANT_ARSENAL_SCHEMA_V1'
    out['refresh_status'] = 'CURRENT'
    out.to_csv(OUT/'pitch_mix_matchups.csv', index=False)
    shutil.copyfile(OUT/'pitch_mix_matchups.csv', OUT/'pitch_mix_matchups.last_good.csv')
    return out


def statcast_params(start_d, end_d):
    return {
        'all':'true','hfPT':'','hfAB':'','hfGT':'R|','hfPR':'','hfZ':'','stadium':'',
        'hfBBL':'','hfNewZones':'','hfPull':'','hfC':'','hfSea':f'{YEAR}|','hfSit':'',
        'player_type':'batter','hfOuts':'','opponent':'','pitcher_throws':'',
        'batter_stands':'','hfSA':'','game_date_gt':start_d.isoformat(),
        'game_date_lt':end_d.isoformat(),'team':'','position':'','hfRO':'','home_road':'',
        'hfFlag':'','hfBBT':'','metric_1':'','hfInn':'','min_pitches':'0','min_results':'0',
        'group_by':'name','sort_col':'pitches','player_event_sort':'api_p_release_speed',
        'sort_order':'desc','min_pas':'0','type':'details'
    }


def fetch_statcast_chunk(session, start_d, end_d):
    url = 'https://baseballsavant.mlb.com/statcast_search/csv'
    r = session.get(url, params=statcast_params(start_d, end_d), headers=HEADERS, timeout=(10, 120))
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.content.decode('utf-8-sig', errors='replace')), low_memory=False)
    if len(df) >= 24990:
        raise RuntimeError(f'Statcast cap hit for {start_d}..{end_d}: {len(df)} rows')
    keep = ['game_pk','at_bat_number','pitch_number','batter','p_throws','events']
    for c in keep:
        if c not in df.columns:
            raise RuntimeError(f'missing Statcast column {c} for {start_d}..{end_d}')
    return df[keep].copy()


def build_platoon(batter_profile):
    session = requests.Session()
    start = date(YEAR, 3, 1)
    end = min(date(YEAR, 12, 31), datetime.now(timezone.utc).date())
    parts = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=3), end)
        df = fetch_statcast_chunk(session, cur, chunk_end)
        parts.append(df)
        print(f'platoon chunk {cur}..{chunk_end}: {len(df)} rows', flush=True)
        cur = chunk_end + timedelta(days=1)
        time.sleep(0.15)
    pitches = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if pitches.empty:
        raise RuntimeError('No Statcast rows for platoon build')
    for c in ['game_pk','at_bat_number','pitch_number','batter']:
        pitches[c] = pd.to_numeric(pitches[c], errors='coerce')
    pitches = pitches.dropna(subset=['game_pk','at_bat_number','pitch_number','batter','p_throws'])
    pitches['p_throws'] = pitches['p_throws'].astype(str).str.upper().str[0]
    pitches = pitches[pitches['p_throws'].isin(['R','L'])].copy()
    pitches = pitches.sort_values(['game_pk','at_bat_number','pitch_number'])
    pitches = pitches.drop_duplicates(['game_pk','at_bat_number','pitch_number'], keep='last')
    pa = pitches.groupby(['game_pk','at_bat_number'], as_index=False).tail(1).copy()
    pa['is_so'] = pa['events'].astype(str).str.lower().isin(['strikeout','strikeout_double_play']).astype(int)
    agg = pa.groupby(['batter','p_throws']).agg(PA=('batter','size'), SO=('is_so','sum')).reset_index()
    pa_piv = agg.pivot(index='batter', columns='p_throws', values='PA').fillna(0)
    so_piv = agg.pivot(index='batter', columns='p_throws', values='SO').fillna(0)
    ids = sorted(set(pa_piv.index).union(set(so_piv.index)))
    name_map = dict(zip(pd.to_numeric(batter_profile['player_id'], errors='coerce'), batter_profile['player_name']))
    rows = []
    for pid in ids:
        rhp_pa = int(pa_piv.loc[pid,'R']) if 'R' in pa_piv.columns and pid in pa_piv.index else 0
        lhp_pa = int(pa_piv.loc[pid,'L']) if 'L' in pa_piv.columns and pid in pa_piv.index else 0
        rhp_so = int(so_piv.loc[pid,'R']) if 'R' in so_piv.columns and pid in so_piv.index else 0
        lhp_so = int(so_piv.loc[pid,'L']) if 'L' in so_piv.columns and pid in so_piv.index else 0
        overall_pa = rhp_pa + lhp_pa
        overall_so = rhp_so + lhp_so
        if overall_pa <= 0:
            continue
        rows.append({
            'mlbam_id': int(pid), 'player_name': name_map.get(pid, ''), 'team': '', 'season': YEAR,
            'vs_rhp_pa': rhp_pa, 'vs_rhp_so': rhp_so,
            'vs_rhp_k_pct': (100.0*rhp_so/rhp_pa) if rhp_pa else pd.NA,
            'vs_lhp_pa': lhp_pa, 'vs_lhp_so': lhp_so,
            'vs_lhp_k_pct': (100.0*lhp_so/lhp_pa) if lhp_pa else pd.NA,
            'overall_pa': overall_pa, 'overall_so': overall_so,
            'overall_k_pct': 100.0*overall_so/overall_pa,
            'source': SOURCE, 'source_timestamp': STAMP, 'refresh_status': 'CURRENT'
        })
    out = pd.DataFrame(rows)
    cols = ['mlbam_id','player_name','team','season','vs_rhp_pa','vs_rhp_so','vs_rhp_k_pct',
            'vs_lhp_pa','vs_lhp_so','vs_lhp_k_pct','overall_pa','overall_so','overall_k_pct',
            'source','source_timestamp','refresh_status']
    out = out[cols].sort_values('player_name').reset_index(drop=True)
    if len(out) < 500:
        raise RuntimeError(f'platoon sanity check failed: {len(out)} rows')
    out.to_csv(OUT/f'savant_batter_platoon_{YEAR}.csv', index=False)
    shutil.copyfile(OUT/f'savant_batter_platoon_{YEAR}.csv', OUT/f'savant_batter_platoon_{YEAR}.last_good.csv')
    return out


def write_manifests(batter, pitcher, arsenal, platoon):
    main_manifest = {
        'season': YEAR, 'source': SOURCE, 'source_timestamp': STAMP, 'status': 'SUCCESS',
        'refresh_completed_at': STAMP,
        'files': {
            'savant_batter_profiles.csv': len(batter),
            'savant_pitcher_stats.csv': len(pitcher),
            f'savant_batter_platoon_{YEAR}.csv': len(platoon),
        }
    }
    aux_manifest = {
        'season': YEAR, 'source': SOURCE, 'source_timestamp': STAMP, 'status': 'SUCCESS',
        'refresh_completed_at': STAMP,
        'files': {'pitch_mix_matchups.csv': len(arsenal)}
    }
    (OUT/'savant_refresh_manifest.json').write_text(json.dumps(main_manifest, indent=2), encoding='utf-8')
    (OUT/'savant_aux_refresh_manifest.json').write_text(json.dumps(aux_manifest, indent=2), encoding='utf-8')


batter, pitcher = build_profiles()
arsenal = build_arsenal(pitcher)
platoon = build_platoon(batter)
write_manifests(batter, pitcher, arsenal, platoon)
summary = {
    'status':'SUCCESS','timestamp':STAMP,'batter_rows':len(batter),'pitcher_rows':len(pitcher),
    'arsenal_rows':len(arsenal),'platoon_rows':len(platoon),
    'outputs':[p.name for p in sorted(OUT.glob('savant_*'))] + ['pitch_mix_matchups.csv','pitch_mix_matchups.last_good.csv']
}
(OUT/'final_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
print(json.dumps(summary, indent=2))
