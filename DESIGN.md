---
name: Bản tin sáng
description: A personal Vietnamese morning briefing printed as a fresh lottery-ticket stub every day.
colors:
  bigman-black: "#000000"
  bigman-lime: "#C5FF2D"
  bigman-white: "#FFFFFF"
  muted-on-white: "rgba(0,0,0,.62)"
  muted-on-black: "rgba(255,255,255,.64)"
  engrave-lime: "rgba(197,255,45,.16)"
typography:
  display:
    fontFamily: "Barlow Condensed, Arial Narrow, sans-serif"
    fontSize: "clamp(72px, 24vw, 96px)"
    fontWeight: 800
    lineHeight: 0.95
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "Barlow Condensed, Arial Narrow, sans-serif"
    fontSize: "30px"
    fontWeight: 800
    lineHeight: 1.05
    letterSpacing: "0.02em"
  title:
    fontFamily: "Barlow Condensed, Arial Narrow, sans-serif"
    fontSize: "22px"
    fontWeight: 800
    lineHeight: 1.15
    letterSpacing: "0.04em"
  numeral:
    fontFamily: "Barlow Condensed, Arial Narrow, sans-serif"
    fontSize: "26px"
    fontWeight: 800
    lineHeight: 1
  figure:
    fontFamily: "Barlow Condensed, Arial Narrow, sans-serif"
    fontSize: "20px"
    fontWeight: 800
    lineHeight: 1.1
  item-title:
    fontFamily: "Be Vietnam Pro, -apple-system, Segoe UI, sans-serif"
    fontSize: "17px"
    fontWeight: 600
    lineHeight: 1.4
  body:
    fontFamily: "Be Vietnam Pro, -apple-system, Segoe UI, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.6
    fontFeature: "tnum"
  label:
    fontFamily: "Barlow Condensed, Arial Narrow, sans-serif"
    fontSize: "13px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "0.12em"
  label-small:
    fontFamily: "Barlow Condensed, Arial Narrow, sans-serif"
    fontSize: "12px"
    fontWeight: 600
    letterSpacing: "0.12em"
rounded:
  none: "0px"
spacing:
  gutter: "16px"
  item: "14px"
  category: "28px"
  layer: "40px"
  column: "760px"
  measure: "68ch"
components:
  serial-box:
    backgroundColor: "{colors.paper-white}"
    textColor: "{colors.serial-red}"
    typography: "{typography.display}"
    rounded: "{rounded.none}"
    padding: "4px 12px 2px"
  weather-box:
    backgroundColor: "{colors.paper-white}"
    textColor: "{colors.ink-navy}"
    rounded: "{rounded.none}"
    padding: "7px 8px 8px"
  strip-link:
    backgroundColor: "transparent"
    textColor: "{colors.ink-navy}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "8px 10px"
  strip-link-active:
    backgroundColor: "{colors.ink-navy}"
    textColor: "{colors.paper-white}"
  item-number:
    textColor: "{colors.serial-red}"
    typography: "{typography.numeral}"
    width: "42px"
  update-tag:
    backgroundColor: "{colors.serial-red}"
    textColor: "{colors.paper-white}"
    rounded: "{rounded.none}"
    padding: "3px 5px"
  board-figure:
    textColor: "{colors.ink-navy}"
    typography: "{typography.figure}"
    padding: "7px 10px"
  resume-flag:
    backgroundColor: "{colors.ink-navy}"
    textColor: "{colors.stub-saturday-pink}"
    rounded: "{rounded.none}"
    padding: "5px 10px"
---

> **Palette update (2026-11-21):** the page now uses the Bigman Backcom identity: black, lime `#C5FF2D`, white only, typography unchanged (Barlow Condensed 600/800 for display, labels and numbers; Be Vietnam Pro 400/600 for reading text). The ticket stubs are always black with lime accents; the weekday stub colours and serial red are retired. Light mode: white paper, black ink, lime only as a highlighter or label background behind black text (never lime text on white). Dark mode: black paper, white ink, lime text accents and a lime perforation edge. Market moves read by arrow plus tone: up is accent (black/lime), down is muted. Sections below that mention weekday colours, serial red describe the previous palette; layout and components are unchanged.


# Design System: Bản tin sáng

## Overview

**Creative North Star: "The Morning Ticket Stub"**

Every morning the page is printed as a fresh vé số kiến thiết stub. The date is the serial number, set huge in serial red inside a white ruled box; today's weather sits in the ticket's ruled cells; the market closes are the posted results board. The stub wears the weekday's colour the way provincial tickets do, under a fine guilloche security engraving and a microprint line, and is torn from the reading body along a punched perforation. Below the tear, the page is plain paper: navy ink, numbered items, dashed rules between them.

The system is flat, ruled and printed. Depth comes from colour fields and 2px ink borders, never from shadow, gradient, glow or rounded cards. Heavy condensed numerals carry everything countable or scannable (serial, temperatures, item numbers, figures, labels); a calm Vietnamese-first humanist sans carries everything you read. It refuses both the broadsheet-hairline digest and the app-card feed. No gambling vocabulary: it is a ticket you read, not one you play.

**Key Characteristics:**
- Locked four-colour palette: weekday stub colour, serial red, ink navy, paper white.
- Two typefaces with fixed jobs: Barlow Condensed for numbers and labels, Be Vietnam Pro for reading.
- Ruled boxes (2px ink borders, 1px inner dividers), square corners everywhere.
- Ticket devices live on stubs only: guilloche, microprint, perforation, field boxes.
- Continuous 01–N numbering that the contents, the reading flag and the closing stub all speak.
- One motion: the top perforation tears in once on load.

## Colors

A locked ticket palette: one weekday stub colour, one serial red, one ink, one paper, with a muted ink for secondary text and nothing else.

### Primary
- **Serial Red** (serial-red): The serial date, weather temperatures, item numbers, category underlines (3px), the "Cập nhật" tag, down-moves on the results board, original-source links and the focus ring. In dark mode it lightens to Lifted Serial Red (dark-serial-red) so it holds on the navy ground.

### Secondary
- **Weekday Stub** (stub-monday-sky through stub-sunday-yellow): The ground of the top stub, the closing stub, the perforation strips, the results-board caption, the reading flag, TOC row hover and text selection. Exactly one is live per day, chosen by `body[data-day]` from Python's weekday index (0 Monday sky, 1 Tuesday lime, 2 Wednesday orange, 3 Thursday violet, 4 Friday aqua, 5 Saturday pink, 6 Sunday yellow). Dark mode swaps each for its darkened twin (dark-stub-*).

### Neutral
- **Ink Navy** (ink-navy): All reading text, ruled-box borders, rules and dividers, the stub ink, the active strip button fill. Dark mode: Moon Ink (dark-ink) for text, Night Rule (dark-rule) for borders and rules, Stub White (dark-stub-ink) on stubs.
- **Paper White** (paper-white): The reading ground and the field inside every ruled box on a stub. Dark mode: Deep Ink Paper (dark-paper), which also becomes the box field.
- **Muted Ink** (ink-muted): Counts, "Lớp" tags, source caps lines, definition labels, missing-data text, the footer. Dark: dark-muted.
- **Engraving** (engrave-light / dark-engrave): The guilloche stroke on stubs only, translucent white over the stub colour.

### Named Rules
**The Four-Colour Lock Rule.** A screen uses the day's stub, serial red, ink and paper. No fifth hue, no tints of red as fills, no gradients. A new state finds its colour inside the lock.

**The Red On White Rule.** Serial red sits on paper or on a white field box, never directly on the stub colour. That is why the Sunday slot, which tickets print red, is yellow here: a red stub would swallow the serial.

**The Stub Owns The Colour Rule.** The weekday colour appears on stub-world surfaces and on the few elements that point back to them (board caption, reading flag, hover, selection). The reading column itself stays ink on paper.

## Typography

**Display Font:** Barlow Condensed 600/800 (with Arial Narrow, sans-serif)
**Body Font:** Be Vietnam Pro 400/600 (with -apple-system, Segoe UI, sans-serif)

**Character:** A ticket printer's condensed numerals against a warm Vietnamese-native reading face. Condensed means "count, scan, label"; Be Vietnam Pro means "read this". Both are self-hosted with vietnamese, latin and latin-ext subsets, and every figure on the page is tabular.

### Hierarchy
- **Display** (800, clamp(72px, 24vw, 96px), 0.95, -0.02em): The serial date only (21·11), serial red in its white box.
- **Headline** (800, 30px, 1.05, uppercase): Layer headings, with a muted "Lớp N" tag at 600 14px.
- **Title** (800, 22px, 1.15, uppercase): Category headings, underlined 3px serial red, item count at right. Stub and section titles use the same voice at 16–26px.
- **Numeral** (800, 26px, 1): Item numbers 01–N and weather temperatures (30px from 700px); closing takeaway numbers at 30px.
- **Figure** (800, 20px, 1.1, right-aligned): Results-board closes; changes at 17px.
- **Item title** (Be Vietnam Pro 600, 17px, 1.4, balanced): Headline of each numbered item, max 68ch.
- **Body** (Be Vietnam Pro 400, 16px, 1.6): Summaries and details (15px in the expanded definition list), max 68ch.
- **Label** (600, 11–15px, 0.06–0.14em, uppercase): Stub rows, weather slot names, strip buttons, the summary line (source plus "Xem đầy đủ ▾"), definition terms, captions.

### Named Rules
**The Two Voices Rule.** Anything countable, scannable or a control speaks Barlow Condensed in caps; anything to be read as prose speaks Be Vietnam Pro in sentence case. AI-written text is always in the reading face; the original-source link is always in the condensed red caps voice, so the summary and the source never look alike.

**The Tabular Everywhere Rule.** `font-variant-numeric: tabular-nums` is set on body; numbers line up in every box and column.

## Layout

A single centred column, 760px max with a 16px gutter (plus safe-area insets at top and bottom), at every width; the stubs bleed full width while their content stays in the column. Mobile first: on a 390px phone the top stub fills roughly half the first viewport. From 700px the serial box and the weather box sit side by side (minmax(260px,1fr) and 1.4fr) and the contents board splits into three layer columns.

Rhythm is ruled, not airy: 40px above a layer heading, 28px above a category, 14px top and bottom inside each item, 12px gaps inside the ticket. Items are a two-column grid (42px number gutter, fluid text). A sticky quick strip (Thời tiết, Thị trường, 3 điều, Mở tất cả) pins to the top with a 2px ink underline; `scroll-padding-top: 56px` keeps anchors clear of it.

## Elevation & Depth

Flat. There are no shadows anywhere. Depth is printed: a colour field (the stub) against paper, white field boxes inset on the stub with 2px ink borders, and the punched perforation marking where the stub tears from the body. The guilloche and microprint are surface texture, not depth.

### Named Rules
**The Printed Not Lifted Rule.** Separation comes from colour fields, ink rules and the perforation. No box-shadow, no glow, no gradient, no blur.

## Shapes

Square corners throughout (0px); the only radius is the 2px on the focus outline. Borders are the grammar: 2px solid ink for every ruled box (serial, weather, results board, contents, closing list, notice), 1px solid ink for dividers inside a box, 1.5px for strip buttons, 3px serial red under category headings, 1px dashed ink between items. The one curved silhouette is the perforation: a 12px strip in the stub colour, masked into 11px half-circle punches on a 16px repeat, flipped vertically where the closing stub begins.

### Named Rules
**The Ruled Box Rule.** A container is a 2px ink rectangle with 1px inner rules, or it is not a container. No cards, no fills behind content in the reading column, no rounded corners.

## Components

### Ticket Stub (signature)
The page's identity. Full-bleed band in the weekday colour with stub ink text. Behind it, an inline SVG guilloche pattern (sine-wave strands, 72×44 tile, 0.6px non-scaling stroke in the engraving colour); at its foot, a microprint line repeating "Bản tin sáng · serial · year" (600 7px condensed caps, decorative, aria-hidden). Inside: the caps row (title left, "Cập nhật HH:MM" right), the serial box, the weather box, the location row, the advice list (600 14px) and, when present, the reading flag. The page closes with a second stub ("3 điều cần nhớ hôm nay") that repeats the morning serial as "Cuống 21·11", with the takeaways as a ruled white list (44px red numeral cell, 2px ink divider, reading-face text).

### Serial Box
White field, 2px stub-ink border, the date in Display serial red at left, weekday (800 24px caps) and "year · N tin" (600 13px) stacked at right, bottom-aligned.

### Weather Box
A three-cell ruled box (white field, 2px border, 1px cell dividers): slot name and hours in label caps, temperature range in serial-red numerals, then sky, rain % and mm, and UV when 3 or more, in 12px reading text. A missing slot shows "Chưa có dữ liệu" in muted condensed.

### Perforation
12px stub-coloured strip with punched half-circles (inline SVG mask, 16px repeat). Below the top stub it tears in once on load: `clip-path` from `inset(0 100% 0 0)` to `inset(0)`, 0.9s with a 0.15s delay on `cubic-bezier(.16,1,.3,1)`, only under `prefers-reduced-motion: no-preference`. Above the closing stub it is flipped and static.

### Quick Strip
Sticky nav on paper with a 2px ink underline. Buttons are square outline chips (1.5px ink border, 600 14px condensed caps, 8px 10px padding). Hover and the pressed "Mở tất cả / Thu gọn tất cả" state invert to an ink fill with paper text.

### Numbered Item
Grid of a red 26px numeral (01–N, continuous across the whole page) and the text column: severity emoji, item title, optional red "Cập nhật" tag (800 11px caps, paper on red), summary, then a native `<details>` whose summary line is the source in ink plus "Xem đầy đủ ▾" in muted caps that turns red on hover and when open. Expanded: a definition list (muted caps terms, 15px reading text) and the original-source link in 800 15px red caps with an inline SVG out-arrow. Items are separated by 1px dashed ink rules. An empty category reads "Không có tin nổi bật mới." in muted text.

### Reading Flag (signature interaction)
"Cờ đọc dở": the last item opened today is stored in localStorage (key `banTinSang.flag`, guarded by try/catch, scoped to the date) unless "Mở tất cả" is active. On return the item carries a stub-coloured corner tag "Đang đọc dở" (800 11px caps) and the top stub shows an inverted ink button, "Đọc tiếp từ tin 07", with an inline SVG arrow. Without storage, the page renders unchanged.

### Results Board
The market table at the head of the economy category: a 2px ink ruled box whose caption bar ("Bảng giá đóng cửa") is the stub colour with a 2px rule beneath. Rows: instrument name in 600 15px reading face with a muted "Phiên" date, close in 800 20px condensed right-aligned, change at 17px with a 9px solid SVG triangle; down-moves are serial red, up-moves stay ink. Missing data spans both cells as "Chưa có dữ liệu". The SJC gold row is a red caps link.

### Contents Board
"Mục lục": a ruled box with one column per layer (stacked on mobile, three columns from 700px with 2px vertical rules). Each category row is a grid of a 58px red number range (05–09, or "––" when empty) and its label; rows hover to the stub colour with the number turning stub ink.

### Notice
The degraded-AI notice is a plain 2px ink ruled box with 14px text above the contents.

## Do's and Don'ts

### Do:
- **Do** pick the stub colour from `body[data-day]` and the weekday's light or dark twin; never hard-code one weekday's colour into a component.
- **Do** put serial red on paper or a white field box (serial, temperatures, numerals, takeaway numbers).
- **Do** draw every container as a 2px ink ruled box with 1px inner rules and square corners.
- **Do** number items continuously 01–N across the page and reuse those numbers in the contents, the reading flag and links.
- **Do** set numbers, labels and controls in Barlow Condensed caps and all reading text in Be Vietnam Pro, at a 68ch measure.
- **Do** show missing data explicitly as "Chưa có dữ liệu" in muted condensed, never a blank or an invented value.
- **Do** keep ticket devices (guilloche, microprint, perforation, field boxes) on stubs, and gate any motion behind `prefers-reduced-motion: no-preference`.
- **Do** draw icons as small inline SVG in currentColor (arrows, triangles).

### Don't:
- **Don't** use shadows, gradients, glow, blur or rounded cards.
- **Don't** add a fifth hue or fill areas with tints of serial red.
- **Don't** set serial red directly on a stub colour, and don't give a weekday a red stub.
- **Don't** spread guilloche or perforation into the reading column.
- **Don't** use gambling vocabulary ("giải", "trúng") or any shop branding.
- **Don't** add motion beyond the one-time perforation tear-in.
