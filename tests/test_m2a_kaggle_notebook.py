from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_kaggle_v2_smoke_notebook_is_valid_and_code_cells_compile():
    notebook_path = ROOT / "experiments/kaggle_upload/kaggle_m2a_v2_smoke.ipynb"
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    assert notebook["nbformat"] == 4
    code_cells = [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]
    assert len(code_cells) >= 4
    for index, cell in enumerate(code_cells):
        compile("".join(cell["source"]), f"{notebook_path}:cell{index}", "exec")
