import {
  Component, ElementRef, OnDestroy, OnInit, computed, inject, signal, viewChild,
} from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import * as alphaTab from '@coderline/alphatab';
import { Api, Tab } from '../../services/api';

interface BeatSpot {
  x: number; y: number; w: number; h: number;  // beat bounds in the tab strip
  bar: number;        // 0-based bar index
  notated: number;    // notated seconds of the beat's onset
}

/**
 * Manual timing editor (Cas's spec): the tab as one continuous horizontal system on
 * top, the stem's full-detail waveform below, anchors as draggable handles on the
 * waveform. Click an anchor to see its note in the tab; click a note to select or
 * create its anchor; drag (or arrow-nudge) to retime by ear, with play/pause/seek
 * always at hand. Hand-placed anchors are saved as `manual` and survive re-syncs.
 */
@Component({
  selector: 'app-timing-editor',
  standalone: true,
  imports: [RouterLink, FormsModule],
  template: `
    <div class="editor">
      <div class="toolbar">
        <a [routerLink]="['/tabs', tab()?.track_id]" class="back">← Tabs</a>
        <strong>{{ tab()?.name }}</strong> <span class="dim">timing</span>
        <button class="transport" (click)="togglePlay()">{{ playing() ? '⏸' : '⏵' }}</button>
        <span class="time">{{ timeLabel() }}</span>
        <label class="dim">zoom
          <input type="range" min="40" max="400" step="10" [ngModel]="pps()" (ngModelChange)="setZoom($event)">
        </label>
        <label class="dim"><input type="checkbox" [(ngModel)]="follow"> follow</label>
        <button (click)="undo()" [disabled]="!undoCount()" title="Undo last anchor edit (Ctrl+Z)">↩ Undo</button>
        <button (click)="resync()" [disabled]="syncing()"
                title="Re-run the automatic sync — your manual anchors guide the whole alignment">
          {{ syncing() ? '⟳ Syncing…' : '⟳ Guided re-sync' }}
        </button>
        <span class="dim counts">{{ anchors().length }} anchors · {{ manualCount() }} manual</span>
        <span class="status">{{ status() }}</span>
        <span class="hint dim">click note ↔ anchor · drag or ←/→ nudges (shift = coarse) · A = anchor to playhead · [ ] = prev/next · Del removes a manual anchor</span>
      </div>

      <div class="tabstrip" #tabScroll>
        <div class="atwrap" #atWrap (click)="onTabClick($event)">
          <div #atHost></div>
          @if (highlight(); as hl) {
            <div class="note-hl" [style.left.px]="hl.x" [style.top.px]="hl.y"
                 [style.width.px]="hl.w" [style.height.px]="hl.h"></div>
          }
          <div class="tab-cursor" #tabCursor></div>
        </div>
      </div>

      <div class="wave" #waveScroll (scroll)="drawWave()">
        <div class="spacer" [style.width.px]="totalPx()" (pointerdown)="onWaveDown($event)">
          <canvas #waveCanvas></canvas>
          @for (a of anchors(); track $index) {
            <div class="anchor" [class.manual]="isManual(a)" [class.selected]="$index === selected()"
                 [style.left.px]="a[1] * pps()"
                 (pointerdown)="grabAnchor($event, $index)">
              <div class="head"></div>
            </div>
          }
          <div class="playhead" #playhead></div>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .editor { display: flex; flex-direction: column; height: calc(100dvh - 104px); gap: 8px; }
    .toolbar { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
    .toolbar .back { color: #9ab; text-decoration: none; }
    .toolbar .transport { font-size: 18px; width: 42px; padding: 3px 0; }
    .toolbar .time { font-variant-numeric: tabular-nums; min-width: 88px; }
    .toolbar .status { color: #8f8; min-width: 70px; }
    .dim { color: #889; font-size: 12px; }
    .hint { margin-left: auto; }
    /* White panel like the tabs page's score-scroll: alphaTab draws black glyphs. */
    .tabstrip { flex: 0 1 auto; max-height: 46%; min-height: 160px; overflow: auto;
                background: #fff; border-radius: 8px; }
    .atwrap { position: relative; width: max-content; min-width: 100%; }
    .note-hl { position: absolute; background: rgba(108,140,255,0.3);
               outline: 2px solid #6c8cff; border-radius: 3px; pointer-events: none; }
    .tab-cursor { position: absolute; top: 0; bottom: 0; width: 2px; background: #ffd166;
                  pointer-events: none; display: none; }
    .wave { flex: 1 1 auto; min-height: 200px; overflow: auto hidden; background: #0c0e13;
            border-radius: 8px; position: relative; }
    .spacer { position: relative; height: 100%; }
    canvas { position: sticky; left: 0; display: block; height: 100%; }
    .anchor { position: absolute; top: 0; bottom: 0; width: 0; cursor: ew-resize; }
    .anchor::before { content: ''; position: absolute; top: 0; bottom: 0; left: -1px;
                      width: 2px; background: rgba(120,220,160,0.55); }
    .anchor .head { position: absolute; top: 2px; left: -7px; width: 14px; height: 14px;
                    background: #6fdca0; transform: rotate(45deg); border-radius: 3px;
                    cursor: grab; }
    .anchor::after { content: ''; position: absolute; top: 0; bottom: 0; left: -7px;
                     width: 14px; }  /* fat hit area */
    .anchor.manual::before { background: rgba(255,209,102,0.75); }
    .anchor.manual .head { background: #ffd166; }
    .anchor.selected .head { outline: 3px solid #fff; }
    .anchor.selected::before { background: #fff; }
    .playhead { position: absolute; top: 0; bottom: 0; width: 1px; background: #ff6a6a;
                pointer-events: none; }
  `],
})
export class TimingEditorPage implements OnInit, OnDestroy {
  private api = inject(Api);
  private route = inject(ActivatedRoute);

  tab = signal<Tab | null>(null);
  anchors = signal<[number, number][]>([]);
  manualKeys = signal<Set<string>>(new Set());
  selected = signal<number | null>(null);
  playing = signal(false);
  pps = signal(100);              // zoom: pixels per second
  follow = true;
  status = signal('');
  highlight = signal<{ x: number; y: number; w: number; h: number } | null>(null);

  totalPx = computed(() => Math.ceil(this.duration * this.pps()));
  timeLabel = signal('0:00.0');
  syncing = signal(false);
  manualCount = computed(() => this.anchors().filter((a) => this.manualKeys().has(a[0].toFixed(4))).length);

  private atHost = viewChild.required<ElementRef<HTMLDivElement>>('atHost');
  private atWrap = viewChild.required<ElementRef<HTMLDivElement>>('atWrap');
  private tabScroll = viewChild.required<ElementRef<HTMLDivElement>>('tabScroll');
  private waveScroll = viewChild.required<ElementRef<HTMLDivElement>>('waveScroll');
  private waveCanvas = viewChild.required<ElementRef<HTMLCanvasElement>>('waveCanvas');
  private playheadEl = viewChild.required<ElementRef<HTMLDivElement>>('playhead');
  private tabCursorEl = viewChild.required<ElementRef<HTMLDivElement>>('tabCursor');

  private at?: alphaTab.AlphaTabApi;
  private beatSpots: BeatSpot[] = [];
  private barRects: { x: number; w: number }[] = [];

  private ctx?: AudioContext;
  private buffer?: AudioBuffer;
  private source?: AudioBufferSourceNode;
  private startCtxTime = 0;
  private startPos = 0;
  private pausedPos = 0;
  private raf = 0;
  private saveTimer = 0;
  private syncPollTimer = 0;
  private drag: { idx: number; moved: boolean } | null = null;
  undoCount = signal(0);
  private undoStack: { anchors: [number, number][]; manual: string[] }[] = [];
  private lastNudge = { idx: -1, at: 0 };

  get duration() { return this.buffer?.duration ?? 0; }

  ngOnInit() {
    const tabId = Number(this.route.snapshot.paramMap.get('tabId'));
    this.api.getTab(tabId).subscribe((tab) => {
      this.tab.set(tab);
      const t = tab.timing;
      this.anchors.set((t?.anchors ?? []).map(([n, a]) => [n, a] as [number, number]));
      this.manualKeys.set(new Set((t?.manual ?? []).map(([n]) => n.toFixed(4))));
      this.api.song(tab.track_id).subscribe(async (song) => {
        const stem = song.stems.find((s) => s.id === tab.stem_id) ?? song.stems.find((s) => s.name === 'guitar');
        if (!stem) { this.status.set('No stem'); return; }
        const resp = await fetch(this.api.fileUrl(tab.track_id, stem.name));
        this.ctx = new AudioContext();
        this.buffer = await this.ctx.decodeAudioData(await resp.arrayBuffer());
        this.drawWave();
      });
      if (tab.alphatex) this.renderTab(tab.alphatex);
    });
    window.addEventListener('keydown', this.onKey);
  }

  ngOnDestroy() {
    cancelAnimationFrame(this.raf);
    clearTimeout(this.saveTimer);
    clearTimeout(this.syncPollTimer);
    window.removeEventListener('keydown', this.onKey);
    this.stopSource();
    this.ctx?.close();
    this.at?.destroy();
  }

  // ---------------------------------------------------------------- tab strip
  private renderTab(tex: string) {
    this.at = new alphaTab.AlphaTabApi(this.atHost().nativeElement, {
      // includeNoteBounds forces bounds collection with the player disabled — the
      // note<->anchor linking is built entirely from the bounds lookup.
      core: { fontDirectory: '/alphatab/font/', useWorkers: false, includeNoteBounds: true },
      display: { layoutMode: alphaTab.LayoutMode.Horizontal, scale: 0.85 },
      player: { playerMode: alphaTab.PlayerMode.Disabled },
    } as any);
    this.at.renderFinished.on(() => setTimeout(() => this.indexBeats(), 50));
    this.at.tex(tex);
  }

  /** Flatten alphaTab's bounds lookup into clickable beat spots with notated times. */
  private indexBeats() {
    const lookup = (this.at as any)?.renderer?.boundsLookup;
    if (!lookup) return;
    const bars = this.notatedBars();
    this.beatSpots = [];
    this.barRects = [];
    (window as any).timingDebug = () => ({
      beats: this.beatSpots.length,
      bars: this.barRects.length,
    });
    for (const sg of lookup.staffSystems ?? lookup.staveGroups ?? []) {
      for (const mb of sg.bars ?? []) {
        const barIdx = mb.index as number;
        const rect = mb.realBounds;
        this.barRects[barIdx] = { x: rect.x, w: rect.w };
        const barStart = bars[barIdx] ?? 0;
        const barDur = (bars[barIdx + 1] ?? barStart + 2) - barStart;
        for (const bb of mb.bars ?? []) {
          for (const beat of bb.beats ?? []) {
            const b = beat.beat;
            let frac = (beat.realBounds.x - rect.x) / Math.max(rect.w, 1);
            try {
              const mbStart = b.voice.bar.masterBar.start;
              const mbDur = b.voice.bar.masterBar.calculateDuration();
              if (mbDur > 0) frac = (b.absolutePlaybackStart - mbStart) / mbDur;
            } catch { /* visual fallback stands */ }
            this.beatSpots.push({
              x: beat.realBounds.x, y: beat.realBounds.y,
              w: Math.max(beat.realBounds.w, 14), h: Math.max(beat.realBounds.h, 30),
              bar: barIdx, notated: barStart + frac * barDur,
            });
          }
        }
      }
    }
  }

  onTabClick(ev: MouseEvent) {
    if (!this.beatSpots.length) return;
    const wrap = this.atWrap().nativeElement.getBoundingClientRect();
    const x = ev.clientX - wrap.left;
    const y = ev.clientY - wrap.top;
    let best: BeatSpot | null = null;
    let bestD = 40;
    for (const s of this.beatSpots) {
      if (y < s.y - 20 || y > s.y + s.h + 20) continue;
      const d = Math.abs(x - s.x);
      if (d < bestD) { bestD = d; best = s; }
    }
    if (!best) return;
    // An existing anchor near this note (±0.3s notated)? Select it — else create one
    // at the current warp position so it starts in place and can be nudged by ear.
    const idx = this.nearestAnchorByNotated(best.notated, 0.3);
    if (idx != null) {
      this.select(idx);
    } else {
      if (this.locked()) return;
      this.pushUndo();
      const audio = this.notatedToAudio(best.notated);
      const list = [...this.anchors(), [best.notated, audio] as [number, number]]
        .sort((p, q) => p[0] - q[0]);
      this.markManual(best.notated);
      this.anchors.set(list);
      this.select(list.findIndex(([n]) => n === best.notated));
      this.queueSave();
    }
    this.showHighlight(best);
    this.scrollWaveTo(this.anchors()[this.selected()!][1]);
  }

  private showHighlight(s: BeatSpot) {
    this.highlight.set({ x: s.x - 4, y: s.y - 6, w: s.w + 8, h: s.h + 12 });
  }

  // ---------------------------------------------------------------- guided re-sync
  /** Re-run the automatic sync: the engine re-aligns the whole stem (all sibling
   *  parts) with the saved manual anchors as its prior, then the fresh warp is
   *  loaded back in. Editing is locked while it runs — a save mid-sync would race
   *  the engine's write. */
  resync() {
    const tab = this.tab();
    if (!tab || this.syncing()) return;
    clearTimeout(this.saveTimer);       // any pending edit is already in `manual`; flush would race
    const before = tab.timing?.synced_at ?? null;
    this.syncing.set(true);
    this.status.set('Re-syncing…');
    const manual = this.anchors().filter((a) => this.isManual(a));
    // Persist the current hand edits first so the engine sees them as guides.
    this.api.updateTabTiming(tab.id, manual).subscribe({
      next: () => this.api.syncTab(tab.id).subscribe({
        next: () => this.pollSync(before, performance.now()),
        error: () => { this.syncing.set(false); this.status.set('Sync failed'); },
      }),
      error: () => { this.syncing.set(false); this.status.set('Save failed'); },
    });
  }

  private pollSync(before: number | null, started: number) {
    this.syncPollTimer = window.setTimeout(() => {
      this.api.getTab(this.tab()!.id).subscribe((tab) => {
        const stamp = tab.timing?.synced_at ?? null;
        if (stamp != null && stamp !== before) {
          this.tab.set(tab);
          this.anchors.set((tab.timing?.anchors ?? []).map(([n, a]) => [n, a] as [number, number]));
          this.manualKeys.set(new Set((tab.timing?.manual ?? []).map(([n]) => n.toFixed(4))));
          this.undoStack = [];          // old snapshots refer to the replaced engine anchors
          this.undoCount.set(0);
          this.select(null);
          this.syncing.set(false);
          this.status.set('Re-synced ✓');
          this.drawWave();
        } else if (performance.now() - started > 8 * 60_000) {
          this.syncing.set(false);
          this.status.set('Sync timed out — check the server log');
        } else {
          this.status.set(`Re-syncing… ${Math.round((performance.now() - started) / 1000)}s`);
          this.pollSync(before, started);
        }
      });
    }, 2500);
  }

  /** True (with a status nudge) while a re-sync locks out anchor edits. */
  private locked(): boolean {
    if (this.syncing()) this.status.set('re-sync running…');
    return this.syncing();
  }

  // ---------------------------------------------------------------- anchors
  /** Snapshot the anchor state before a mutation, for Ctrl+Z / the Undo button. */
  private pushUndo() {
    this.undoStack.push({
      anchors: this.anchors().map((a) => [...a] as [number, number]),
      manual: [...this.manualKeys()],
    });
    if (this.undoStack.length > 50) this.undoStack.shift();
    this.undoCount.set(this.undoStack.length);
  }

  undo() {
    if (this.locked()) return;
    const s = this.undoStack.pop();
    if (!s) return;
    this.undoCount.set(this.undoStack.length);
    this.anchors.set(s.anchors);
    this.manualKeys.set(new Set(s.manual));
    this.select(null);
    this.drawWave();
    this.queueSave();
  }

  isManual(a: [number, number]) { return this.manualKeys().has(a[0].toFixed(4)); }
  private markManual(notated: number) {
    const keys = new Set(this.manualKeys());
    keys.add(notated.toFixed(4));
    this.manualKeys.set(keys);
  }

  private nearestAnchorByNotated(notated: number, tol: number): number | null {
    let best: number | null = null;
    let bestD = tol;
    this.anchors().forEach(([n], i) => {
      const d = Math.abs(n - notated);
      if (d <= bestD) { bestD = d; best = i; }
    });
    return best;
  }

  private select(idx: number | null) {
    this.selected.set(idx);
    if (idx == null) { this.highlight.set(null); return; }
    const [n] = this.anchors()[idx];
    const bars = this.notatedBars();
    let bar = 0;
    while (bar + 1 < bars.length && bars[bar + 1] <= n) bar++;
    let best: BeatSpot | null = null;
    let bestD = Infinity;
    for (const s of this.beatSpots) {
      if (s.bar !== bar) continue;
      const d = Math.abs(s.notated - n);
      if (d < bestD) { bestD = d; best = s; }
    }
    if (best) {
      this.showHighlight(best);
      const scroller = this.tabScroll().nativeElement;
      scroller.scrollTo({ left: Math.max(0, best.x - scroller.clientWidth / 2), behavior: 'smooth' });
    }
  }

  grabAnchor(ev: PointerEvent, idx: number) {
    ev.preventDefault();
    ev.stopPropagation();
    this.select(idx);
    if (this.locked()) return;
    this.drag = { idx, moved: false };
    const move = (e: PointerEvent) => {
      if (!this.drag) return;
      if (!this.drag.moved) this.pushUndo();  // one undo step per drag
      this.drag.moved = true;
      const spacer = this.waveScroll().nativeElement;
      const rect = spacer.getBoundingClientRect();
      const t = (e.clientX - rect.left + spacer.scrollLeft) / this.pps();
      // moving past engine anchors evicts them, shifting the index
      this.drag.idx = this.moveAnchor(this.drag.idx, t);
      this.selected.set(this.drag.idx);
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      if (this.drag?.moved) this.queueSave();
      this.drag = null;
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  }

  /** Move an anchor to `audio` seconds and return its index in the updated list.
   *
   * Only MANUAL anchors are hard walls: on a far-off song the engine anchors in the
   * way are exactly what the user is overriding, so clamping against them made long
   * corrections impossible. Engine anchors the move crosses are evicted instead —
   * the server applies the same rule on save (apply_manual), so the eviction shows
   * the warp the save will produce. */
  private moveAnchor(idx: number, audio: number): number {
    const cur = this.anchors();
    const nt = cur[idx][0];
    let lo = 0;
    let hi = this.duration;
    for (let i = idx - 1; i >= 0; i--) if (this.isManual(cur[i])) { lo = cur[i][1] + 0.05; break; }
    for (let i = idx + 1; i < cur.length; i++) if (this.isManual(cur[i])) { hi = cur[i][1] - 0.05; break; }
    const t = Math.round(Math.min(Math.max(audio, lo), Math.max(lo, hi)) * 1000) / 1000;
    this.markManual(nt);
    const list = cur
      .filter((p, i) => i === idx || this.isManual(p) || (p[0] < nt ? p[1] < t : p[1] > t))
      .map((p) => (p[0] === nt ? [nt, t] as [number, number] : p));
    this.anchors.set(list);
    return list.findIndex((p) => p[0] === nt);
  }

  private onKey = (ev: KeyboardEvent) => {
    if (ev.ctrlKey && ev.key.toLowerCase() === 'z') {
      ev.preventDefault();
      this.undo();
      return;
    }
    if (ev.code === 'Space' && !(ev.target as HTMLElement)?.closest('input')) {
      ev.preventDefault();
      this.togglePlay();
      return;
    }
    if (ev.key === '[' || ev.key === ']') {
      ev.preventDefault();
      this.stepSelection(ev.key === ']' ? 1 : -1);
      return;
    }
    const idx = this.selected();
    if (idx == null) return;
    if (ev.key === 'ArrowLeft' || ev.key === 'ArrowRight') {
      ev.preventDefault();
      if (this.locked()) return;
      // Coalesce a run of nudges on one anchor into a single undo step.
      const now = performance.now();
      if (this.lastNudge.idx !== idx || now - this.lastNudge.at > 800) this.pushUndo();
      this.lastNudge = { idx, at: now };
      const step = (ev.shiftKey ? 0.1 : 0.02) * (ev.key === 'ArrowLeft' ? -1 : 1);
      this.selected.set(this.moveAnchor(idx, this.anchors()[idx][1] + step));
      this.queueSave();
    } else if (ev.key.toLowerCase() === 'a' && !ev.ctrlKey && !ev.altKey && !ev.metaKey) {
      // Slam the selected anchor onto the playhead: listen, pause (or not) at the
      // note's true attack, press A — no dragging across half the song.
      ev.preventDefault();
      if (this.locked()) return;
      this.pushUndo();
      const ni = this.moveAnchor(idx, this.position());
      this.selected.set(ni);
      this.scrollWaveTo(this.anchors()[ni][1]);
      this.queueSave();
    } else if (ev.key === 'Delete' || ev.key === 'Backspace') {
      if (this.locked()) return;
      const a = this.anchors()[idx];
      if (!this.isManual(a)) { this.status.set('engine anchor'); return; }
      this.pushUndo();
      const keys = new Set(this.manualKeys());
      keys.delete(a[0].toFixed(4));
      this.manualKeys.set(keys);
      this.anchors.set(this.anchors().filter((_, i) => i !== idx));
      this.select(null);
      this.queueSave();
    }
  };

  /** Select the previous/next anchor ([ / ]) and bring it into view in both panes;
   *  with nothing selected, start from the anchor nearest the playhead. */
  private stepSelection(dir: 1 | -1) {
    const list = this.anchors();
    if (!list.length) return;
    const cur = this.selected();
    let idx: number;
    if (cur == null) {
      const t = this.position();
      idx = 0;
      for (let i = 1; i < list.length; i++) {
        if (Math.abs(list[i][1] - t) < Math.abs(list[idx][1] - t)) idx = i;
      }
    } else {
      idx = Math.min(list.length - 1, Math.max(0, cur + dir));
    }
    this.select(idx);
    this.scrollWaveTo(list[idx][1]);
  }

  private queueSave() {
    this.status.set('…');
    clearTimeout(this.saveTimer);
    this.saveTimer = window.setTimeout(() => {
      const manual = this.anchors().filter((a) => this.isManual(a));
      this.api.updateTabTiming(this.tab()!.id, manual).subscribe({
        next: (tab) => {
          this.tab.set(tab);
          this.anchors.set((tab.timing?.anchors ?? []).map(([n, a]) => [n, a] as [number, number]));
          this.manualKeys.set(new Set((tab.timing?.manual ?? []).map(([n]) => n.toFixed(4))));
          this.status.set('Saved ✓');
        },
        error: () => this.status.set('Save failed'),
      });
    }, 700);
  }

  // ---------------------------------------------------------------- warp math
  private notatedBars(): number[] {
    const t = this.tab()?.timing;
    if (t?.notated_bars?.length) return t.notated_bars;
    // Older timings lack the notated ruler: reconstruct it by inverse-warping bar_times.
    return (t?.bar_times ?? []).map((bt) => this.audioToNotated(bt));
  }

  private notatedToAudio(n: number): number {
    const a = this.anchors();
    if (a.length < 2) return n;
    if (n <= a[0][0]) return a[0][1] - (a[0][0] - n);
    const last = a[a.length - 1];
    if (n >= last[0]) return last[1] + (n - last[0]);
    for (let k = 1; k < a.length; k++) {
      if (n <= a[k][0]) {
        const [n0, a0] = a[k - 1];
        const [n1, a1] = a[k];
        const f = n1 > n0 ? (n - n0) / (n1 - n0) : 0;
        return a0 + f * (a1 - a0);
      }
    }
    return last[1];
  }

  private audioToNotated(t: number): number {
    const a = this.anchors();
    if (a.length < 2) return t;
    if (t <= a[0][1]) return a[0][0] - (a[0][1] - t);
    const last = a[a.length - 1];
    if (t >= last[1]) return last[0] + (t - last[1]);
    for (let k = 1; k < a.length; k++) {
      if (t <= a[k][1]) {
        const [n0, a0] = a[k - 1];
        const [n1, a1] = a[k];
        const f = a1 > a0 ? (t - a0) / (a1 - a0) : 0;
        return n0 + f * (n1 - n0);
      }
    }
    return last[0];
  }

  // ---------------------------------------------------------------- waveform
  setZoom(v: number) {
    const scroller = this.waveScroll().nativeElement;
    const centreT = (scroller.scrollLeft + scroller.clientWidth / 2) / this.pps();
    this.pps.set(v);
    queueMicrotask(() => {
      scroller.scrollLeft = Math.max(0, centreT * v - scroller.clientWidth / 2);
      this.drawWave();
    });
  }

  drawWave() {
    const cv = this.waveCanvas().nativeElement;
    const scroller = this.waveScroll().nativeElement;
    if (!this.buffer) return;
    const w = scroller.clientWidth;
    const h = scroller.clientHeight;
    const dpr = window.devicePixelRatio || 1;
    if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.style.width = `${w}px`; }
    if (cv.height !== Math.round(h * dpr)) { cv.height = Math.round(h * dpr); cv.style.height = `${h}px`; }
    const g = cv.getContext('2d')!;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    const pps = this.pps();
    const t0 = scroller.scrollLeft / pps;
    const data = this.buffer.getChannelData(0);
    const sr = this.buffer.sampleRate;
    const mid = h / 2;
    g.fillStyle = '#5f7fe8';
    for (let x = 0; x < w; x++) {
      const s0 = Math.floor((t0 + x / pps) * sr);
      const s1 = Math.floor((t0 + (x + 1) / pps) * sr);
      let mn = 0, mx = 0;
      for (let s = Math.max(0, s0); s < Math.min(data.length, s1); s += 1) {
        const v = data[s];
        if (v > mx) mx = v;
        if (v < mn) mn = v;
      }
      g.fillRect(x, mid + mn * (mid - 2), 1, Math.max(1, (mx - mn) * (mid - 2)));
    }
    // bar ruler from the LIVE warp so edits are visible immediately
    g.fillStyle = 'rgba(255,255,255,0.14)';
    const bars = this.notatedBars();
    for (let i = 0; i < bars.length; i++) {
      const t = this.notatedToAudio(bars[i]);
      if (t < t0 - 1 || t > t0 + w / pps + 1) continue;
      g.fillRect((t - t0) * pps, 0, 1, h);
      g.fillStyle = 'rgba(255,255,255,0.45)';
      g.fillText(String(i + 1), (t - t0) * pps + 3, 12);
      g.fillStyle = 'rgba(255,255,255,0.14)';
    }
  }

  private scrollWaveTo(t: number) {
    const scroller = this.waveScroll().nativeElement;
    const x = t * this.pps();
    if (x < scroller.scrollLeft + 40 || x > scroller.scrollLeft + scroller.clientWidth - 40) {
      scroller.scrollLeft = Math.max(0, x - scroller.clientWidth / 2);
      this.drawWave();
    }
  }

  onWaveDown(ev: PointerEvent) {
    if ((ev.target as HTMLElement).closest('.anchor')) return;
    const spacer = this.waveScroll().nativeElement;
    const rect = spacer.getBoundingClientRect();
    const t = (ev.clientX - rect.left + spacer.scrollLeft) / this.pps();
    this.seek(Math.max(0, Math.min(t, this.duration)));
  }

  // ---------------------------------------------------------------- playback
  position(): number {
    if (!this.ctx) return 0;
    return this.playing()
      ? this.startPos + (this.ctx.currentTime - this.startCtxTime)
      : this.pausedPos;
  }

  togglePlay() {
    if (!this.buffer || !this.ctx) return;
    if (this.playing()) {
      this.pausedPos = this.position();
      this.stopSource();
      this.playing.set(false);
    } else {
      this.startAt(this.pausedPos);
    }
  }

  private seek(t: number) {
    this.pausedPos = t;
    if (this.playing()) this.startAt(t);
    else this.tick();
  }

  private startAt(t: number) {
    this.stopSource();
    this.source = this.ctx!.createBufferSource();
    this.source.buffer = this.buffer!;
    this.source.connect(this.ctx!.destination);
    this.source.onended = () => { if (this.playing() && this.position() >= this.duration - 0.1) this.playing.set(false); };
    this.source.start(0, Math.max(0, t));
    this.startCtxTime = this.ctx!.currentTime;
    this.startPos = t;
    this.playing.set(true);
    this.loop();
  }

  private stopSource() {
    try { this.source?.stop(); } catch { /* not started */ }
    this.source?.disconnect();
    this.source = undefined;
  }

  private loop = () => {
    cancelAnimationFrame(this.raf);
    this.tick();
    if (this.playing()) this.raf = requestAnimationFrame(this.loop);
  };

  /** Move both playheads (waveform + tab strip) to the current position. */
  private tick() {
    const t = this.position();
    this.timeLabel.set(`${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, '0')}`);
    this.playheadEl().nativeElement.style.left = `${t * this.pps()}px`;
    if (this.playing() && this.follow) {
      const scroller = this.waveScroll().nativeElement;
      const x = t * this.pps();
      if (x > scroller.scrollLeft + scroller.clientWidth * 0.8 || x < scroller.scrollLeft) {
        scroller.scrollLeft = Math.max(0, x - scroller.clientWidth * 0.2);
        this.drawWave();
      }
    }
    // tab-strip cursor via the live warp
    const bars = this.notatedBars();
    const n = this.audioToNotated(t);
    let bar = 0;
    while (bar + 1 < bars.length && bars[bar + 1] <= n) bar++;
    const rect = this.barRects[bar];
    const cursor = this.tabCursorEl().nativeElement;
    if (rect) {
      const barDur = (bars[bar + 1] ?? bars[bar] + 2) - bars[bar];
      const frac = Math.min(1, Math.max(0, (n - bars[bar]) / Math.max(barDur, 0.01)));
      cursor.style.display = 'block';
      cursor.style.left = `${rect.x + frac * rect.w}px`;
      if (this.playing() && this.follow) {
        const scroller = this.tabScroll().nativeElement;
        const x = rect.x + frac * rect.w;
        if (x > scroller.scrollLeft + scroller.clientWidth * 0.85 || x < scroller.scrollLeft) {
          scroller.scrollLeft = Math.max(0, x - scroller.clientWidth * 0.2);
        }
      }
    } else {
      cursor.style.display = 'none';
    }
  }
}
