# SoundSplitter — logo & icon design brief

Paste this whole file into Claude Desktop and use **Designer** to generate the assets below.
It contains everything needed: what the app is, the exact color palette, the concept direction,
and the precise deliverables (sizes/formats) with where each one ends up in the project.

---

## What the app is (concept fuel)

**SoundSplitter** is a desktop music tool. It captures a song and **splits it into 6 separate
instrument tracks** — *vocals, drums, bass, guitar, piano, and "other"* — using AI source
separation. You then get a multitrack **mixer**: mute/solo any stem, hit "Practice mode" to drop
vocals + guitar for an instant backing track, and even generate guitar tabs.

The core idea to express visually: **one sound coming apart into separate layers/parts.**
Think: a single waveform fanning out into multiple colored bands; a beam of sound passing through
a prism and separating into its components; layered/offset audio tracks; an EQ/fader motif (the
current placeholder is the 🎚️ fader emoji).

**Personality:** modern, technical-but-musical, clean, confident. Not playful/cartoonish, not
corporate. It lives in a sleek **dark** UI. A pro-audio / studio feel suits it.

---

## Color palette (from the app's actual theme — dark UI)

| Role | Hex | Use |
|---|---|---|
| Background | `#14161b` | near-black app canvas (logos sit on this) |
| Panel | `#1d2027` / `#262a33` | slightly lighter surfaces |
| Text | `#e7e9ee` | off-white (wordmark text) |
| Muted | `#9aa0ac` | secondary gray |
| **Accent (primary)** | `#5b8cff` | electric blue — the brand's lead color |
| **Accent 2** | `#46d39a` | mint green — secondary/highlight |
| Danger | `#ff6b6b` | red (avoid for branding) |

Lead with **electric blue `#5b8cff`**, support with **mint `#46d39a`**. A blue→green gradient, or
using the 6 stems as a small multicolor accent (e.g. a 6-bar spectrum), are both on-brand.
Everything must look great on the dark `#14161b` background and remain legible in light contexts too.

Typography vibe: clean geometric/grotesk sans (the UI uses Segoe UI / system sans). Wordmark can be
slightly tightened, lowercase or title case — see options below.

---

## Concept directions (pick/blend — Designer can explore a few)

1. **Split waveform** — a horizontal audio waveform that, at its center, fans/splits into 2–6
   diverging colored strands. Reads instantly as "one sound → many parts."
2. **Prism split** — a single white sound-wave line entering a shape and exiting as a blue→green
   (or 6-color) spectrum. Elegant, premium.
3. **Stacked stems** — 3–6 offset rounded bars/lanes (like mixer tracks) forming a tight mark,
   optionally with a "split" gap down the middle.
4. **Fader/EQ glyph** — abstracted fader sliders (nod to the current 🎚️) arranged so the negative
   space or split suggests separation.

Recommended starting point: **#1 or #2**, in blue with a mint accent, as the icon; then set the
wordmark beside it for the header lockup.

---

## Deliverables

### Asset A — App icon (square mark, no text)
The standalone symbol. Must be **simple and bold enough to read at 16–32px** (taskbar, installer,
favicon) while still looking good large. Square, works on dark; provide a version that also holds
up on light. Subtle depth/gradient is fine but keep it crisp at tiny sizes.

Export these (this is exactly the set the app/installer consume):

| File | Size | Format | Used by |
|---|---|---|---|
| `icon.png` | 1024×1024 | PNG (transparent) | master |
| `32x32.png` | 32×32 | PNG | Tauri/window |
| `64x64.png` | 64×64 | PNG | Tauri |
| `128x128.png` | 128×128 | PNG | Tauri |
| `128x128@2x.png` | 256×256 | PNG | Tauri (hi-dpi) |
| `icon.ico` | multi-res (16,32,48,256) | ICO | **Windows installer + taskbar + favicon** |
| `favicon.ico` | multi-res (16,32,48) | ICO | browser tab |

> The installer icon and the EXE icon both come from `icon.ico`, so prioritize how the mark looks
> at 16/32px there.

### Asset B — Header logo lockup (icon + wordmark)
A horizontal **"icon + 'SoundSplitter'"** lockup for the top-left of the app's dark toolbar.
It renders small — about **28px tall** — so keep the wordmark legible at that height; the icon is
Asset A's symbol. Title case "SoundSplitter" (the current text is lowercase "sound-splitter" —
open to either, but a clean title-case wordmark looks more finished).

| File | Spec | Used by |
|---|---|---|
| `logo-wordmark.svg` | vector, transparent, designed for ~28px height (horizontal) | app toolbar |
| `logo-wordmark.png` | ~ 480×120 @2x, transparent | fallback |

Provide it tuned for **dark backgrounds** (off-white `#e7e9ee` text). A light-bg variant is a nice
bonus but not required.

---

## Where these land in the project (for reference)

- App icon set → `src-tauri/icons/` (replace the current Angular-default files of the same names).
  The Inno installer's `SetupIconFile` and the EXE icon both use `src-tauri/icons/icon.ico`.
- Favicon → `frontend/public/favicon.ico` (currently the Angular default).
- Header lockup → `frontend/public/logo-wordmark.svg`, shown in `frontend/src/app/app.html`
  (the `<span class="brand">🎚️ sound-splitter</span>` becomes an `<img>`).

Once you've generated them, drop the files into those folders and I'll wire up the header `<img>`,
swap the favicon, and (optionally) fix the browser tab title which currently still says "Frontend".

---

## Quick checklist for Designer

- [ ] Square app icon, crisp at 16–32px, great on `#14161b`, blue `#5b8cff` lead + mint `#46d39a`.
- [ ] Concept = "one sound splitting into parts" (waveform/prism/stems).
- [ ] Horizontal header lockup (icon + "SoundSplitter") tuned for ~28px on dark.
- [ ] Export the file/size table above (PNGs + multi-res ICOs + SVG wordmark).
- [ ] Keep it modern, clean, studio/pro-audio feel — not cartoonish.
