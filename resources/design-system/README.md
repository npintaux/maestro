# Maestro Design System

Corporate-default design tokens, component whitelist, and accessibility thresholds. These are the
**frozen authority** that [`scripts/validate_ui_spec.py`](../../scripts/validate_ui_spec.py) checks a
subsystem's `ui-spec.json` against. The whole point is that off-brand or inaccessible UI is caught by
a gate that *bites* — not by trusting an agent (including a Stitch MCP call).

A project overrides these defaults by pointing the validator at a project-local directory:

```bash
python3 scripts/validate_ui_spec.py path/to/ui-spec.json \
  --design-system path/to/project/design-system \
  --prd docs/PRD.md
```

## Files (bespoke Maestro schema)

### `tokens.json` — `maestro/design-tokens@1`
Categories map a token name to a value. `color` values must be `#RGB`/`#RRGGBB` (used for contrast).

```json
{ "color": { "on-surface": "#111827" }, "font": { "family-sans": "Inter" }, "font-size": {...},
  "space": {...}, "radius": {...} }
```

### `components.json` — `maestro/component-whitelist@1`
```json
{ "components": ["AppBar", "Button", "Text", "..."] }
```

### `a11y-rules.json` — `maestro/a11y-rules@1`
```json
{ "contrast": { "normal-text": 4.5, "large-text": 3.0 } }
```

## The `ui-spec.json` contract the validator checks

A `ui-spec.json` is authored per subsystem by the [`ux-design`](../../skills/ux-design/SKILL.md)
persona and frozen; the validator backs the `gate-ui` stage in `gate_controller.py`. Every
color/font/size/space is a **token reference** `{category.name}`; raw literals are rejected as magic
values.

```json
{
  "schema": "maestro/ui-spec@1",
  "initial_screen": "cart",
  "screens": [
    {
      "id": "cart",
      "user_stories": ["US-1"],
      "components": ["AppBar", "List", "Button"],
      "text_styles": [
        { "color": "{color.on-surface}", "background": "{color.surface}", "size": "normal" }
      ],
      "transitions": [ { "on": "checkout_cta", "to": "payment" } ]
    }
  ]
}
```

The validator denies a spec that: references a raw color/unknown token (magic value), uses a
component outside the whitelist, has a text style below the WCAG contrast threshold, names an
undefined `initial_screen`, targets/leaves an unreachable screen, duplicates a screen id or
transition trigger, or maps a screen to a `US-N` not defined in `docs/PRD.md` (when `--prd` is
given). `size` is `normal` (AA 4.5:1) or `large` (3.0:1).

## Importing a Claude Design export (advisory)

[`scripts/import_claude_design.py`](../../scripts/import_claude_design.py) is an **advisory** helper —
not a gate. It unpacks a Claude Design export `.zip`, best-effort extracts the colors, fonts, and
component names it finds in any HTML/CSS/JSX/TSX/JS/JSON/SVG entries, and maps them against this
design system:

```bash
python3 scripts/import_claude_design.py path/to/claude-design-export.zip \
  --design-system resources/design-system \
  --emit-draft src/modules/<subsystem>/ui-spec.json
```

The JSON report separates on-brand values (`mapped_colors`/`mapped_fonts`/`whitelisted_components`)
from off-brand **magic values** (`unmapped_colors`/`unmapped_fonts`/`non_whitelisted_components`) the
`ux-design` persona must conform to tokens (or deliberately add). The optional `--emit-draft` writes a
**non-authoritative** `ui-spec.json` scaffold (`_draft_notes` records the decisions to resolve); it is
intentionally incomplete and will **fail** the validator until finished. The gate, not the import,
is the authority.
