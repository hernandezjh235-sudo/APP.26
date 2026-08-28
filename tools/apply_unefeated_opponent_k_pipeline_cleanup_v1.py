#!/usr/bin/env python3
"""Guarded opponent-K cleanup for the older Undefeated app.

This script runs against the Railway checkout after bootstrap_v1104.py. Because
this repository's app.py is very large, the patch is deliberately structure-
guarded and fail-closed:

- It only changes APP97 when the app contains the same Matchup-Intel recent-team
  K family, season-vs-hand field, and current-lineup field used by the sibling
  builds.
- APP97 then uses season-vs-hand as its team baseline and blends the current
  lineup downstream, instead of reusing L3/L5/L10/L15/L30 recent team form a
  second time. The legacy APP97 recent blend stays available as audit/fallback.
- When the matching public K-card renderer exists, "Exposure" is changed to the
  true lineup exposure and L5/L10 are labeled as calendar DAYS vs pitcher hand.
- If the expected structure is absent, the script prints a safe NO-OP and exits
  successfully without changing app.py.

Scope is opponent-K pipeline/card labeling only. It does not alter pitcher
skill, BF/IP/workload, probabilities/distributions, grading, save/refresh,
Savant refresh, Pitching Outs, Fantasy Score, Moneyline, or Undefeated-specific
decision/resolver logic.
"""
from __future__ import annotations

import argparse
import ast
import py_compile
import re
import tempfile
from pathlib import Path

MARKER = "UNDEFEATED_OPP_K_PIPELINE_CLEANUP_V1_2026_08_28"
TARGET_FN = "_app97_recent_hand_profile"

REQUIRED_MODEL_ANCHORS = (
    "Recency Team K Blend",
    "Team K% Season vs Hand",
    "APP88 Batter Lineup K%",
)

WRAPPER = r'''
def _app97_recent_hand_profile(row):
    """APP97 team baseline without duplicate recent-team-K influence.

    Matchup Intel already owns the PA-shrunk recent team-K family. APP97 uses
    season vs hand as the stable team baseline; its existing downstream logic
    still blends the current lineup once. The old recent blend is retained for
    audit and as a fail-safe fallback when a season-vs-hand value is missing.
    """
    legacy_env, split_suspect, legacy_detail = _legacy_app97_recent_hand_profile(row)
    season_hand = _app97_pct(row.get("Team K% Season vs Hand"), None)
    if season_hand is None:
        season_hand = _app97_pct(row.get("Opponent K% vs Pitcher Hand"), None)
    if season_hand is None:
        return legacy_env, split_suspect, f"FALLBACK legacy recent blend; {legacy_detail}"
    detail = (
        f"season_vs_hand_only {season_hand:.1f}; recent team form applied once upstream "
        f"in Matchup Intel; legacy APP97 recent blend audit={legacy_env:.1f}"
        if legacy_env is not None else
        f"season_vs_hand_only {season_hand:.1f}; recent team form applied once upstream in Matchup Intel"
    )
    return season_hand, split_suspect, detail
'''.lstrip("\n")


def _replace_active_app97(text: str) -> tuple[str, int]:
    tree = ast.parse(text)
    nodes = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef)
        and n.name == TARGET_FN
        and getattr(n, "col_offset", 1) == 0
    ]
    if not nodes:
        return text, 0

    # Python's active top-level definition is the last one in source order.
    node = max(nodes, key=lambda n: n.lineno)
    lines = text.splitlines(keepends=True)
    start, end = node.lineno - 1, node.end_lineno
    original = "".join(lines[start:end])
    token = f"def {TARGET_FN}("
    if token not in original:
        return text, 0
    legacy = original.replace(token, f"def _legacy{TARGET_FN}(", 1).rstrip("\r\n")
    lines[start:end] = [legacy + "\n\n" + WRAPPER + "\n"]
    return "".join(lines), 1


def _patch_card(text: str) -> tuple[str, dict]:
    stats = {"source": 0, "season_insert": 0, "labels": 0}

    # Replace the misleading card source with real lineup exposure first. The
    # fallbacks preserve display availability if a lineup field is unavailable.
    source_old = 'opp_k = _kclean_fmt(_kclean_pick(row, ["Opponent K% vs Pitcher Hand", "APP97 Opponent K Environment", "APP88 Batter Lineup K%"], ""), 1)'
    source_new = '''opp_k = _kclean_fmt(_kclean_pick(row, [\n                "Lineup Exposure K%", "lineup_exposure_k_pct",\n                "UB Lineup Exposure K%", "APP88 Batter Lineup K%", "Lineup K%",\n                "Opponent K% vs Pitcher Hand", "APP97 Opponent K Environment"\n            ], ""), 1)'''
    if source_old in text:
        stats["source"] = text.count(source_old)
        text = text.replace(source_old, source_new)

    # Add a season-vs-hand display variable once per matching renderer block.
    hand_line = 'hand_window = "LHP" if str(hand).upper().startswith("L") else "RHP"'
    season_line = '''hand_window = "LHP" if str(hand).upper().startswith("L") else "RHP"\n\n            opp_season = _kclean_fmt(_kclean_pick(row, [\n                "Team K% Season vs Hand", f"Opp K% vs {hand_window} Official",\n                "Opponent K% vs Pitcher Hand"\n            ], ""), 1)'''
    if source_new in text:
        # Only modify hand_window occurrences that occur shortly after our new
        # source block, avoiding unrelated renderers that use the same variable.
        pos = 0
        chunks = []
        changed = 0
        while True:
            s = text.find(source_new, pos)
            if s < 0:
                chunks.append(text[pos:])
                break
            h = text.find(hand_line, s, min(len(text), s + 1800))
            if h < 0:
                chunks.append(text[pos:s + len(source_new)])
                pos = s + len(source_new)
                continue
            chunks.append(text[pos:h])
            chunks.append(season_line)
            pos = h + len(hand_line)
            changed += 1
        if changed:
            text = "".join(chunks)
            stats["season_insert"] = changed

    # Public labels. Replace only when opp_season exists somewhere, so no
    # undefined variable can be introduced.
    if "opp_season = _kclean_fmt" in text:
        replacements = {
            'if opp_k != "—": _opp_lines.append(f"Exposure {opp_k}%")':
                'if opp_k != "—": _opp_lines.append(f"Lineup Exposure {opp_k}%")\n\n            if opp_season != "—": _opp_lines.append(f"Season vs {hand_window} {opp_season}%")',
            'if opp_l10 != "—": _opp_lines.append(f"L10 {opp_l10}%")':
                'if opp_l10 != "—": _opp_lines.append(f"Last 10 Days vs {hand_window} {opp_l10}%")',
            'if opp_l5 != "—": _opp_lines.append(f"L5 {opp_l5}%")':
                'if opp_l5 != "—": _opp_lines.append(f"Last 5 Days vs {hand_window} {opp_l5}%")',
        }
        for old, new in replacements.items():
            if old in text:
                n = text.count(old)
                text = text.replace(old, new)
                stats["labels"] += n

    return text, stats


def patch_text(text: str) -> tuple[str, dict]:
    if MARKER in text:
        return text, {"status": "ALREADY_APPLIED"}

    missing = [a for a in REQUIRED_MODEL_ANCHORS if a not in text]
    if missing:
        return text, {"status": "SAFE_NOOP_MISSING_MODEL_ANCHORS", "missing": missing}

    out, fn_count = _replace_active_app97(text)
    if fn_count != 1:
        return text, {"status": "SAFE_NOOP_APP97_ACTIVE_FUNCTION_NOT_FOUND", "functions": fn_count}

    out, card_stats = _patch_card(out)
    out = f"# {MARKER}\n" + out
    ast.parse(out)
    return out, {
        "status": "PATCH_READY",
        "active_app97_functions": fn_count,
        "card": card_stats,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="app.py")
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()

    path = Path(args.app)
    original = path.read_text(encoding="utf-8-sig")
    updated, stats = patch_text(original)

    if updated == original:
        print(f"{MARKER}: {stats}")
        return 0

    # Compile the complete ~multi-MB app before replacing the checkout copy.
    with tempfile.TemporaryDirectory() as td:
        probe = Path(td) / "app.py"
        probe.write_text(updated, encoding="utf-8")
        py_compile.compile(str(probe), doraise=True)

    if args.check_only:
        print(f"{MARKER}: CHECK PASS {stats}")
        return 0

    tmp = path.with_suffix(path.suffix + ".opp_k_tmp")
    tmp.write_text(updated, encoding="utf-8")
    tmp.replace(path)
    print(f"{MARKER}: APPLIED {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
