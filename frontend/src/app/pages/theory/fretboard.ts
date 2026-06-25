import { Component, ElementRef, HostListener, effect, input, viewChild } from '@angular/core';
import { FretPosition } from '../../theory/fretboard';
import { Tuning } from '../../theory/tunings';
import { mod12 } from '../../theory/notes';

/**
 * A horizontal guitar-neck diagram drawn on canvas. The nut is on the left; the lowest-pitch
 * string sits at the bottom. It just renders whatever `positions` it's handed (computed by the
 * parent via `fretPositions`), emphasising roots and any currently-sounding pitch classes
 * (`highlightPcs`). Shared by the Theory and Practice pages — like `app-stem-waveform`, it's a
 * self-contained canvas component with no audio/state of its own.
 */
@Component({
  selector: 'app-fretboard',
  standalone: true,
  template: `<canvas #cv class="fretboard"></canvas>`,
  styles: [`
    :host { display: block; width: 100%; }
    canvas.fretboard { display: block; width: 100%; height: 200px; }
  `],
})
export class Fretboard {
  tuning = input.required<Tuning>();
  positions = input.required<FretPosition[]>();
  maxFret = input(15);
  /** Pitch classes to draw as "active" right now (e.g. the current chord/scale step). */
  highlightPcs = input<number[]>([]);
  /** Fade non-active notes so the active note stands out (used by the practice tool). */
  dimInactive = input(false);
  /** Optional "hand position": only frets in [start, end] stay lit; the rest are ghosted. */
  handWindow = input<{ start: number; end: number } | null>(null);

  private cv = viewChild<ElementRef<HTMLCanvasElement>>('cv');

  constructor() {
    // Redraw whenever inputs or the canvas element change. The effect runs after the view exists,
    // so the canvas is available on the first meaningful pass.
    effect(() => {
      this.tuning(); this.positions(); this.maxFret(); this.highlightPcs();
      this.dimInactive(); this.handWindow();
      this.cv();
      this.draw();
    });
  }

  @HostListener('window:resize') draw() {
    const cv = this.cv()?.nativeElement;
    if (!cv) return;
    const tuning = this.tuning();
    const positions = this.positions();
    const maxFret = this.maxFret();
    const hi = new Set(this.highlightPcs().map(mod12));
    const dim = this.dimInactive();
    const win = this.handWindow();
    const strings = tuning.strings.length;

    const w = cv.clientWidth || 800;
    const h = cv.clientHeight || 170;
    const dpr = window.devicePixelRatio || 1;
    cv.width = Math.round(w * dpr);
    cv.height = Math.round(h * dpr);
    const ctx = cv.getContext('2d');
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);

    const padL = 34, padR = 14, padT = 16, padB = 34;
    const x0 = padL;                                // nut
    const x1 = w - padR;
    const fw = (x1 - x0) / maxFret;                 // fret width
    const y0 = padT;
    const y1 = h - padB;
    const sp = strings > 1 ? (y1 - y0) / (strings - 1) : 0;
    const yFor = (str: number) => y0 + (strings - 1 - str) * sp; // low string at bottom

    // Fretboard background + frets.
    ctx.fillStyle = '#171a21';
    ctx.fillRect(x0, y0 - 4, x1 - x0, (y1 - y0) + 8);
    ctx.strokeStyle = '#3a4150';
    ctx.lineWidth = 1;
    for (let f = 1; f <= maxFret; f++) {
      const x = x0 + f * fw;
      ctx.beginPath(); ctx.moveTo(x, y0 - 4); ctx.lineTo(x, y1 + 4); ctx.stroke();
    }
    // Nut (thicker).
    ctx.strokeStyle = '#9aa0ac'; ctx.lineWidth = 3;
    ctx.beginPath(); ctx.moveTo(x0, y0 - 4); ctx.lineTo(x0, y1 + 4); ctx.stroke();

    // Inlay markers.
    ctx.fillStyle = '#2c323d';
    const midY = (y0 + y1) / 2;
    for (const f of [3, 5, 7, 9, 15, 17, 19, 21]) {
      if (f > maxFret) continue;
      const x = x0 + (f - 0.5) * fw;
      ctx.beginPath(); ctx.arc(x, midY, 4, 0, Math.PI * 2); ctx.fill();
    }
    for (const f of [12, 24]) { // double dots at the octave
      if (f > maxFret) continue;
      const x = x0 + (f - 0.5) * fw;
      ctx.beginPath(); ctx.arc(x, y0 + sp * 0.6, 4, 0, Math.PI * 2); ctx.fill();
      ctx.beginPath(); ctx.arc(x, y1 - sp * 0.6, 4, 0, Math.PI * 2); ctx.fill();
    }

    // Strings.
    ctx.strokeStyle = '#525a68'; ctx.lineWidth = 1;
    for (let s = 0; s < strings; s++) {
      const y = yFor(s);
      ctx.beginPath(); ctx.moveTo(x0 - 18, y); ctx.lineTo(x1, y); ctx.stroke();
    }

    // Hand-position window band.
    if (win) {
      const bx0 = x0 + Math.max(0, win.start - 1) * fw;
      const bx1 = x0 + Math.min(maxFret, Math.max(win.start, win.end)) * fw;
      ctx.fillStyle = 'rgba(91,140,255,0.12)';
      ctx.fillRect(bx0, y0 - 6, bx1 - bx0, (y1 - y0) + 12);
      ctx.strokeStyle = 'rgba(91,140,255,0.6)'; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(bx0, y0 - 8); ctx.lineTo(bx0, y1 + 8); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(bx1, y0 - 8); ctx.lineTo(bx1, y1 + 8); ctx.stroke();
    }

    // Fret numbers — sit below the bottom row of dots so they stay readable.
    ctx.fillStyle = '#6b7280'; ctx.font = '10px Segoe UI, sans-serif'; ctx.textAlign = 'center';
    for (const f of [3, 5, 7, 9, 12, 15, 17, 19, 21, 24]) {
      if (f > maxFret) continue;
      ctx.fillText(String(f), x0 + (f - 0.5) * fw, y1 + 24);
    }

    // Note dots.
    const r = Math.min(12, sp * 0.42);
    ctx.font = `bold ${Math.round(r)}px Segoe UI, sans-serif`;
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    for (const p of positions) {
      const x = p.fret === 0 ? x0 - 18 : x0 + (p.fret - 0.5) * fw;
      const y = yFor(p.string);
      const inWin = !win || (p.fret >= win.start && p.fret <= win.end);
      // The "current" note only counts as active inside the hand-position window, so a single
      // instance lights up rather than every octave across the neck.
      const active = inWin && hi.has(mod12(p.pc));
      let alpha: number;
      if (active) alpha = 1;                     // the note to play right now
      else if (win && !inWin && dim) alpha = 0.13;  // ghost out-of-window (scale "dim" mode only)
      else alpha = dim ? 0.3 : 0.82;            // dimmed scale tone, or a lit chord-voicing note

      ctx.beginPath(); ctx.arc(x, y, active ? r + 1.5 : r, 0, Math.PI * 2);
      ctx.fillStyle = p.isRoot ? '#5b8cff' : '#46d39a';
      ctx.globalAlpha = alpha;
      ctx.fill();
      if (active) { ctx.lineWidth = 2.5; ctx.strokeStyle = '#fff'; ctx.stroke(); }
      ctx.globalAlpha = 1;
      // Skip labels on heavily-ghosted notes to keep the lit window clean.
      if (alpha >= 0.25) {
        ctx.fillStyle = p.isRoot ? '#fff' : '#0c0e12';
        ctx.fillText(p.label, x, y + 0.5);
      }
    }
    ctx.textBaseline = 'alphabetic';
  }
}
