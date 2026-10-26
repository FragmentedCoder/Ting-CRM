# Þing brand

The source for Þing's look: colours for light and dark mode, type, spacing, radii and the logo. `tokens.json` holds every value; the frontend builds its CSS variables from it.

## Personality

Calm, precise, trustworthy, quietly Nordic: carved stone and clean paper, not Viking clichés. No horns, axes, knotwork or fake runic fonts.

## Logo

The mark is the Ansuz rune (ᚨ) — Odin's rune of speech, message and poetry, the skald's own — in amber (Rav) on a deep navy (Midnat) tile.

| File | Use |
| --- | --- |
| `ting-mark.svg` | Default mark on light backgrounds; app icon |
| `ting-mark-framed.svg` | On dark backgrounds; a white inner frame makes the tile edge read |
| `ting-favicon.svg` | 16–32 px; heavier rune stroke |

Minimum size 16 px; clear space of 25% of the tile width on every side. Do not recolour, rotate or outline the rune, and never replace it with the S-rune (ᛋ, Sowilo), which has extremist associations.

## Colour

- Neutral surfaces; colour is kept for the mark, one accent action and status.
- Light mode uses a neutral off-white background (`sne`, #F7F7F7), never pure white or a blue or warm cast.
- Primary buttons are "ink and snow" (`button-bg` / `button-text`), neutral so they are never mistaken for a status.
- Amber (`accent`) marks the rune, highlights and at most one sign-off action per view. Never amber body text on light.
- Status colours (`ok`, `warning`, `critical`, `info`) always appear with their word, never colour alone. Every text pair meets 4.5:1 contrast.

## Type

- **Marcellus** — display: wordmark, page and report titles, section headings. One weight; hierarchy comes from size.
- **IBM Plex Sans** — all interface and report body text (400, 500, 600).
- **IBM Plex Mono** — serial numbers, IP addresses, hashes and log excerpts.

All three are licensed under the SIL Open Font License and are bundled with Þing, so nothing loads from a font CDN at runtime.

## Layout

A 4 px spacing scale, borders instead of shadows, and radii of 8 px (buttons, inputs), 12 px (rows, small cards) and 20 px (cards, panels).
