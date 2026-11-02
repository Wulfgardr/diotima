#!/usr/bin/env python3
"""Generate Diotima's GitHub look: verdict glyphs and README banners (SVG).

Palette from the Diotima visual identity: ivory paper, slate ink, forest green for
verified provenance, terracotta for preserved dissent. Glyph colours are mid-tones that
read on both GitHub light and dark backgrounds.

    python3 scripts/build_brand.py            # writes assets/glyphs/*.svg, assets/banner-*.svg
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
COPY = ASSETS / "brand.json"

IVORY, SLATE, NIGHT = "#F6F5F0", "#1C252C", "#0F1519"
GREEN, GREEN_MID, GREEN_LIGHT = "#146354", "#1F8A72", "#4FB39A"
TERRA, TERRA_MID = "#B85D3B", "#C96A44"
LICHEN, GREY_MID = "#D4DED9", "#8B98A0"

SERIF = "Georgia, 'Iowan Old Style', 'Times New Roman', serif"
SANS = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"


def _svg(body: str, title: str, size: int = 24) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="{size}" height="{size}" '
        f'role="img" aria-label="{escape(title)}"><title>{escape(title)}</title>{body}</svg>\n'
    )


GLYPHS: dict[str, tuple[str, str]] = {
    "supports": (
        f'<circle cx="12" cy="12" r="9" fill="{GREEN_MID}"/>'
        '<path d="M7.6 12.3l3 3 5.8-6.2" fill="none" stroke="#fff" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round"/>',
        "Supported: the verbatim passage was found and backs the claim",
    ),
    "partial": (
        f'<circle cx="12" cy="12" r="8.2" fill="none" stroke="{GREEN_MID}" stroke-width="1.8"/>'
        f'<path d="M12 3.8a8.2 8.2 0 0 0 0 16.4z" fill="{GREEN_MID}"/>',
        "Partial: the passage backs only part of the claim",
    ),
    "contradicts": (
        f'<circle cx="12" cy="12" r="9" fill="{TERRA_MID}"/>'
        '<path d="M7.5 12h9" stroke="#fff" stroke-width="2.4" stroke-linecap="round"/>',
        "Contradicts: the source says otherwise; kept visible",
    ),
    "insufficient": (
        f'<circle cx="12" cy="12" r="8.2" fill="none" stroke="{GREY_MID}" stroke-width="1.8"/>'
        f'<circle cx="12" cy="12" r="2.4" fill="{GREY_MID}"/>',
        "Insufficient: the passage is too thin to judge the claim",
    ),
    "not_verifiable": (
        f'<circle cx="12" cy="12" r="8.2" fill="none" stroke="{GREY_MID}" stroke-width="1.8" '
        'stroke-dasharray="3 2.4"/>'
        f'<path d="M8.2 15.8l7.6-7.6" stroke="{GREY_MID}" stroke-width="1.8" stroke-linecap="round"/>',
        "Not verifiable: no passage found in an accessible source",
    ),
    "verified_passage": (
        f'<path d="M5.5 5.5L12 12l-6.5 6.5M12 12h7" fill="none" stroke="{GREEN_MID}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="5.5" cy="5.5" r="2.6" fill="{GREEN_MID}"/>'
        f'<circle cx="12" cy="12" r="2.9" fill="{GREEN_MID}"/>'
        f'<circle cx="5.5" cy="18.5" r="2.6" fill="{GREEN_MID}"/>'
        f'<circle cx="19.5" cy="12" r="2.3" fill="none" stroke="{GREEN_MID}" stroke-width="1.6"/>',
        "Verified passage: claim, quote and source linked by code",
    ),
    "full_text": (
        f'<path d="M6 3.5h8.5L18.5 7.5V20.5H6z" fill="none" stroke="{GREEN_MID}" stroke-width="1.6" '
        'stroke-linejoin="round"/>'
        f'<path d="M8.5 10h7.5M8.5 13h7.5M8.5 16h7.5M8.5 7h4" stroke="{GREEN_MID}" stroke-width="1.5" '
        'stroke-linecap="round"/>',
        "Full text: the judgement rests on the full text",
    ),
    "abstract_only": (
        f'<path d="M6 3.5h8.5L18.5 7.5V20.5H6z" fill="none" stroke="{GREY_MID}" stroke-width="1.6" '
        'stroke-linejoin="round" stroke-dasharray="2.6 1.8"/>'
        f'<path d="M8.5 7h4M8.5 10h7.5" stroke="{GREY_MID}" stroke-width="1.5" stroke-linecap="round"/>',
        "Abstract only: quantitative claims cannot be verified from it",
    ),
}

# The geometric mark from the Diotima identity (128x128), reused inside the banners.
MARK = f"""
  <rect x="4" y="4" width="120" height="120" rx="22" fill="{IVORY}" stroke="{LICHEN}" stroke-width="2"/>
  <path d="M22 36 V94 H58 C61 97 67 97 70 94 H106 V36" fill="none" stroke="{GREEN}" stroke-width="3.5"
    stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M27 31 H54 C59 31 62 34 64 38 C66 34 69 31 74 31 H101 V88 H71 C67 88 65 90 64 92 C63 90 61 88 57
    88 H27 Z" fill="#FFFFFF" stroke="{SLATE}" stroke-width="2.8" stroke-linejoin="round"/>
  <line x1="64" y1="38" x2="64" y2="91" stroke="{SLATE}" stroke-width="2.4" stroke-linecap="round"/>
  <circle cx="80" cy="56" r="16" fill="none" stroke="{GREEN}" stroke-width="2" stroke-dasharray="3 2.5"/>
  <line x1="80" y1="37" x2="80" y2="43" stroke="{SLATE}" stroke-width="2.2" stroke-linecap="round"/>
  <circle cx="80" cy="35" r="2.5" fill="none" stroke="{SLATE}" stroke-width="2"/>
  <path d="M38 46 L52 62 L38 75" fill="none" stroke="{SLATE}" stroke-width="2.6" stroke-linecap="round"
    stroke-linejoin="round"/>
  <line x1="52" y1="62" x2="75" y2="62" stroke="{GREEN}" stroke-width="2.6" stroke-linecap="round"/>
  <path d="M45 45 C45 40 48 37 48 34 C48 37 51 40 51 45 C51 47.8 49.7 49.5 48 49.5 C46.3 49.5 45 47.8 45 45 Z"
    fill="{GREEN}"/>
  <circle cx="38" cy="46" r="4.5" fill="{GREEN}" stroke="{SLATE}" stroke-width="2"/>
  <circle cx="52" cy="62" r="5" fill="{GREEN}" stroke="{SLATE}" stroke-width="2"/>
  <circle cx="38" cy="75" r="4.5" fill="{GREEN}" stroke="{SLATE}" stroke-width="2"/>
  <circle cx="80" cy="62" r="12" fill="{IVORY}" stroke="{SLATE}" stroke-width="3"/>
  <line x1="88.8" y1="70.8" x2="99" y2="81" stroke="{GREEN}" stroke-width="5" stroke-linecap="round"/>
  <line x1="88.8" y1="70.8" x2="99" y2="81" stroke="{SLATE}" stroke-width="2" stroke-linecap="round"/>
  <circle cx="80" cy="62" r="4.2" fill="{TERRA}"/>
"""


def _chain_row(x: int, y: int, ink: str, green: str, terra: str) -> str:
    """claim -> passage -> source, with a dissent node: the method in one line of glyphs."""
    labels = ["claim", "verbatim passage", "source"]
    parts = []
    xs = [x, x + 190, x + 430]
    for i, (cx, label) in enumerate(zip(xs, labels, strict=True)):
        parts.append(f'<circle cx="{cx}" cy="{y}" r="7" fill="{green}"/>')
        parts.append(
            f'<text x="{cx + 16}" y="{y + 5}" font-family="{SANS}" font-size="15" fill="{ink}" '
            f'letter-spacing="0.4">{label}</text>'
        )
        if i < 2:
            start = cx + 16 + len(label) * 8 + 12
            parts.append(
                f'<line x1="{start}" y1="{y}" x2="{xs[i + 1] - 14}" y2="{y}" stroke="{green}" '
                f'stroke-width="2" stroke-linecap="round"/>'
            )
    dx = xs[2] + 110
    parts.append(
        f'<circle cx="{dx}" cy="{y}" r="7" fill="none" stroke="{terra}" stroke-width="2"/>'
        f'<circle cx="{dx}" cy="{y}" r="3" fill="{terra}"/>'
        f'<text x="{dx + 16}" y="{y + 5}" font-family="{SANS}" font-size="15" fill="{ink}" '
        f'letter-spacing="0.4">dissent kept</text>'
    )
    return "".join(parts)


def banner(theme: str, tagline: str, width: int = 1280, height: int = 300) -> str:
    dark = theme == "dark"
    bg = NIGHT if dark else IVORY
    ink = IVORY if dark else SLATE
    sub = "#AEB8BE" if dark else "#4A5660"
    green = GREEN_LIGHT if dark else GREEN
    terra = TERRA_MID
    rule = "#26323A" if dark else LICHEN
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}"
  role="img" aria-label="Diotima. {escape(tagline)}">
  <title>Diotima. {escape(tagline)}</title>
  <rect width="{width}" height="{height}" rx="18" fill="{bg}"/>
  <rect x="1" y="1" width="{width - 2}" height="{height - 2}" rx="17" fill="none" stroke="{rule}" stroke-width="2"/>
  <g transform="translate(64 54) scale(1.5)">{MARK}</g>
  <text x="300" y="132" font-family="{SERIF}" font-size="78" fill="{ink}" letter-spacing="14">DIOTIMA</text>
  <text x="302" y="178" font-family="{SERIF}" font-style="italic" font-size="26" fill="{sub}">{escape(tagline)}</text>
  <line x1="302" y1="208" x2="{width - 64}" y2="208" stroke="{rule}" stroke-width="1.5"/>
  {_chain_row(310, 246, sub, green, terra)}
</svg>
"""


def social_preview(title: str, subtitle: str) -> str:
    """1280x640 card for the GitHub social preview (rendered to PNG separately)."""
    w, h = 1280, 640
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">
  <rect width="{w}" height="{h}" fill="{IVORY}"/>
  <rect x="24" y="24" width="{w - 48}" height="{h - 48}" rx="28" fill="none" stroke="{LICHEN}" stroke-width="3"/>
  <g transform="translate(80 180) scale(2.2)">{MARK}</g>
  <text x="430" y="268" font-family="{SERIF}" font-size="100" fill="{SLATE}" letter-spacing="18">DIOTIMA</text>
  <text x="434" y="332" font-family="{SERIF}" font-style="italic" font-size="31" fill="#4A5660">{escape(title)}</text>
  <text x="434" y="386" font-family="{SANS}" font-size="24" fill="#4A5660">{escape(subtitle)}</text>
  <g transform="translate(-74 100)">{_chain_row(510, 380, "#4A5660", GREEN, TERRA)}</g>
</svg>
"""


def main() -> None:
    copy = json.loads(COPY.read_text(encoding="utf-8")) if COPY.exists() else {}
    tagline = copy.get("tagline", "Every claim tied to a passage that code has found in the source")
    social = copy.get("social_preview", {})
    alt = copy.get("verdict_glyph_alt_text", {})

    (ASSETS / "glyphs").mkdir(parents=True, exist_ok=True)
    for name, (body, title) in GLYPHS.items():
        (ASSETS / "glyphs" / f"{name}.svg").write_text(_svg(body, alt.get(name, title)), encoding="utf-8")
    for theme in ("light", "dark"):
        (ASSETS / f"banner-{theme}.svg").write_text(banner(theme, tagline), encoding="utf-8")
    (ASSETS / "social-preview.svg").write_text(
        social_preview(
            social.get("title", "Auditable evidence synthesis"),
            social.get("subtitle", "A plugin for Claude Code and Codex"),
        ),
        encoding="utf-8",
    )
    print("brand assets written to", ASSETS.relative_to(ROOT))


if __name__ == "__main__":
    main()
