"""Render resume-v2.yaml -> resume-v2.pdf.

Run from anywhere: `python render/build.py`. Reads only resume-v2.yaml and writes only
render/build/ (gitignored) plus resume-v2.pdf at the repo root. The canonical files
(resume.yaml, index.html, Nachum_Getzel_Elkind_Resume.pdf) are never touched — that
scoping is deliberate; see .github/workflows/render-v2.yml.

Requires: pip install jinja2 pyyaml playwright && playwright install chromium
"""

import asyncio
import shutil
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_lib import render  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


async def main() -> None:
    data = yaml.safe_load((REPO / "resume-v2.yaml").read_text(encoding="utf-8"))
    result = await render(data, REPO / "render" / "build", pdf=True)
    target = REPO / "resume-v2.pdf"
    shutil.copyfile(result.pdf_path, target)
    print(f"wrote {target}")


asyncio.run(main())
