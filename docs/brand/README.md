# Þing brand

The source for Þing's look: colours for light and dark mode, type, spacing, radii and the logo. `tokens.json` holds every value; the frontend builds its CSS variables from it.

Þing is Skjald's sister product. It keeps Skjald's brand (the Midnat tile, neutral surfaces, ink-and-snow buttons, Fjord links, status colours, fonts, spacing and radii) and changes two things: the mark is a ring of standing stones instead of the Ansuz rune, and the accent is Lyng (heather) instead of Rav (amber).

## Name

- Always write **Þing**, with the thorn, in the interface, the wordmark and documents. Never "Thing", "THING" or "Ting" in product copy.
- Where only ASCII works (the repository, packages, Docker images, commands, host names, HTTP headers), write `ting`, as in `ting-crm` and `/etc/ting`.
- Tagline: *Gather. Agree. Remember.* Set below the wordmark in IBM Plex Sans 500, `text-muted` on light and `frost` on dark.
- The wordmark is set live in Marcellus beside the mark; there is no wordmark file. Marcellus has Þ/þ and æ ø å.

## Personality

Calm, precise, trustworthy, quietly Nordic: carved stone and clean paper, not Viking clichés. No horns, axes, knotwork or fake runic fonts, and never the S-rune (ᛋ, Sowilo), which has extremist associations.

A *þing* was the Norse assembly: free people met in a ring of standing stones to settle disputes, make agreements and hear the law spoken. Þing is where everything about a customer is gathered, agreed and remembered.

## Logo

The mark is nine upright stones standing in a ring, seen at a low angle (smaller at the back, taller at the front), in Lyng on a Midnat tile.

| File | Use |
| --- | --- |
| `ting-mark.svg` | Default mark on light backgrounds; app icon |
| `ting-mark-framed.svg` | On dark backgrounds; a white inner frame makes the tile edge read |
| `ting-favicon.svg` | 16–32 px; seven heavier stones |

Minimum size 16 px; clear space of 25% of the tile width on every side. Do not recolour, rotate or outline the stones, and do not change their number (nine, or seven in the favicon). Never animate the ring, and never use it as a loading spinner, a "group" icon or decoration.

## Colour

- Neutral surfaces; colour is kept for the mark, one accent action and status.
- Light mode uses a neutral off-white background (`sne`, #F7F7F7) with white cards, never a pure white page or a blue or warm cast. Borders, not shadows.
- Primary buttons are "ink and snow" (`button-bg` / `button-text`), neutral so they are never mistaken for a status.
- Lyng (`accent`, #9A78B0 light, #B898C8 dark) fills the stones, highlights and at most **one** confirming action per view, such as "Confirm agreement". Text on it is `on-accent` (Midnat: 4.7:1 light, 7.4:1 dark). Never Lyng body text on light, and never on regular buttons or badges.
- Status colours (`ok`, `warning`, `critical`, `info`) always appear with their word, never colour alone. Every text pair meets 4.5:1 contrast.
- Rav (amber) is Skjald's and not part of Þing.

## Type

- **Marcellus**: display. Wordmark, page titles, section headings. One weight; hierarchy comes from size.
- **IBM Plex Sans**: all interface text (400, 500, 600).
- **IBM Plex Mono**: CVR numbers, domains, IP addresses, serial numbers, IDs and log excerpts.

All three are licensed under the SIL Open Font License and are bundled with Þing, so nothing loads from a font CDN at runtime.

## Layout

A 4 px spacing scale, borders instead of shadows, and radii of 8 px (buttons, inputs), 12 px (rows, small cards) and 20 px (cards, panels).

## Voice

- Plain English labels in sentence case, short and verb first: "New customer", "Log work", "Mark renewed".
- Every status shows a word, never colour alone.
- Answers a technician acts on are clear, never "maybe": the support a customer has is **Working hours**, **Any time** or **No support**, and always comes with the case number the time goes on.

## Components

The three starting components:

- **Button**: primary (ink and snow), accent (Lyng, one per view) and secondary (outlined).
- **StatusBadge**: OK, Warning, Critical and Info, showing the record's own word ("Active", "Ending", "Ended").
- **AgreementRow**: one agreement in a list: number, customer, type, status, dates and the next notice deadline. Þing's counterpart to Skjald's ReportRow.
