# QA Frontend Design System

## 1. Atmosphere & Identity

An operational accessibility test console: compact, evidence-led, and calm under dense runtime data. The signature is muted blue-gray panels with explicit status text, so environment differences and comparator outcomes remain understandable without relying on color alone.

## 2. Color

| Role | Token | Value | Usage |
|---|---|---|---|
| Surface primary | `--surface-primary` | `#ffffff` | Main panels and controls |
| Surface secondary | `--surface-secondary` | `#f6f8fa` | Detail cards and hints |
| Text primary | `--text-primary` | `#172026` | Headings and values |
| Text secondary | `--text-secondary` | `#5e6c78` | Labels and help text |
| Border default | `--border-default` | `#dce3e9` | Cards and separators |
| Accent primary | `--accent-primary` | `#245f82` | Actions and comparator identity |
| Status success | `--status-success` | `#215a2f` | Compatible/status text |
| Status warning | `--status-warning` | `#684f00` | Environment difference guidance |
| Status error | `--status-error` | `#8d1e1e` | Blocking errors |

## 3. Typography

Primary font is the existing system sans-serif stack. Comparator metadata uses 11–13px caption/body-small sizing to preserve density; body text remains readable and wraps long values rather than forcing horizontal scroll.

## 4. Spacing & Layout

The existing 4px rhythm is preserved. Comparator selectors use a three-column grid on wide screens and one column below 900px. Environment details use a two-card switcher that collapses to one column on narrow screens.

## 5. Components

### Comparator selector

- **Structure:** labelled native `<select>` controls and a Compare button.
- **States:** default, selected, disabled, loading, empty, error.
- **Accessibility:** explicit `label`/`id` association, keyboard-native selection, title/full detail fallback for truncated labels.

### Environment card

- **Structure:** semantic `<article>` with a heading, four summary lines, and a small metadata row.
- **States:** complete values and Unknown values.
- **Accessibility:** values are present as text, not color-only indicators; long values wrap by word.

### Environment notice

- **Structure:** live status region with a status title and explanatory text.
- **Variants:** `Environment differs`, `Environment appears compatible`.
- **Accessibility:** `role="status"` and `aria-live`; wording explains that Comparator Core remains authoritative.

## 6. Motion & Interaction

No new motion is introduced. Native controls retain browser keyboard and focus behavior; existing page motion remains unchanged.

## 7. Depth & Surface

The existing borders-only / light tonal-shift treatment is preserved. New cards use the established light surface and border tokens without introducing a new shadow system.

## 8. Accessibility Constraints & Accepted Debt

- WCAG 2.2 AA intent: visible native focus, keyboard access, semantic labels, and non-color status wording.
- The native select option rendering is browser-controlled and may truncate differently by platform; the selected control has a title and the environment cards expose the complete values.
