from pathlib import Path
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parent

# Preserve the proven V1.10.3 bootstrap/patch chain exactly.
subprocess.run([sys.executable, str(ROOT / 'bootstrap_v1103.py')], cwd=ROOT, check=True)

# Validate the restored live Savant helper before the app imports it.
subprocess.run([sys.executable, '-m', 'py_compile', str(ROOT / 'merge_v269_safe_update.py')], cwd=ROOT, check=True)

# Best-effort preflight refresh so batter vs-hand data is READY on first render.
# Network/schema failures never block deployment; the app keeps LAST_GOOD and retries.
try:
    from merge_v269_safe_update import SavantDataService
    service = SavantDataService(cache_dir=ROOT / 'learning_data')
    result = service.refresh(force=False)
    safe = {
        'status': result.get('status'),
        'refresh': result.get('refresh'),
        'rows': result.get('row_count'),
        'source': result.get('source'),
        'error': result.get('error'),
    }
    print('V1.10.4 Savant batter preflight:', json.dumps(safe, default=str))
except Exception as exc:
    print(f'V1.10.4 Savant batter preflight warning: {type(exc).__name__}: {exc}')

print('Applied V1.10.3 + V1.10.4 live Savant batter vs-hand bridge')
