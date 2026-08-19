from pathlib import Path
import base64
import gzip
import hashlib
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
PAYLOAD = ROOT / ".github" / "v1103_payload" / "patch.b64"
EXPECTED_PATCH_SHA256 = "6b0cc4cbffdc3a93e04b165c11c8f8b66f86fb65e5233112d0509f65eff2f15d"

# First preserve the proven V1.10.2 Savant bootstrap exactly as-is.
subprocess.run([sys.executable, str(ROOT / "bootstrap_v1102.py")], cwd=ROOT, check=True)

# Then layer only the tested V1.10.3 decision-integrity guards.
raw = gzip.decompress(base64.b64decode("".join(PAYLOAD.read_text().split())))
if hashlib.sha256(raw).hexdigest() != EXPECTED_PATCH_SHA256:
    raise RuntimeError("V1.10.3 patch checksum mismatch; refusing to patch")
patch_path = ROOT / ".github" / "v1103_apply_patch.py"
patch_path.write_bytes(raw)
subprocess.run([sys.executable, str(patch_path)], cwd=ROOT, check=True)

print("Applied V1.10.2 Savant profile + V1.10.3 Net Rescue guards")
