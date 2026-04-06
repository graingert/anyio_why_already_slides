#!/usr/bin/env python3
"""
embed_svgs.py — inline SVG files into Marp markdown slides.

Replaces <img src="filename.svg"> tags with the SVG content embedded
directly. All element IDs are namespaced with the SVG filename stem to
prevent collisions when multiple diagrams appear in the same document.

HTML comments are removed because Marp treats them as speaker notes.
The lxml XML serialiser produces compact output with no blank lines,
which is required because CommonMark HTML blocks (type 6) terminate at
the first blank line.

Usage:
    python3 embed_svgs.py              # processes all slide decks
    python3 embed_svgs.py slides.md    # process specific files
"""
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup, Comment

SVG_DIR = Path(__file__).parent

DEFAULT_MD_FILES = [
    'slides.md',
    'slides_40.md',
    'lightning.md',
    'slides_part1.md',
    'slides_part2.md',
    'slides_part3.md',
]

# Match <img src="local-file.svg" ...> — local references only
IMG_PATTERN = re.compile(r'<img\s+src="([\w]+\.svg)"([^>]*)>')


def _namespace_svg(soup: BeautifulSoup, prefix: str) -> None:
    """Prefix every ``id`` and every reference to those IDs with *prefix*."""
    # Build old → new mapping
    id_map: dict[str, str] = {}
    for tag in soup.find_all(id=True):
        old = tag['id']
        new = f"{prefix}-{old}"
        id_map[old] = new
        tag['id'] = new

    if not id_map:
        return

    # Update url(#old) and href="#old" references in all attributes
    url_re = re.compile(
        r'url\(#(' + '|'.join(re.escape(k) for k in id_map) + r')\)',
    )
    for tag in soup.find_all(True):
        for attr, val in list(tag.attrs.items()):
            if not isinstance(val, str):
                continue
            if 'url(#' in val:
                tag[attr] = url_re.sub(
                    lambda m: f'url(#{id_map[m.group(1)]})', val,
                )
            elif val.startswith('#') and val[1:] in id_map:
                tag[attr] = f'#{id_map[val[1:]]}'


def _prepare_svg(svg_path: Path, *, width: str | None, style: str | None) -> str:
    """Parse, clean, namespace, and serialise an SVG for inline embedding."""
    soup = BeautifulSoup(svg_path.read_text(), 'xml')

    # Remove HTML comments (Marp treats them as speaker notes)
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    # Namespace IDs to avoid collisions between diagrams
    prefix = svg_path.stem.replace('_', '-')
    _namespace_svg(soup, prefix)

    # Patch the <svg> root: drop its own width/height/style, apply ours
    svg_tag = soup.find('svg')
    for attr in ('width', 'height', 'style'):
        del svg_tag[attr]
    if width:
        svg_tag['width'] = width
    if style:
        svg_tag['style'] = style

    # Serialise — strip blank lines left behind by comment removal,
    # since CommonMark HTML blocks terminate at the first blank line.
    return '\n'.join(
        line for line in str(svg_tag).splitlines() if line.strip()
    )


def _build_prefix_map() -> dict[str, Path]:
    """Map namespace prefix → SVG source path for all local SVGs."""
    return {
        p.stem.replace('_', '-'): p
        for p in SVG_DIR.glob('*.svg')
    }


def embed_svgs(md_path: Path) -> None:
    text = md_path.read_text()
    prefix_map = _build_prefix_map()

    # Pass 1: replace <img src="x.svg" ...> tags (first-time embedding)
    def replace_img(m: re.Match) -> str:
        svg_file = m.group(1)
        rest_attrs = m.group(2)
        svg_path = SVG_DIR / svg_file

        if not svg_path.exists():
            print(f"  WARNING: {svg_path} not found, leaving <img> in place")
            return m.group(0)

        width_m = re.search(r'width="([^"]+)"', rest_attrs)
        style_m = re.search(r'style="([^"]+)"', rest_attrs)
        width = width_m.group(1) if width_m else None
        style = style_m.group(1) if style_m else None

        prefix = svg_path.stem.replace('_', '-')
        svg = _prepare_svg(svg_path, width=width, style=style)
        print(f"  {svg_file}  prefix={prefix}  width={width}")
        return svg

    text = IMG_PATTERN.sub(replace_img, text)

    # Pass 2: replace already-embedded <svg>...</svg> blocks
    # Can't parse the whole file as HTML (it's markdown), so find SVG
    # blocks positionally and parse each one with BeautifulSoup.
    parts: list[str] = []
    pos = 0
    while True:
        start = text.find('<svg', pos)
        if start == -1:
            parts.append(text[pos:])
            break
        end = text.find('</svg>', start)
        if end == -1:
            parts.append(text[pos:])
            break
        end += len('</svg>')

        svg_block = text[start:end]
        soup = BeautifulSoup(svg_block, 'xml')
        svg_tag = soup.find('svg')

        # Identify which source SVG this came from via namespaced IDs
        replacement = None
        if svg_tag:
            for prefix, svg_path in prefix_map.items():
                if svg_tag.find(id=lambda v: v and v.startswith(f'{prefix}-')):
                    width = svg_tag.get('width')
                    style = svg_tag.get('style')
                    replacement = _prepare_svg(svg_path, width=width, style=style)
                    print(f"  {svg_path.name}  prefix={prefix}  width={width}  (update)")
                    break

        parts.append(text[pos:start])
        parts.append(replacement if replacement is not None else svg_block)
        pos = end

    text = ''.join(parts)

    md_path.write_text(text)


def main() -> None:
    targets = sys.argv[1:] or DEFAULT_MD_FILES
    for md_file in targets:
        md_path = SVG_DIR / md_file
        print(f"\n{md_path.name}:")
        embed_svgs(md_path)
    print("\nDone.")


if __name__ == '__main__':
    main()
