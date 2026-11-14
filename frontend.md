# frontend.md

Design and layout rules for the app's frontend. Read `AGENTS.md` first, then
`plan.md`, then this file.

`AGENTS.md` and `plan.md` win over this file for scope, behavior, privacy and
wording rules. This file only decides how the app looks and how screens are laid
out.

## The one rule about changes

Design work changes how things look, never what they do.

- Allowed: Tailwind classes, CSS, spacing, colors, fonts, icons, the order and
  grouping of elements on a screen, splitting a crowded screen into steps.
- Not allowed: changing props, state, handlers, API calls, query keys, routes,
  generated types (`frontend/src/api/types.ts`), validation, test ids, or the
  data a screen shows. If a layout idea needs a behavior change, stop and ask.
- Every rule in `AGENTS.md` still applies to the visual layer, for example:
  First/Second Block never told apart by color alone, seats always shown as
  "seats as of <time>", professors show a star and a "See on Rate My
  Professors" link and no ratings, every schedule ends with
  "Confirm with BYU-Idaho Academic Advising.", every screen has loading, empty
  and error states.

## Visual direction

Calm and simple, like a clean habit tracker, with a little warmth from paper
tones, serif headlines and perforated "class slips".

1. **One job per screen.** Each screen answers one question. If it needs more,
   split it into steps or hide detail behind a link or a toggle.
2. **Show less at once.** A list shows at most 3 to 6 items before "Show more".
   A card shows a title, one line of detail and at most one secondary fact.
3. **Paper, white cards, one black button.** The page is warm off-white, content
   sits on white cards, and each screen has at most one filled black button.
4. **Color is small.** Color appears only as small squares that tag a subject or
   a rule. Never as large fills, gradients or colored backgrounds.
5. **Serif for headlines, sans for everything else.**
6. **The slip.** Schedule options and professor cards are slips: white cards
   with a dashed perforation line and two half-circle notches. This is the one
   decorative idea. Do not add others.

Reference mockups: the "Mix" page of the design canvas
(https://claude.ai/artifact/RnWRdnhdtucxMPBFcV9Yov, private to Gabriel until
shared). The mockups use sample data; real screens use API data only.

## Tokens

Put these in `tailwind.config` under `theme.extend` (and as CSS variables in
`src/index.css`). Components use the token names, never raw hex values.

### Color

| Token | Hex | Use |
| --- | --- | --- |
| `paper` | `#F6F5F1` | Page background |
| `surface` | `#FFFFFF` | Cards, inputs, nav |
| `ink` | `#1A1A1A` | Text, primary button, filled dots |
| `muted` | `#6E6A62` | Secondary text (4.9:1 on paper) |
| `line` | `#E6E2D9` | Card and input borders |
| `line-soft` | `#EFECE5` | Dividers inside cards |
| `field` | `#F1EFE9` | Tags, hover backgrounds |
| `halo` | `#EDEAE3` | Ring around the main prompt box |
| `perf` | `#D8D2C6` | Dashed perforation line |
| `warn` | `#8A5300` | "Check this before registering" text |
| `star` | `#B57E10` | Favorite star (filled) |

Tag squares (small only, 10 to 16 px, never behind text):

| Token | Hex | Default meaning |
| --- | --- | --- |
| `sq-sage` | `#9DBF8F` | CSE, or the first rule chip |
| `sq-clay` | `#E0A98A` | REL, or the second rule chip |
| `sq-sky` | `#9DB6D8` | MATH, or the third rule chip |
| `sq-sea` | `#8CC5C0` | WDD |
| `sq-butter` | `#D9C27A` | Fourth rule chip |
| `sq-lilac` | `#C7B3D9` | Fifth rule chip |
| `sq-stone` | `#C9C3B6` | Any other subject |

Subject colors come from a small map keyed by subject code, with `sq-stone` as
the fallback. Color is never the only signal: the code or label is always
written next to the square.

There is no red in the palette. Errors use `ink` text with an icon and a clear
sentence. Warnings use `warn`.

### Type

Two families, loaded with one `<link>` in `index.html` (no new npm
dependency):

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500&family=Geist:wght@400;500;600&display=swap" rel="stylesheet">
```

- `font-serif`: `'Newsreader', Georgia, serif`. Headlines, option names, the
  one-sentence "why", starter suggestions. Weight 400, letter-spacing -0.015em.
- `font-sans`: `'Geist', system-ui, -apple-system, sans-serif`. Everything
  else.

| Role | Family | Size / line height | Weight |
| --- | --- | --- | --- |
| Display (home only) | serif | 64 / 1.04, 40 on mobile | 400 |
| Page title | serif | 52 / 1.05, 36 on mobile | 400 |
| Card title (Option 1) | serif | 28 / 1 | 400 |
| Quote ("why this one") | serif | 23 / 1.4 | 400 |
| Body | sans | 16 / 1.45 | 400 |
| Lead under a title | sans | 17 / 1.5, `muted` | 400 |
| Item title (CSE 212) | sans | 16 | 600 |
| Small | sans | 14 | 400 to 600 |
| Note | sans | 13, `muted` | 400 |

- Headlines use `text-wrap: balance` and a max width (about 17ch) so no word
  sits alone on the last line.
- Sentence case everywhere. No ALL CAPS labels, no tracked-out eyebrows.
- Numbers that line up (times, credits) use `tabular-nums`.
- Body text lines stay under about 70 characters.

### Space, size and shape

- 4 px base. Common steps: 8, 12, 16, 24, 32, 40, 56, 72, 96.
- Content width 880 px. Grids of cards (professors) may use 1120 px. Side
  padding 24 px.
- Page top padding: 56 to 72 px on inner screens, about 104 px on home.
- Card padding 22 to 26 px.
- Radius: cards 16, nav bar 14, slips 14, buttons and inputs 9 to 10, chips
  and dots fully round, tags 7.
- Borders 1 px `line`. No drop shadows on regular cards. Only two effects
  exist: the slip outline and the prompt halo (see Components).
- Touch targets at least 44 x 44 px (chip remove buttons may be 30 px inside a
  44 px tall chip).

### Motion

- Hover: background or border color change, 150 ms. Nothing moves or scales.
- No entrance animations, no parallax, no auto-playing anything.
- Respect `prefers-reduced-motion` by turning transitions off.
- Streaming chat text and loading skeletons are the only "live" motion.

## Components

Build these once in `src/components/ui/` and reuse them. Names are
suggestions; keep any names a block already created.

**Nav bar.** Floating white bar, 14 radius, 1 px `line` border, 16 px from the
top. Left: black 28 px logo tile and the app name. Center: 2 to 4 text links
(14 px, current page in `ink` and 600 weight). Right: one muted fact, for
example "Winter 2027". On mobile, links move into a menu button.

**Buttons.**
- Primary: `ink` background, white text, 40 to 44 px tall, radius 9, 600
  weight. At most one per screen.
- Secondary: white, 1 px `line` border, `ink` text.
- Text button: no border, `muted` text, turns `ink` on hover. Used for "All
  schedules", "Draft email", "Show more".
- Icon-only buttons always have an `aria-label`.
- Button text is a verb and an object ("Build schedules", "Draft email"). No
  arrows appended to text.

**Prompt box.** The main input on home and the mentor finder. White, 16
radius, 1 px `line` border, plus a 6 px `halo` ring (`box-shadow: 0 0 0 6px`).
Border turns `ink` on focus. Bottom bar: a small secondary button on the left
("Add degree audit") and a 36 px black send button on the right. It always has
a visually hidden `<label>`.

**Starter suggestions.** A centered row of serif text buttons, each with a
16 px tag square. Clicking one fills the prompt; it does not submit. Four at
most.

**Rule chip.** Removable chip for each constraint: white, round, 1 px `line`
border, 10 px tag square, label, and an `x` button labeled "Remove rule:
<label>". Shows the `ConstraintSet` exactly as the API returns it.

**Slip.** A white card with notches and a perforation. Use it for schedule
options and professor cards only.

```css
.slip-wrap { filter: drop-shadow(0 0 .7px #9F978A) drop-shadow(0 3px 6px rgb(60 50 30 / .07)); }
.slip {
  --cut: 96px; /* distance from top to the perforation */
  background: #fff;
  border-radius: 14px;
  mask:
    radial-gradient(circle 11px at 0 var(--cut), transparent 97%, #000) left / 51% 100% no-repeat,
    radial-gradient(circle 11px at 100% var(--cut), transparent 97%, #000) right / 51% 100% no-repeat;
}
.slip-perf { border-top: 1.5px dashed #D8D2C6; margin: 0 18px; }
```

The outline filter must sit on a wrapper element (`.slip-wrap`), because a
mask on the same element would cut it off. The perforation line sits exactly
at `--cut`.

**Week dots.** Six 18 px circles for M, T, W, R, F, S with the letter under
each. Class day: filled `ink`. No class: 1.5 px `#D3CEC3` ring and `muted`
letter. Each dot has screen-reader text ("Thursday: class"). R is Thursday, as
in `AGENTS.md`.

**Class row.** One row per class inside a white list card, rows divided by
`line-soft`. Left: 14 px subject square. Middle: code (600) and title
(`muted`), then "Mon, Wed 10:15 to 11:45, STC 231". Right: the requirement it
fills, in `muted`. Extra lines only when they apply: a block tag, a warning or
"pending grade".

**Block tag.** Small `field` tag with a 12 x 10 pattern swatch and the label:
First Block uses diagonal hatching, Second Block uses dots, both drawn in
`ink`. The text label is always present. Online classes say "Online, no set
time" and have no swatch.

```css
.sw-first  { background-image: repeating-linear-gradient(135deg, #1A1A1A 0 1px, transparent 1px 4px); }
.sw-second { background-image: radial-gradient(#1A1A1A 1px, transparent 1.2px); background-size: 4px 4px; }
```

**Warning line.** `warn` text, 13 px, with a circle-alert icon:
"Check this before registering: needs MATH 110X". Never red, never styled as
an error.

**Star.** Filled `star` when favorited, outline `muted` when not. Always a
real `<button>` with `aria-label` "Star <name>" or "Unstar <name>".

**Badge.** Small black pill with white 12 px text, used once per list, for
example "Best fit" on the top-ranked schedule.

**Footnote.** 13 to 14 px `muted` line at the bottom of a screen for "Seats as
of 8:40 PM." and "Confirm with BYU-Idaho Academic Advising."

**Floating class slips (home only, optional).** Up to four small slips around
the home headline, tilted 4 to 6 degrees, `aria-hidden="true"`, hidden below
1100 px. They show real course codes from the student's remaining
requirements, or are left out. Never fake data.

**Icons.** Lucide icons from `lucide-react` through `components/ui/Icon.tsx`
(stroke 2.25, 14 to 20 px, `currentColor`), matching the Duo habit tracker. In
icon + sentence lists, show the icon on an `IconTile`: a rounded tile tinted at
12% of the icon's own color. No emoji. Decorative icons get `aria-hidden="true"`.

## Screens

Every screen uses the same frame: nav bar, one serif title, one short lead line
at most, the content, a footnote. Content is centered in the 880 px column
unless noted.

### Consent (AI-01)

```
[ nav ]
        Before you start                      <- page title
        one lead line
  [ white card: 4 short lines, icon + sentence each ]
  [ ] I understand what is stored and how to delete it
  [ Upload my audit ]  ( Use sample audit )    <- both disabled until checked
        footnote: never asks for a BYU-Idaho username or password
```

### Home: ask (AI-02 entry)

```
[ nav ]
          Plan a semester that fits your week          <- display serif, centered
          one lead line (muted)
     [ prompt box ............................ ]
     [ + Add degree audit                  (^) ]
          No audit yet? Try the sample audit
   [] No mornings  [] Fridays off  [] 12 to 15 credits  [] Favorite professors
```

A left-aligned variant on faint week-grid lines is also allowed; pick one and
use it everywhere.

### Schedules (AI-02, AI-03)

```
[ nav ]
  Winter 2027, from your audit                 <- note
  Three schedules fit                          <- title
  (o No class before 10:00 x) (o Fridays off x) (o 12 to 15 credits x)
  [ slip: Option 1 (Best fit)                  > ]
  [   14 credits, done by 3:00. One reason.     ]
  [ - - - - - - - - - - - - - - - - - - - - - - ]
  [   M T W R F S dots        * Starred prof    ]
  [ slip: Option 2 ...                          ]
  [ slip: Option 3 ...                          ]
  footnote: seats as of, confirm with advising
```

- 3 to 5 slips, one column. Chat history is not shown here; the prompt lives on
  home. If the chat panel must stay on this screen, put it in a drawer or below
  the slips, never beside them at full height.
- A relaxation hint replaces the slips with one card: the sentence from the API
  and one primary button, "Apply this change".

### One schedule (AI-03)

```
[ nav ]
  <- All schedules
  Option 1                                [ Calendar file ]
  14 credits, Monday to Thursday, done by 3:00
  "Every class counts toward your degree..."   <- serif quote, from the API's why
  [ list card: class rows ]
  footnote
```

- A List / Week toggle can switch the list for the weekly calendar. The
  calendar uses the same tokens: blocks are `ink` for full semester, hatched
  for First Block, dotted for Second Block, dashed outline for online, each
  with its text label.
- Backups and the professor link open inside the row (expand), not on the
  main list.

### Audit upload and confirm (AI-04)

- Upload: title, one lead line, one dashed drop area (white, `line` dashed
  border), one primary button. Nothing else.
- Confirm: title, one summary line (major, catalog year, audit date), then
  only the items that need the student: track question, flagged rows. Other
  requirement groups are collapsed rows with a status word and credits left.

### Professors and mentor finder (AI-05)

```
[ nav ]
          Find a professor to ask                     <- centered title
   (o Research) (o Letter) (o TA job) (o Internship)  <- one selected
     [ prompt: topic ........................ (^) ]
  [ slip ]  [ slip ]  [ slip ]                         <- 1120 px grid, 3 across
  footnote: where reasons come from
```

Each professor slip: initials in serif, name, department, star; perforation;
one reason sentence; "Draft email" and "See on Rate My Professors". The email
draft opens on its own screen or a side sheet, with Copy and no Send.

## States

- **Loading:** skeleton versions of the real layout (slips, rows) in `field`,
  no spinners in the middle of the page. The send button shows a small spinner
  while the request runs.
- **Empty:** the screen title, one sentence that says what to do, and one
  button. Example: "No professors match this topic yet. Try a broader topic."
- **Error:** one sentence that says what happened and what to try, plus a
  retry button and, for the audit, "Use sample audit". No red screens, no
  apologies.

## Responsive

- Desktop-first, works at 375 px (`AGENTS.md`).
- Below 768 px: display 40 px, titles 36 px, side padding 20 px, slips and
  cards one column, nav links in a menu, rule chips scroll sideways in one row.
- Below 1100 px: hide the floating class slips.
- Never scroll the page sideways. Wide content (the week calendar) scrolls
  inside its own box.

## Accessibility

- Text contrast at least 4.5:1. The tokens above pass on `paper` and
  `surface`; check any new color.
- Visible focus: `outline: 2px solid #1A1A1A; outline-offset: 3px`. Never
  remove it.
- Every input has a `<label>` (visually hidden is fine). Real `<button>` and
  `<a>` elements only.
- Status is never color alone: dots have screen-reader text, blocks have
  labels, warnings have words.

## Don't

- Don't add colored backgrounds, gradients, glows or glassmorphism.
- Don't put more than one primary button on a screen.
- Don't show the chat, the rules and the full schedules at full size on the
  same screen.
- Don't use ALL CAPS, emoji, or arrows typed into button text.
- Don't add new decorative ideas beyond the slip.
- Don't copy any other website's text, images or illustrations.
- Don't add a UI library or font package without asking (`AGENTS.md`: no new
  major dependency). Icons come from `lucide-react`, already installed.
- Don't change behavior while restyling (see the first section).
