import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# PAC_EXAMPLE_SRC points at an alternate implementation (e.g. solution/src); src/ still supplies the types.
for p in [ROOT / "src", Path(os.environ["PAC_EXAMPLE_SRC"]) if os.getenv("PAC_EXAMPLE_SRC") else None]:
    if p is not None:
        sys.path.insert(0, str(p))
