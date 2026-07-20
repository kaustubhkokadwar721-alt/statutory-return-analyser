# Web Style Guide

Status: Active

Applies to: `web_app/`

Last reviewed: 2026-07-16

This guide is the design contract for the Statutory Return Extractor. It keeps the
interface consistent as new document types, validations, and review workflows are
added. It describes the system that exists today; it is not a second theme or a
separate component library.

## 1. What A Web Style Guide Contains

A useful web style guide has five layers:

1. **Principles** explain the product's character and the decisions that should stay
   true even when the interface expands.
2. **Foundations** define reusable visual values: colour, type, spacing, shape,
   motion, icons, and layout.
3. **Components** define reusable interface parts and all their states.
4. **Patterns** explain how components work together to complete a user task.
5. **Standards** cover content, accessibility, privacy, testing, and contribution.

This structure follows mature public systems that separate styles, components, and
task patterns, and that document both code and usage guidance.

## 2. Product Direction

### Design idea

**Registry: Indian statutory paper, modernised.**

The interface should feel like a careful audit working paper: calm, exact, familiar,
and trustworthy. Warm paper, blue-black ink, register green, and seal maroon give it
identity. Colour is functional before it is decorative.

### Audience

- Auditors, accountants, tax teams, and finance staff.
- Users may be tired, under deadline, and handling sensitive client records.
- Users should not need to understand parsing, WebAssembly, OCR, or schemas.

### Product principles

1. **Accuracy before speed claims.** Never imply that extraction is correct when a
   field is missing, conflicting, or weak.
2. **Exceptions first.** Review and Error records must be easier to find than clean
   records.
3. **Private by design.** Privacy is visible, specific, and true. Do not use vague
   security theatre.
4. **Quiet working surface.** Prefer dense, orderly information over marketing
   layouts, oversized type, decorative cards, or novelty animation.
5. **Plain language.** Use task words such as `Run and Report`, `Review`, and
   `Download Excel`. Technical detail belongs in diagnostics.
6. **One action, one result.** A primary action should have a clear outcome and a
   visible state while it is running.
7. **Expand by reuse.** A new return type should reuse the existing upload, status,
   review, table, and download patterns.

## 3. Canonical Resources

These files own the web interface:

| Resource | Responsibility |
| --- | --- |
| `web_app/themes/prime.css` | Design tokens, layout, component appearance, responsive rules |
| `web_app/index.html` | Semantic structure, labels, icon sprite, accessibility attributes |
| `web_app/app.js` | Component states, dynamic content, status messages, result rendering |
| `web_app/fonts/` | Offline Spectral and Hanken Grotesk font files |
| `web_app/README.md` | Runtime, packaging, and deployment instructions |
| `docs/web-style-guide.md` | Design intent, usage rules, and UI acceptance checks |

Rules:

- Do not create a second stylesheet for a feature. Extend `prime.css` in the section
  that owns the component.
- Do not add an icon package. Reuse or add a symbol to the SVG sprite in `index.html`.
- Do not fetch fonts, icons, scripts, analytics, or images from a third party.
- Do not place document data in logs, browser storage, service-worker caches, or URLs.
- Generated runtime and OCR vendor files are not design resources.

## 4. Foundations

### Colour

Use semantic tokens, not raw colours inside components.

| Token group | Purpose |
| --- | --- |
| `--bg`, `--bg-deep` | Warm page background |
| `--panel`, `--panel-2`, `--sink` | Main surface, hover/zebra surface, inset surface |
| `--ink`, `--ink-soft`, `--ink-faint` | Primary, secondary, and supporting text |
| `--green`, `--green-2` | Brand, successful states, privacy, focus |
| `--seal`, `--seal-2` | Primary action and active navigation |
| `--ok`, `--amber`, `--red` | OK, Review, and Error semantics |
| `--rule`, `--rule-soft` | Structural and subtle borders |

Status meaning is fixed:

| State | Colour | Meaning |
| --- | --- | --- |
| OK | Green | Required evidence is present and checks passed |
| Review | Amber | A person must inspect weak, missing, or conflicting evidence |
| Error | Red | Processing or a required validation failed |
| Busy | Amber pulse | Work is active; no final result exists yet |

Do not use colour alone. Pair every state colour with text, an icon, a shape, or a
position. Do not reuse green for an unchecked or uncertain state.

Each document type owns a stable token pair (`--t-*` and `--s-*`). The pair may mark
the document tile, file tag, and table glyph. It must not override validation status.

### Typography

| Role | Typeface | Current use |
| --- | --- | --- |
| Display | Spectral | Product name, drop-zone heading, KPI values, download title |
| Interface and data | Hanken Grotesk | Controls, labels, tables, diagnostics, body text |
| Technical log | System monospace | Boot and processing diagnostics only |

Current scale:

- Product title: 19px, Spectral semibold.
- Drop-zone heading: 26px, Spectral semibold.
- KPI value: 34px, Spectral semibold with tabular numbers.
- Primary action: 14.5px, Hanken Grotesk semibold.
- Body: 14px.
- Table: 13px; table header: 10.5px uppercase.
- Supporting labels: 10-12.5px.

Rules:

- Use display type only for true headings and key figures.
- Use tabular numerals for amounts, counts, references, and confidence scores.
- Keep letter spacing at `0` for normal text. Modest positive spacing is reserved for
  short uppercase labels.
- Do not scale font size with viewport width.
- Never reduce important text to make a container fit; let the layout wrap instead.

### Spacing and density

Use a 4px base rhythm. Prefer values already present in the stylesheet:

`4, 6, 8, 10, 12, 16, 20, 24, 28, 32`

The app is a working surface, so spacing should aid scanning rather than make every
section feel like a separate card. New page sections should be unframed. Use cards
only for repeated items, a modal, or a genuinely bounded tool.

### Shape, borders, and shadow

- Main radius: `--radius` (6px).
- Compact radius: `--radius-sm` (4px).
- Pills may be fully rounded because they represent compact states or counts.
- Use `--rule` and `--rule-soft` for structure.
- Use `--shadow` only for the main working surface or elevated interaction.
- Use `--shadow-sm` for restrained separation.
- Do not add decorative floating sections, nested cards, or large soft shadows.

### Icons

- Icons are outline SVG symbols in the sprite at the top of `index.html`.
- Document icons communicate document identity; UI icons communicate actions.
- Icon-only controls need an accessible name and a visible tooltip when unfamiliar.
- Decorative SVGs use `aria-hidden="true"`.
- Do not draw a second version of an existing symbol.

### Motion

- Motion should explain state: hover lift, active press, progress pulse, or result
  reveal.
- Keep transitions between 150ms and 400ms and use `--ease`.
- Never animate table data or monetary values.
- Respect `prefers-reduced-motion`; the existing rule disables animation and
  transition globally.

## 5. Layout and Responsiveness

The interface is one working surface, not a landing page.

- `.wrap` is the shared content boundary with `--maxw: 1800px` and responsive side
  padding.
- The top bar contains product identity, engine status, and the privacy assurance.
- The main card owns the Drop and Results tabs.
- Tables may scroll horizontally; the page itself must not.
- Stable controls and fixed-format elements must not resize when labels or states
  change.

Current breakpoints:

| Breakpoint | Behaviour |
| --- | --- |
| Above 1020px | Full-height working surface and contained result scrolling |
| 1020px and below | Natural page flow; shorter drop zone |
| 780px and below | Header wraps; privacy assurance moves to its own row |
| 560px and below | Controls stack; filters wrap; action fills available width |
| Desktop height 820px and below | Vertical chrome becomes more compact |

Do not add a breakpoint for one label. Fix the component's intrinsic sizing first.

## 6. Component Inventory

Each component needs a purpose, all relevant states, keyboard behaviour, responsive
behaviour, and a single owner.

| Component | Selectors / owner | Required states and rules |
| --- | --- | --- |
| Product header | `.topbar`, `.brand`, `.title` | Product identity remains the strongest header element |
| Engine status | `.statusbar`, `.dot`; `setStatus()` | Default, Busy, OK, Error; message truncates safely in the header |
| Privacy assurance | `.pledge-mini` | Visible but subordinate to product identity; wording must remain factual |
| Workspace tabs | `.tabs`, `.tab`; `selectTab()` | Selected, unselected, focus, hidden Results state; correct ARIA tab wiring |
| Boot diagnostics | `.diag`, `.diag-step` | Waiting, Busy, OK, Error, reason; never show a false OK |
| Document-type tile | `.type`, `.tplate` | Stable size, identity colour, label, short description; informational, not a control |
| PDF drop zone | `.drop`; picker events | Default, hover, drag-over, focus, files-selected compact state |
| File list and tags | `.files`, `.fchip`, `.ftag` | Pending, identified, Review, Error, removable, duplicate-safe filename display |
| Primary action | `.btn`, `#run` | Disabled, default, hover, active, focus, processing; one primary action per view |
| OCR control | `.ocr-toggle` | Checked/unchecked and explanatory tooltip; no claim that structured forms are safe when they are not |
| Processing log | `.log` | Hidden until useful; technical detail only; no extracted client values |
| Download row | `.results`, `.dl` | Workbook name, record count, primary download action |
| KPI strip | `.kpis`, `.kpi` | Neutral total, OK, Review, Error, clickable filter with keyboard focus |
| Data table | `.tbl`, `.tbl-wrap` | Sticky header where needed, numeric alignment, hover, horizontal scroll |
| Kind badge | `.kcell` | Return, Challan, Payment, Arrears; never substitute for validation status |
| Status pill | `.pill` | OK, Review, Error with text and colour |
| Record filters | `.record-filter`, `.flagtoggle` | Labelled select/checkbox, keyboard focus, mobile wrapping |
| Review evidence | `.review-detail`, `.evidence-btn` | Summary, findings, evidence, profile, source pages; collapsed by default |
| Unreadable file | `.bad`, `#badFiles` | Type, filename, reason, next action; no silent omission |

### Component naming

Use short, domain-specific class names already established in the stylesheet. New
components should use an `sre-` prefix if their name is broad enough to collide with a
vendor or browser convention. Do not rename current classes merely to add the prefix.

## 7. Task Patterns

### Start and readiness

`Loading runtime -> Loading libraries -> Installing PDF engine -> Loading return engine -> Ready`

- Show the current stage.
- A failed stage stays failed and includes a reason below.
- `Ready` means the parser can accept files; it does not claim every document will
  parse successfully.

### Add documents

`Drop/select PDF -> show file -> allow removal -> enable Run and Report`

- Accept mixed supported document types.
- Preserve the original filename for evidence and export.
- A duplicate display name must not overwrite another file in memory.

### Run and report

`Run -> preflight -> optional local OCR -> classify -> extract -> validate -> review/workbook`

- Disable the action while work is active.
- Keep progress visible.
- Finish with a record count and workbook availability.
- A failed document must appear in Unreadable files or Review; it must not disappear.

### Review exceptions

`Overview -> flagged KPI/filter -> Records -> Review Evidence`

- Sort Error and Review before OK.
- Keep the reason near the affected record.
- Evidence must identify the field, raw/extracted value, page, method, anchor, and
  profile where available.
- Do not present deterministic confidence as a probability.

### OCR

- Native text parsing runs first.
- OCR assets load only when an image-only PDF requires them.
- OCR-derived records are reviewed unless their form-specific acceptance rules prove
  they are safe.
- Scanned GSTR and Shipping Bill layouts remain review-only until structured OCR can
  preserve their table evidence.

## 8. Content Style

### Voice

Calm, direct, and specific. Write for a finance professional, not a developer.

- Use sentence case for messages and title case only where the interface already uses
  a compact label convention.
- Begin commands with a verb: `Run and Report`, `Download Excel`, `Open`.
- Name the document or field when giving an error.
- Say what happened and what the user can do next.
- Avoid `parse`, `schema`, `runtime`, `sidecar`, `probability`, and `pipeline` in normal
  user-facing copy unless no plain alternative is accurate.

Preferred status words are fixed: `OK`, `Review`, `Error`, `Matched`, and `Mismatch`.
Do not create synonyms such as Pass, Warning, Failed, or Success for the same states.

Examples:

| Avoid | Use |
| --- | --- |
| Parse to CSV | Run and Report |
| Processing failed | Processing stopped. See details below. |
| Invalid input | This PDF could not be opened. Check that it is not encrypted or damaged. |
| Low confidence | Review: the challan number could not be read clearly. |

### Numbers and statutory data

- Use Indian digit grouping for displayed money.
- Keep full precision in extracted and exported data; display rounding must not alter
  the workbook value.
- Use `-` for not applicable in display tables, not for a missing required field.
- Preserve source references and IDs as text so leading zeroes remain intact.
- Use explicit financial-year labels such as `2025-26`.

## 9. Accessibility Standard

Target WCAG 2.2 AA for the web interface.

- Every function must work with keyboard only.
- Keep a visible `:focus-visible` state on every interactive element.
- Native controls are preferred to custom controls.
- Labels visible to users should match accessible names.
- Do not use colour alone for status or document meaning.
- Maintain sufficient text and control contrast.
- Use semantic headings, tables, lists, buttons, labels, and details/summary elements.
- Dynamic counts and important progress use appropriate live regions without
  announcing every log line.
- Touch targets should be at least 24 by 24 CSS pixels; primary actions should be
  comfortably larger.
- Content must remain usable at 200% browser zoom and at 320 CSS pixels wide.
- Reduced-motion preference must remove non-essential animation.

Automated checks help but do not replace keyboard, zoom, and screen-reader spot checks.

## 10. Privacy and Trust

The privacy promise is part of the product, not decorative copy.

Allowed claims:

- `Private by design`
- `Files stay on this device`
- `100% offline, nothing leaves this device` only after the complete local runtime is
  ready and processing makes no document-related network request.

Rules:

- PDFs, OCR text, evidence, workbooks, and filenames stay in browser memory.
- Service-worker caching is limited to application and runtime assets.
- Do not add telemetry, analytics, remote error reporting, cloud OCR, external AI, or
  document persistence without an explicit product and privacy decision.
- Diagnostics may name a source file when required for the user's review, but must not
  print extracted statutory IDs, names, amounts, or OCR text.
- Any future network-dependent feature must be visibly separate and off by default;
  it cannot inherit the current privacy claim.

## 11. Adding or Changing UI

Before adding a component:

1. Check whether an existing component or native HTML element solves the need.
2. Define the user task, not only the visual shape.
3. List default, hover, focus, disabled, busy, empty, success, review, and error states
   that apply.
4. Reuse semantic tokens and the existing icon sprite.
5. Define keyboard and mobile behaviour.
6. Check whether the component displays or stores client data.
7. Add it to the component inventory above if it will be reused.

Do not add an abstraction for one instance. Promote repeated markup to a renderer or
helper only when the duplication is real and the states are understood.

### Component documentation template

Use this small template for a new reusable component:

```text
Name:
Purpose:
Owner (HTML/CSS/JS):
Markup or renderer:
Tokens used:
States:
Keyboard behaviour:
Responsive behaviour:
Privacy considerations:
Acceptance checks:
```

## 12. Visual Acceptance Checks

Check these viewports after a UI change:

- 1920 x 970: wide desktop.
- 1366 x 768: common short laptop.
- 1024 x 768: compact desktop/tablet landscape.
- 390 x 844: mobile.

Check these states when relevant:

- Cold boot and each boot diagnostic stage.
- Ready with no files.
- One file, many files, long filename, and duplicate filename.
- Processing and local OCR.
- Successful workbook with records.
- Review and Error records with evidence.
- Unreadable/encrypted/image-only PDF.
- Browser zoom at 200%.
- Keyboard-only flow and visible focus.
- Reduced motion.
- No page-level horizontal overflow.
- No document-related network requests after the local runtime is ready.

For canvas or image-based additions, also verify non-blank pixels and framing. The
current application does not need decorative imagery; its real visual assets are the
document-state icons, data, evidence, and generated workbook.

## 13. External Research Basis

These public systems informed the structure of this guide:

- [GOV.UK Styles](https://design-system.service.gov.uk/styles/) separates layout,
  spacing, typography, colour, and images.
- [GOV.UK Components](https://design-system.service.gov.uk/components/) documents
  reusable UI parts with usage guidance and coded examples.
- [GOV.UK Patterns](https://design-system.service.gov.uk/patterns/) combines components
  into user-focused tasks.
- [USWDS Design Tokens](https://designsystem.digital.gov/design-tokens/) uses curated
  palettes for colour, spacing, typography, opacity, shadow, and related values.
- [W3C Designing for Web Accessibility](https://www.w3.org/WAI/tips/designing/) covers
  contrast, non-colour cues, identifiable controls, labels, feedback, grouping, and
  responsive layouts.
- [WCAG 2 Overview](https://www.w3.org/WAI/standards-guidelines/wcag/) defines the
  shared accessibility standard; this project targets WCAG 2.2 AA.

Review external guidance when the product adds a new control or interaction pattern,
but preserve the product's own statutory-working-paper character.
