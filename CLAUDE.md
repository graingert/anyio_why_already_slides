# Claude Instructions

## Branch naming

The default branch is named `default` (not `main` or `master`). The CI
release workflow triggers on pushes to `default`.

## Dependencies

```
pip install -r requirements.txt
```

This installs `beautifulsoup4` and `lxml`, needed by `embed_svgs.py`.

## SVG embedding

Source SVGs live as standalone `.svg` files. They are inlined into the
slide decks by `embed_svgs.py`, which namespaces IDs, strips HTML
comments (Marp treats them as speaker notes), and removes blank lines
(CommonMark HTML blocks terminate at the first blank line).

```
python3 embed_svgs.py
```

Run this after editing any `.svg` file, then commit the updated `.md`
files alongside the SVG changes. CI checks that embedded SVGs are in
sync on every PR.

## Regenerating the PDFs

Run each command separately (do not chain with `&&` or `;`):

```
npx @marp-team/marp-cli@latest slides.md --pdf --html
```

```
npx @marp-team/marp-cli@latest slides_40.md --pdf --html
```

```
npx @marp-team/marp-cli@latest lightning.md --pdf --html
```

```
npx @marp-team/marp-cli@latest slides_part1.md --pdf --html
```

```
npx @marp-team/marp-cli@latest slides_part2.md --pdf --html
```

```
npx @marp-team/marp-cli@latest slides_part3.md --pdf --html
```

The `--html` flag enables HTML tag parsing in the markdown (for `<img>`, `<style scoped>`, etc.) — it does not produce an HTML output file. Only a PDF is generated.
