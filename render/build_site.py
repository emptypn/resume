"""Render resume-v2.yaml -> index.html + resume.pdf + resume-v2.pdf at the repo root.

Run by .github/workflows/build.yml on every push to master: the YAML is the source of
truth and the committed rendered files ARE the deployed site. Writes only the three
rendered artifacts; the retired toolchain (create_pdf.py, resume.yaml) and the archived
canonical PDFs are never touched.

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
    shutil.copyfile(result.html_path, REPO / "index.html")
    # index.html's "View PDF" button links resume.pdf; resume-v2.pdf stays in
    # lockstep so the file the review branch produced never goes stale on master.
    shutil.copyfile(result.pdf_path, REPO / "resume.pdf")
    shutil.copyfile(result.pdf_path, REPO / "resume-v2.pdf")
    print("wrote index.html, resume.pdf, resume-v2.pdf")


asyncio.run(main())
