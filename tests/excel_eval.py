"""Evaluate an openpyxl-written workbook with the `formulas` engine (no Excel needed)."""
from pathlib import Path

import formulas


def evaluate(path: Path):
    model = formulas.ExcelModel().loads(str(path)).finish()
    sol = model.calculate()
    name = path.name.upper()
    out = {}
    for key, val in sol.items():
        k = key.upper().replace("'", "")
        prefix = f"[{name}]"
        if not k.startswith(prefix) or ":" in k:
            continue
        sheet, ref = k[len(prefix):].split("!")
        try:
            out[(sheet, ref)] = val.value[0, 0]
        except Exception:  # noqa: BLE001
            out[(sheet, ref)] = val

    def get(sheet: str, ref: str):
        v = out.get((sheet.upper(), ref.upper()))
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return str(v)

    return get, out
