# Diagram sources

Editable [Mermaid](https://mermaid.js.org/) source for the diagrams shown in the
project [`README.md`](../README.md). The README embeds **rendered PNGs** (so they
display everywhere, including viewers without Mermaid support); these `.mmd` files
are the source of truth — edit them here, then re-render.

| Source | Rendered image in README |
|--------|--------------------------|
| [`user-journey.mmd`](user-journey.mmd) | `demo/user-journey.png` — the end-to-end user journey (onboard → import → ask) |
| [`how-it-works.mmd`](how-it-works.mmd) | `demo/how-it-works.png` — the agent/tool architecture |

## Re-rendering after an edit

Using the Mermaid CLI ([`@mermaid-js/mermaid-cli`](https://github.com/mermaid-js/mermaid-cli)):

```bash
# one-off, no install:
npx -p @mermaid-js/mermaid-cli mmdc -i mermaid/user-journey.mmd -o demo/user-journey.png -s 3 -b transparent
npx -p @mermaid-js/mermaid-cli mmdc -i mermaid/how-it-works.mmd -o demo/how-it-works.png -s 3 -b transparent
```

`-s 3` renders at 3× scale for a crisp image; `-b transparent` keeps the
background clear. You can also paste a file's contents into
<https://mermaid.live> to preview or export.
