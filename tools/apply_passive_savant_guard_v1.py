#!/usr/bin/env python3
from __future__ import annotations

import argparse
import py_compile
import tempfile
from pathlib import Path

MARKER = "UNDEFEATED_PASSIVE_SAVANT_GUARD_V1_2026_08_28"
ANCHOR = "def _impl_render_kproj_tab_08(board):"
OLD_CALL = "_v269_start_savant_refresh_if_needed(board)"
NEW_CALL = "_unef_passive_savant_status_only(board)"

BLOCK = r'''
# =============================================================================
# UNDEFEATED_PASSIVE_SAVANT_GUARD_V1_2026_08_28
# Runtime-only stability guard. Normal Streamlit reruns/read-only renders use
# cached Savant health only. Network refresh remains available through the
# explicit REFRESH LIVE BOARD path installed by Manual Refresh / Board State V2.1.
# Projection math is untouched.
# =============================================================================
def _unef_passive_savant_status_only(board=None):
    try:
        svc = globals().get("_v269_savant_service")
        if callable(svc):
            service = svc()
            if hasattr(service, "health"):
                return service.health()
    except Exception:
        pass
    return {"status": "CACHE_ONLY"}
'''.strip()


def patch_text(text: str) -> str:
    if MARKER in text:
        return text
    text = text.replace("\r\n", "\n")
    if ANCHOR not in text:
        raise RuntimeError("K renderer anchor not found; app left unchanged")
    if OLD_CALL not in text:
        raise RuntimeError("Passive Savant render call not found; app left unchanged")
    pos = text.index(ANCHOR)
    text = text[:pos] + BLOCK + "\n\n\n" + text[pos:]
    text = text.replace(OLD_CALL, NEW_CALL)
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="app.py")
    args = ap.parse_args()
    path = Path(args.app)
    original = path.read_text(encoding="utf-8")
    updated = patch_text(original)
    if updated != original:
        path.write_text(updated, encoding="utf-8")
    with tempfile.TemporaryDirectory() as td:
        py_compile.compile(str(path), cfile=str(Path(td) / "app.pyc"), doraise=True)
    print(f"Undefeated Passive Savant Guard V1 READY: {path}")


if __name__ == "__main__":
    main()
