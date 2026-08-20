import io
import json
import traceback
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
CUSTOM_SELECTIONS = [
    'pa','strikeout','k_percent','bb_percent','whiff_percent','swing_percent',
    'xwoba','xba','xslg','hard_hit_percent','barrel_batted_rate',
    'avg_swing_speed','fast_swing_rate','swords','squared_up_contact','woba'
]

def fetch_csv(name, url, params):
    r = requests.get(url, params=params, headers=HEADERS, timeout=(10, 90))
    info = {
        'status_code': r.status_code,
        'url': r.url,
        'content_type': r.headers.get('content-type'),
        'bytes': len(r.content),
    }
    r.raise_for_status()
    text = r.content.decode('utf-8-sig', errors='replace')
    df = pd.read_csv(io.StringIO(text), low_memory=False)
    df.to_csv(OUT / f'{name}.csv', index=False)
    info.update({'rows': int(len(df)), 'columns': list(df.columns)})
    return info

def custom(kind):
    return fetch_csv(
        f'raw_custom_{kind}',
        'https://baseballsavant.mlb.com/leaderboard/custom',
        {
            'year': YEAR,
            'type': kind,
            'filter': '',
            'min': '1',
            'selections': ','.join(CUSTOM_SELECTIONS),
            'chart': 'false',
            'x': 'pa',
            'y': 'pa',
            'r': 'no',
            'chartType': 'beeswarm',
            'sort': 'pa',
            'sortDir': 'desc',
            'csv': 'true',
        },
    )

def arsenal():
    return fetch_csv(
        'raw_pitcher_arsenal',
        'https://baseballsavant.mlb.com/leaderboard/pitch-arsenal-stats',
        {'type':'pitcher','pitchType':'','year':YEAR,'team':'','min':'1','csv':'true'},
    )

def platoon(hand):
    params = {
        'all':'true','hfPT':'','hfAB':'','hfGT':'R|','hfPR':'','hfZ':'',
        'hfStadium':'','hfBBL':'','hfNewZones':'','hfPull':'','hfC':'',
        'hfSea':f'{YEAR}|','hfSit':'','player_type':'batter','hfOuts':'',
        'hfOpponent':'','pitcher_throws':hand,'batter_stands':'','hfSA':'',
        'game_date_gt':'','game_date_lt':'','hfMo':'','hfTeam':'','home_road':'',
        'hfRO':'','position':'','hfInfield':'','hfOutfield':'','hfInn':'',
        'hfBBT':'','hfFlag':'','metric_1':'','group_by':'name','min_pitches':'0',
        'min_results':'0','min_pas':'0','sort_col':'pitches',
        'player_event_sort':'api_p_release_speed','sort_order':'desc',
        'chk_stats_pa':'on','chk_stats_k_percent':'on','type':'details',
    }
    return fetch_csv(f'raw_platoon_{hand}', 'https://baseballsavant.mlb.com/statcast_search/csv', params)

summary = {}
for name, fn in [
    ('custom_batter', lambda: custom('batter')),
    ('custom_pitcher', lambda: custom('pitcher')),
    ('pitcher_arsenal', arsenal),
    ('platoon_R', lambda: platoon('R')),
    ('platoon_L', lambda: platoon('L')),
]:
    try:
        summary[name] = {'ok': True, **fn()}
    except Exception as exc:
        summary[name] = {'ok': False, 'error': f'{type(exc).__name__}: {exc}', 'traceback': traceback.format_exc()}

(OUT / 'summary.json').write_text(json.dumps(summary, indent=2, default=str), encoding='utf-8')
print(json.dumps(summary, indent=2, default=str))
if not all(v.get('ok') for v in summary.values()):
    raise SystemExit(1)
