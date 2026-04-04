#!/usr/bin/env python3
"""
embed_svgs.py — inline SVG files into Marp markdown slides.

Replaces <img src="filename.svg"> tags with the SVG content embedded
directly. All element IDs are namespaced with the SVG filename stem to
prevent collisions when multiple diagrams appear in the same document.

Blank lines are stripped from the embedded SVG because CommonMark HTML
blocks (type 6) terminate at the first blank line — any blank line
inside an SVG causes Marp's parser to exit the HTML block and silently
drop <defs>, breaking all gradient/marker/filter references.

Usage:
    python3 embed_svgs.py              # processes slides.md, slides_40.md, lightning.md
    python3 embed_svgs.py slides.md    # process specific files
"""
import re
import sys
from pathlib import Path

SVG_DIR = Path(__file__).parent

DEFAULT_MD_FILES = ['slides.md', 'slides_40.md', 'lightning.md']

# Match <img src="local-file.svg" ...> — local references only
IMG_PATTERN = re.compile(r'<img\s+src="([\w]+\.svg)"([^>]*)>')


def strip_blank_lines(svg_text: str) -> str:
    """Remove blank lines from SVG content.

    CommonMark HTML blocks (type 6) terminate at the first blank line, so any
    blank line inside an embedded SVG causes the Marp markdown parser to exit
    the HTML block and treat subsequent lines as Markdown.  SVG does not need
    blank lines — they are purely cosmetic in the source files.
    """
    return '\n'.join(line for line in svg_text.splitlines() if line.strip())


def namespace_svg(svg_text: str, prefix: str) -> str:
    """Prefix every id= and every reference to those IDs with *prefix*."""
    ids = re.findall(r'\bid="([^"]+)"', svg_text)
    for id_val in ids:
        new_id = f"{prefix}-{id_val}"
        svg_text = re.sub(rf'\bid="{re.escape(id_val)}"', f'id="{new_id}"', svg_text)
        svg_text = re.sub(rf'url\(#{re.escape(id_val)}\)', f'url(#{new_id})', svg_text)
        svg_text = re.sub(
            rf'((?:xlink:)?href)="#{re.escape(id_val)}"',
            rf'\1="#{new_id}"', svg_text,
        )
    return svg_text


def embed_svgs(md_path: Path) -> None:
    text = md_path.read_text()

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
        svg = strip_blank_lines(svg_path.read_text())
        svg = namespace_svg(svg, prefix)

        def patch_svg_tag(tm: re.Match) -> str:
            attrs = tm.group(1)
            # Drop the SVG's own width/height/style — we control those
            attrs = re.sub(r'\s+width="[^"]*"', '', attrs)
            attrs = re.sub(r'\s+height="[^"]*"', '', attrs)
            attrs = re.sub(r'\s+style="[^"]*"', '', attrs)
            if width:
                attrs += f' width="{width}"'
            if style:
                attrs += f' style="{style}"'
            return f'<svg{attrs}>'

        svg = re.sub(r'<svg([^>]*)>', patch_svg_tag, svg, count=1)
        print(f"  {svg_file}  prefix={prefix}  width={width}")
        return svg

    new_text = IMG_PATTERN.sub(replace_img, text)
    md_path.write_text(new_text)


def main() -> None:
    targets = sys.argv[1:] or DEFAULT_MD_FILES
    for md_file in targets:
        md_path = SVG_DIR / md_file
        print(f"\n{md_path.name}:")
        embed_svgs(md_path)
    print("\nDone.")


if __name__ == '__main__':
    main()
