"""Create the synthetic demo attachment RBI_Statement.zip for the attachment-analysis demo.

The archive contains three INERT text files that merely carry the names
Statement.pdf, Update.exe and helper.dll. Nothing in it is a real PDF, program
or library, and it is never executed. Usage:  python scripts/make_demo_attachment.py [output_dir]
"""

import sys
import zipfile
from pathlib import Path

ENTRIES = {
    "Statement.pdf": "Synthetic placeholder. Not a real PDF.\n",
    "Update.exe": "Synthetic placeholder. Not a real program.\n",
    "helper.dll": "Synthetic placeholder. Not a real library.\n",
}

out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
out_dir.mkdir(parents=True, exist_ok=True)
target = out_dir / "RBI_Statement.zip"
with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
    for name, text in ENTRIES.items():
        archive.writestr(name, text)
print(f"Wrote {target} ({target.stat().st_size} bytes)")
