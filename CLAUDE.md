# Claude Instructions

## Regenerating the PDFs

Run each command separately (do not chain with `&&` or `;`):

```
npx @marp-team/marp-cli@latest lightning.md --pdf --html
```

```
npx @marp-team/marp-cli@latest slides.md --pdf --html
```

```
npx @marp-team/marp-cli@latest slides_40.md --pdf --html
```

The `--html` flag enables HTML tag parsing in the markdown (for `<img>`, `<style scoped>`, etc.) — it does not produce an HTML output file. Only a PDF is generated.
