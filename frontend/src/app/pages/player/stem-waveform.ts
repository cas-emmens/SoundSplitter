import {
  AfterViewInit, Component, ElementRef, EventEmitter, HostListener,
  Input, OnInit, Output, ViewChild, inject,
} from '@angular/core';
import { Api } from '../../services/api';

/**
 * Waveform strip for one stem with two drag handles to trim dead space off the
 * front/end. Non-destructive: emits trim amounts (ms from each edge); the page
 * applies them live in the player and persists them. Draws from precomputed
 * peaks (no audio decode here).
 */
@Component({
  selector: 'app-stem-waveform',
  standalone: true,
  template: `
    <div class="wf" #wrap>
      <canvas #cv></canvas>
      <div class="dim left" [style.width.%]="startPct"></div>
      <div class="dim right" [style.width.%]="endPct"></div>
      <div class="handle" [style.left.%]="startPct" (pointerdown)="grab($event, 'start')"
           title="Trim start"></div>
      <div class="handle" [style.left.%]="100 - endPct" (pointerdown)="grab($event, 'end')"
           title="Trim end"></div>
    </div>
  `,
  styles: [`
    .wf { position: relative; height: 46px; width: 100%;
          background: #14161c; border-radius: 6px; overflow: hidden;
          user-select: none; touch-action: none; }
    canvas { display: block; width: 100%; height: 100%; }
    .dim { position: absolute; top: 0; bottom: 0; background: rgba(8,9,12,0.66);
           pointer-events: none; }
    .dim.left { left: 0; }
    .dim.right { right: 0; }
    .handle { position: absolute; top: 0; bottom: 0; width: 9px; margin-left: -4px;
              cursor: ew-resize; background: #ffd166;
              box-shadow: 0 0 0 1px rgba(0,0,0,0.4); }
    .handle::after { content: ''; position: absolute; top: 50%; left: 50%;
              width: 2px; height: 16px; margin: -8px 0 0 -1px; background: #1a1d24; }
  `],
})
export class StemWaveform implements OnInit, AfterViewInit {
  private api = inject(Api);

  @Input({ required: true }) trackId!: string;
  @Input({ required: true }) name!: string;
  @Input() trimStartMs = 0;
  @Input() trimEndMs = 0;
  @Output() trimChange = new EventEmitter<{ startMs: number; endMs: number }>();

  @ViewChild('cv') cv!: ElementRef<HTMLCanvasElement>;
  @ViewChild('wrap') wrap!: ElementRef<HTMLDivElement>;

  durationMs = 0;
  private peaks: number[] = [];
  private dragging: 'start' | 'end' | null = null;

  get startPct() { return this.durationMs ? Math.min(100, (this.trimStartMs / this.durationMs) * 100) : 0; }
  get endPct() { return this.durationMs ? Math.min(100, (this.trimEndMs / this.durationMs) * 100) : 0; }

  ngOnInit() {
    this.api.stemPeaks(this.trackId, this.name).subscribe((p) => {
      this.peaks = p.peaks;
      this.durationMs = p.duration * 1000;
      queueMicrotask(() => this.draw());
    });
  }
  ngAfterViewInit() { this.draw(); }

  @HostListener('window:resize') draw() {
    const cv = this.cv?.nativeElement;
    if (!cv || !this.peaks.length) return;
    const w = cv.clientWidth || 600;
    const h = cv.clientHeight || 46;
    const dpr = window.devicePixelRatio || 1;
    cv.width = Math.round(w * dpr);
    cv.height = Math.round(h * dpr);
    const ctx = cv.getContext('2d');
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = '#6c8cff';
    const n = this.peaks.length;
    const mid = h / 2;
    for (let x = 0; x < w; x++) {
      const peak = this.peaks[Math.min(n - 1, Math.floor((x / w) * n))] ?? 0;
      const bh = Math.max(1, peak * (mid - 1));
      ctx.fillRect(x, mid - bh, 1, bh * 2);
    }
  }

  grab(ev: PointerEvent, which: 'start' | 'end') {
    ev.preventDefault();
    this.dragging = which;
  }

  @HostListener('document:pointermove', ['$event'])
  onMove(ev: PointerEvent) {
    if (!this.dragging || !this.durationMs) return;
    const rect = this.wrap.nativeElement.getBoundingClientRect();
    const frac = Math.min(1, Math.max(0, (ev.clientX - rect.left) / rect.width));
    const ms = frac * this.durationMs;
    const minGap = Math.min(this.durationMs * 0.02, 200); // keep an audible sliver
    if (this.dragging === 'start') {
      this.trimStartMs = Math.max(0, Math.min(ms, this.durationMs - this.trimEndMs - minGap));
    } else {
      this.trimEndMs = Math.max(0, Math.min(this.durationMs - ms, this.durationMs - this.trimStartMs - minGap));
    }
  }

  @HostListener('document:pointerup')
  onUp() {
    if (!this.dragging) return;
    this.dragging = null;
    this.trimChange.emit({ startMs: Math.round(this.trimStartMs), endMs: Math.round(this.trimEndMs) });
  }
}
