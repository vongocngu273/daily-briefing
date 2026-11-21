---
version: 1
slug: "templates-index-html-j2"
primary_target: "templates/index.html.j2"
related_targets: []
---

# Surface: daily briefing page (templates/index.html.j2 → docs/index.html)

Mode: Read. Build path: code-led. Single reader, any device, skim-or-deep depending on the day.
Job: weather → 3 takeaways → headlines → full details, stopping at any depth. Content volume varies 0–45 items; empty categories happen.
Constraints: no cards, no gradients, no glow; prefers-color-scheme light/dark; tabular-nums; <details> per item; no external JS; no shop branding.

## Direction contract

THESIS: Every morning is a fresh lottery-ticket stub (vé số kiến thiết): the date is the serial number, today's weather sits in the ticket's ruled boxes, the market table is the posted results board. Refuses the broadsheet-hairline digest and the app-card feed.

OWN-WORLD: Locked four-colour ticket palette: ticket stub colour (changes by weekday, like provincial tickets: pink, sky, lime, orange, violet, aqua, red), serial red #d0021b, ink navy #1b1f4a, paper white. Fine-line guilloche security pattern drawn as inline SVG on the stub only. Perforation edge (punched half-circles) separating stub from body. Heavy condensed numerals (Barlow Condensed 800) for serial, numbers and labels; Be Vietnam Pro for reading. Ruled boxes with 2px ink borders; dashed rules between items. Dark mode: navy ground, stub colour darkened, white paper becomes deep ink, serial red lightened.

STORY: The reader opens the link, sees today's ticket (date, update time, item count, weather with advice), knows in seconds whether to take a raincoat, reads 3 takeaways, then works down numbered items, opening details as the day allows. Returning later, the page lands on where they stopped.

FIRST VIEWPORT: Full-width stub ~55% of a 390x844 screen: small caps row (Bản tin sáng / Cập nhật 07:12), serial date 21·11 at ~108px in red with weekday tag, row (Thứ Bảy · 2026 / 38 tin), 3-column ruled weather box (label, temp range big red, sky + rain%), advice line. Perforation. Sticky quick-link strip (Thời tiết, Thị trường, 3 điều, Mở hết). Reading column starts with the first category heading underlined in serial red and numbered items (01, 02…) with severity emoji, title, summary, source caps line, details.

FORM: Grounded direction 3 of 7 (vé số kiến thiết); seed:96379a7bbf72a8c3. Raises: bookmark flag where you stopped (from cutting bench); continuous 01–N numbering with TOC by number (from brick instructions); locked 4-colour palette (from PC-98); AI summary vs original-source link set in visibly different type (from provenance ribbon). Signature interaction: the "cờ đọc dở" flag — the last opened item is remembered (localStorage, try/catch) and a "Đọc tiếp từ tin 07" link appears in the stub. Motion: one-time perforation tear-in of the stub on load, reduced-motion respected. No gambling vocabulary anywhere (no 'giải', 'trúng').

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
