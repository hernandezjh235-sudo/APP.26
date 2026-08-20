# TEMP BRANCH TRIGGER ONLY — production main is unchanged.
# FINAL AUG 20 CSV BUILD TRIGGER
from pathlib import Path
import base64
import gzip
import hashlib
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
PAYLOAD = ROOT / ".github" / "v1102_payload"
EXPECTED_DATA_SHA256 = "d03d4e3c87fc3bc3f3aa4cc159529c6f298ad449bc16b5e8e08dc13fb97cad68"
EXPECTED_PATCH_SHA256 = "726100a12a694e3c4a381f7a7f55503ee00829aff6aa5f92486d2a23e651da5d"

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def decode_gzip_b64(text: str) -> bytes:
    return gzip.decompress(base64.b64decode("".join(text.split())))

# Reconstruct exact user Savant export.
data_text = "".join((PAYLOAD / f"data{i:02d}.b64").read_text() for i in range(1, 6))
data = decode_gzip_b64(data_text)
if sha256_bytes(data) != EXPECTED_DATA_SHA256:
    raise RuntimeError("Savant payload checksum mismatch; refusing to patch")
data_path = ROOT / "learning_data" / "savant_full_pitcher_profiles.csv"
data_path.parent.mkdir(parents=True, exist_ok=True)
data_path.write_bytes(data)

# Reconstruct and run the tested V1.10.2 patcher.
patch = decode_gzip_b64((PAYLOAD / "patch.b64").read_text())
if sha256_bytes(patch) != EXPECTED_PATCH_SHA256:
    raise RuntimeError("App patch payload checksum mismatch; refusing to patch")
patch_path = ROOT / ".github" / "v1102_apply_patch.py"
patch_path.write_bytes(patch)
subprocess.run([sys.executable, str(patch_path)], cwd=ROOT, check=True)

print(f"Installed Savant full pitcher profile: {data_path} ({len(data)} bytes)")
print("Applied Undefeated V1.10.2 Savant Full Profile patch to app.py")
