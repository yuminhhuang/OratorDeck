from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]


def load_script(filename: str):
    module_name = f"oratordeck_test_{filename.removesuffix('.py').replace('-', '_')}"
    path = PROJECT_DIR / "scripts" / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
