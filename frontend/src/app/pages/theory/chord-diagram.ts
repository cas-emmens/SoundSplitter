import { Component, ElementRef, HostListener, effect, input, viewChild } from '@angular/core';
import { ResolvedShape } from '../../theory/chord-shapes';

/**
 * A standard vertical chord-box diagram (canvas): 6 strings (low E on the left), a few frets, with
 * finger-numbered dots, a barre bar, ×/○ markers above the nut, and a base-fret label for shapes up
 * the neck. Renders a single `ResolvedShape` from chord-shapes.ts.
 */
@Component({
  selector: 'app-chord-diagram',
  standalone: true,
  template: `<canvas #cv class="cd"></canvas>`,
  styles: [`
    :host { display: block; }
    canvas.cd { display: block; width: 112px; height: 144px; }
  `],
})
export class ChordDiagram {
  shape = input.required<ResolvedShape>();
  private cv = viewChild<ElementRef<HTMLCanvasElement>>('cv');

  constructor() {
    effect(() => { this.shape(); this.cv(); this.draw(); });
  }

  @HostListener('window:resize') draw() {
    const cv = this.cv()?.nativeElement;
    if (!cv) return;
    const s = this.shape();
    const N = 6, F = 5;

    const w = cv.clientWidth || 112, h = cv.clientHeight || 144;
    const dpr = window.devicePixelRatio || 1;
    cv.width = Math.round(w * dpr);
    cv.height = Math.round(h * dpr);
    const ctx = cv.getContext('2d');
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);

    const mL = 16, mR = 16, mT = 26, mB = 12;
    const gx = mL, gridW = w - mL - mR;
    const sGap = gridW / (N - 1);
    const gy = mT, gridH = h - mT - mB;
    const fGap = gridH / F;
    const nut = s.baseFret <= 1;

    // Grid.
    ctx.strokeStyle = '#525a68'; ctx.lineWidth = 1;
    for (let r = 0; r <= F; r++) {
      const y = gy + r * fGap;
      ctx.beginPath(); ctx.moveTo(gx, y); ctx.lineTo(gx + gridW, y); ctx.stroke();
    }
    for (let i = 0; i < N; i++) {
      const x = gx + i * sGap;
      ctx.beginPath(); ctx.moveTo(x, gy); ctx.lineTo(x, gy + gridH); ctx.stroke();
    }
    if (nut) {
      ctx.strokeStyle = '#9aa0ac'; ctx.lineWidth = 4;
      ctx.beginPath(); ctx.moveTo(gx - 0.5, gy); ctx.lineTo(gx + gridW + 0.5, gy); ctx.stroke();
    } else {
      ctx.fillStyle = '#9aa0ac'; ctx.font = '11px Segoe UI, sans-serif';
      ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
      ctx.fillText(`${s.baseFret}fr`, gx - 5, gy + fGap * 0.5);
    }

    // ×/○ markers above the nut.
    ctx.font = '12px Segoe UI, sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    for (let i = 0; i < N; i++) {
      const x = gx + i * sGap, y = gy - 9, f = s.frets[i];
      if (f < 0) { ctx.fillStyle = '#7a818d'; ctx.fillText('×', x, y); }
      else if (f === 0) {
        ctx.strokeStyle = '#7a818d'; ctx.lineWidth = 1.4;
        ctx.beginPath(); ctx.arc(x, y, 3.5, 0, Math.PI * 2); ctx.stroke();
      }
    }

    // Barre bar.
    const barreFret = s.barre ? s.barre.fret : -99;
    if (s.barre) {
      const row = s.barre.fret - s.baseFret + 1;
      const cy = gy + (row - 0.5) * fGap;
      const x1 = gx + s.barre.from * sGap, x2 = gx + s.barre.to * sGap;
      ctx.strokeStyle = '#5b8cff'; ctx.lineWidth = sGap * 0.55; ctx.lineCap = 'round';
      ctx.beginPath(); ctx.moveTo(x1, cy); ctx.lineTo(x2, cy); ctx.stroke();
      ctx.lineCap = 'butt';
    }

    // Finger dots (skip notes already covered by the barre).
    const r = sGap * 0.34;
    for (let i = 0; i < N; i++) {
      const f = s.frets[i];
      if (f <= 0) continue;
      if (s.barre && f === barreFret && i >= s.barre.from && i <= s.barre.to) continue;
      const row = f - s.baseFret + 1;
      if (row < 1 || row > F) continue;
      const cx = gx + i * sGap, cy = gy + (row - 0.5) * fGap;
      ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.fillStyle = '#5b8cff'; ctx.fill();
      const finger = s.fingers[i];
      if (finger > 0) {
        ctx.fillStyle = '#fff'; ctx.font = `bold ${Math.round(r * 1.4)}px Segoe UI, sans-serif`;
        ctx.fillText(String(finger), cx, cy + 0.5);
      }
    }
    ctx.textBaseline = 'alphabetic';
  }
}
