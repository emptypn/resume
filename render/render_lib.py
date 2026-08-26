"""Resume rendering: YAML -> self-contained HTML -> PDF.

The successor to this repo's retired `create_pdf.py`, with its four defects fixed:
the template loader is bound to this package's own `templates/` (renders from any
CWD), the stylesheet is inlined into the HTML (one self-contained file), YAML block
scalars go through the `richtext` filters (prose stays prose, "- " runs become real
lists), and nothing swallows exceptions (a failed render fails loudly).

PDFs come from Playwright Chromium `page.pdf()`, not WeasyPrint: WeasyPrint needs
GTK, which cannot be assumed on contributors' machines or CI.

Autoescape is off, as upstream — resume YAML legitimately contains inline markup
(`<em>`, anchors). Do not put untrusted text into the YAML.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

log = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"
TEMPLATE_NAME = "resume.html.template"
STYLESHEET_NAME = "style.css"

#: Canonical top-to-bottom section order; a variant may reorder or drop entries, and
#: anything it omits is appended in this order so no section is ever silently lost.
SECTION_ORDER: tuple[str, ...] = (
    "summary",
    "experience",  # the 2026-08-25 single-resume design (canonical-PDF layout)
    "what_i_bring",
    "technical_expertise",
    "current_position",
    "past_positions",
    "projects",
    "patents_publications",
    "education",
    "languages",
)

#: Names the renderer injects into the template namespace. Resume YAML is splatted into
#: that same namespace (upstream's `template.render(**data)`), so a top-level key with one
#: of these names would silently shadow the injected value — that is a fail, not a warning.
#: `section_order` is deliberately NOT reserved: `resolve_section_order()` reads it out of
#: the YAML, which is how a variant asks to lead with the section that fits the posting.
RESERVED_KEYS = frozenset({"inline_css", "pdf_link"})

HTML_FILENAME = "index.html"
PDF_FILENAME = "resume.pdf"
PDF_TIMEOUT_MS = 30_000

_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.*)$")


class RenderError(RuntimeError):
    """The resume could not be rendered. Never swallowed here (fix 4)."""


class PdfUnavailableError(RenderError):
    """Chromium could not be launched — the HTML rendered, the PDF did not."""


@dataclass(frozen=True)
class RenderedVariant:
    html_path: Path
    pdf_path: Path | None = None


# ----------------------------------------------------------------------------- fix 3


def richtext(value: Any) -> str:
    """Render YAML block text or a list as real HTML structure.

    A resume block scalar mixes two shapes the author means differently::

        description: |
          Architected and developed a chess engine from scratch.
          - Implemented game logic using OO design patterns.
          - Optimized move generation for performance.

    The lead line is prose; the "- " lines are bullets. Interpolated raw (upstream) the
    whole thing collapses into one paragraph. Here the prose run becomes a `<p>` — joined
    with spaces, because a newline inside a YAML block scalar is a soft wrap the author
    inserted for editor width, not a line break they want on the page — and the bullet run
    becomes a `<ul>`. A blank line starts a new paragraph. Lists pass straight to `<ul>`.
    """
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        items = [str(item).strip() for item in value]
        items = [item for item in items if item]
        return "<ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>" if items else ""
    if not isinstance(value, str):
        return str(value)

    blocks: list[str] = []
    paragraph: list[str] = []
    bullets: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append("<p>" + " ".join(paragraph) + "</p>")
            paragraph.clear()

    def flush_bullets() -> None:
        if bullets:
            blocks.append("<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
            bullets.clear()

    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            flush_bullets()
            flush_paragraph()
            continue
        bullet = _BULLET_RE.match(raw_line)
        if bullet:
            flush_paragraph()
            bullets.append(bullet.group(1).strip())
        else:
            flush_bullets()
            paragraph.append(line)
    flush_bullets()
    flush_paragraph()
    return "\n".join(blocks)


def richtext_inline(value: Any) -> str:
    """Flow text for a spot that is already inside a `<p>` or `<li>`.

    `richtext` wraps its output in block elements, which is wrong when the template has
    already opened one — nested `<p>` silently splits the container in HTML. Here a YAML
    block scalar's newlines are treated as the soft wraps they are (joined with spaces)
    and nothing else is added.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        return str(value)
    return " ".join(line.strip() for line in value.splitlines() if line.strip())


# ------------------------------------------------------------------------- fixes 1 & 2


def _environment() -> Environment:
    """Jinja bound to this package's own templates directory (fix 1).

    `StrictUndefined` is deliberate: a template that reads a field the YAML does not have
    must raise rather than render an empty gap into a document a human will send. Optional
    sections are guarded with `is defined` in the template, so absence is expressive and
    only a genuine mistake reaches the exception.
    """
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=False,  # noqa: S701 - resume YAML carries intentional inline markup; see module docstring
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    env.filters["richtext"] = richtext
    env.filters["richtext_inline"] = richtext_inline
    return env


def load_stylesheet() -> str:
    try:
        return (TEMPLATE_DIR / STYLESHEET_NAME).read_text(encoding="utf-8")
    except OSError as exc:
        raise RenderError(f"vendored stylesheet missing at {TEMPLATE_DIR / STYLESHEET_NAME}") from exc


def resolve_section_order(yaml_data: dict[str, Any]) -> list[str]:
    """The requested order, filtered to known sections, with the rest appended.

    Dropping a section from the order would silently delete resume content, so anything
    the caller did not mention keeps its canonical position instead.
    """
    requested = yaml_data.get("section_order") or []
    if isinstance(requested, str):
        requested = [requested]
    order = [s for s in requested if s in SECTION_ORDER]
    order += [s for s in SECTION_ORDER if s not in order]
    return order


def validate(yaml_data: dict[str, Any]) -> None:
    """Fail loudly on the shapes the template cannot express (fix 4)."""
    if not isinstance(yaml_data, dict):
        raise RenderError(f"resume data must be a mapping, got {type(yaml_data).__name__}")
    collisions = sorted(RESERVED_KEYS & set(yaml_data))
    if collisions:
        raise RenderError(
            f"resume YAML uses reserved top-level key(s) {collisions}: they would shadow the "
            "values the renderer injects. Rename them."
        )
    header = yaml_data.get("header")
    if not isinstance(header, dict) or not header.get("name"):
        raise RenderError("resume YAML needs header.name — it titles the page and the PDF")
    contact = header.get("contact")
    if contact is not None and (not isinstance(contact, dict) or not contact.get("email")):
        raise RenderError("header.contact is present but has no email")


def render_html_string(yaml_data: dict[str, Any], *, pdf_link: str | None = None) -> str:
    """Render the page. Raises RenderError on template or data problems."""
    validate(yaml_data)
    context = dict(yaml_data)
    context.pop("section_order", None)
    context["section_order"] = resolve_section_order(yaml_data)
    context["inline_css"] = load_stylesheet()
    context["pdf_link"] = pdf_link
    try:
        return _environment().get_template(TEMPLATE_NAME).render(**context)
    except RenderError:
        raise
    except Exception as exc:
        raise RenderError(f"{type(exc).__name__}: {exc}") from exc


def render_html(
    yaml_data: dict[str, Any],
    out_dir: Path,
    *,
    pdf_link: str | None = PDF_FILENAME,
    filename: str = HTML_FILENAME,
) -> Path:
    """Write the self-contained HTML into `out_dir` and return its path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / filename
    html_path.write_text(render_html_string(yaml_data, pdf_link=pdf_link), encoding="utf-8")
    return html_path


# ------------------------------------------------------------------------------- PDF


class PdfSession:
    """A Chromium kept alive across several renders.

    Launching costs about a second, which is per-variant overhead worth avoiding on a
    batch. Unlike the careers-page ladder — where a missing browser legitimately means
    "top out at T1" — an absent Chromium here is a hard failure: the PDF is the artifact
    that gets attached to an application, and quietly shipping HTML-only would be the
    swallowed-exception bug this module exists to fix.
    """

    def __init__(self, *, timeout_ms: int = PDF_TIMEOUT_MS) -> None:
        self._timeout_ms = timeout_ms
        self._lock = asyncio.Lock()
        self._playwright: Any = None
        self._browser: Any = None

    async def __aenter__(self) -> PdfSession:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception as exc:  # noqa: BLE001 - teardown must not mask the real error
                log.debug("browser close failed: %s", exc)
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception as exc:  # noqa: BLE001
                log.debug("playwright stop failed: %s", exc)
        self._browser = self._playwright = None

    async def _ensure_browser(self) -> Any:
        async with self._lock:
            if self._browser is not None:
                return self._browser
            try:
                from playwright.async_api import async_playwright

                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(headless=True)
            except Exception as exc:
                raise PdfUnavailableError(
                    f"Chromium could not be launched ({type(exc).__name__}: {exc}). "
                    "Run `python -m uv run playwright install chromium`."
                ) from exc
            return self._browser

    async def to_pdf(self, html_path: Path, pdf_path: Path) -> Path:
        """Print a local HTML file to A4 PDF with backgrounds on."""
        browser = await self._ensure_browser()
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        page = None
        try:
            page = await browser.new_page()
            await page.goto(html_path.resolve().as_uri(), wait_until="load", timeout=self._timeout_ms)
            await page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                # The vendored stylesheet owns the page box (@page A4/15mm); zero here so
                # Chromium's default half-inch does not stack on top of it.
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                prefer_css_page_size=True,
            )
        finally:
            if page is not None:
                await page.close()
        if not pdf_path.exists() or pdf_path.stat().st_size == 0:
            raise RenderError(f"Chromium produced no PDF at {pdf_path}")
        return pdf_path


async def render(
    yaml_data: dict[str, Any],
    out_dir: Path,
    *,
    pdf: bool = True,
    pdf_session: PdfSession | None = None,
) -> RenderedVariant:
    """Render one resume into `out_dir` as `index.html` (+ `resume.pdf`).

    Async because the PDF step drives Playwright, whose sync API cannot run inside the
    pipeline's event loop. `pdf=False` renders HTML only; it does not exist to paper over
    a missing browser, which raises.
    """
    html_path = render_html(yaml_data, out_dir, pdf_link=PDF_FILENAME if pdf else None)
    if not pdf:
        return RenderedVariant(html_path=html_path)

    pdf_path = out_dir / PDF_FILENAME
    if pdf_session is not None:
        await pdf_session.to_pdf(html_path, pdf_path)
    else:
        async with PdfSession() as session:
            await session.to_pdf(html_path, pdf_path)
    return RenderedVariant(html_path=html_path, pdf_path=pdf_path)
