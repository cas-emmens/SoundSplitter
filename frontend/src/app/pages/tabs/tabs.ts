import { AfterViewInit, Component, ElementRef, OnDestroy, OnInit, computed, effect, inject, signal, untracked, viewChild } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import * as alphaTab from '@coderline/alphatab';
import { Api, SongDetail, Tab } from '../../services/api';
import { MultitrackPlayer } from '../../services/multitrack-player';

interface StemRow { name: string; muted: boolean; focused: boolean; }

@Component({
  selector: 'app-tabs',
  imports: [RouterLink, FormsModule],
  templateUrl: './tabs.html',
  styleUrl: './tabs.css',
})
export class TabsPage implements OnInit, AfterViewInit, OnDestroy {
  private api = inject(Api);
  private route = inject(ActivatedRoute);
  private mix = inject(MultitrackPlayer);

  private atHost = viewChild<ElementRef<HTMLDivElement>>('atHost');
  private scrollHost = viewChild.required<ElementRef<HTMLDivElement>>('scrollHost');

  song = signal<SongDetail | null>(null);
  tabs = signal<Tab[]>([]);
  selectedId = signal<number | null>(null);
  selected = computed(() => this.tabs().find((t) => t.id === this.selectedId()) ?? null);
  stems = signal<StemRow[]>([]);
  status = signal('');
  playing = signal(false);
  mixerReady = signal(false);
  editing = signal(false);
  draft = signal('');       // editable alphaTex while in edit mode
  saving = signal(false);
  trackId = '';

  private at?: alphaTab.AlphaTabApi;
  private raf = 0;

  constructor() {
    // The score host lives inside an `@if (tabs().length)` block, so it does NOT exist yet when
    // ngAfterViewInit fires (tabs load async, after first paint). Creating alphaTab there read a
    // required viewChild that wasn't in the DOM and threw, so the api was never built and the
    // score stayed blank forever — no tab-switch could recover it. An effect instead runs after
    // change detection: it builds alphaTab the moment the host appears, and re-renders whenever
    // the selected tab changes. (Reads `atHost()` + `selected()` so it re-fires on both.)
    effect(() => {
      const host = this.atHost();
      if (!host) return;
      this.ensureAlphaTab(host.nativeElement);
      this.renderSelected();
    });
  }

  ngOnInit() {
    this.trackId = this.route.snapshot.paramMap.get('id') || '';
    this.api.song(this.trackId).subscribe((s) => {
      this.song.set(s);
      this.loadMixer(s);
    });
    this.api.listTabs(this.trackId).subscribe((r) => {
      const done = r.tabs.filter((t) => t.status === 'done' && t.alphatex);
      this.tabs.set(done);
      if (done.length) this.selectTab(done[0].id);
    });
  }

  ngAfterViewInit() {
    // alphaTab creation/render is handled by the constructor effect (the host is behind an @if
    // and isn't in the DOM yet here); we only need the resize listener for responsive bars-per-row.
    window.addEventListener('resize', this.onResize);
  }

  ngOnDestroy() {
    cancelAnimationFrame(this.raf);
    clearTimeout(this.resizeTimer);
    window.removeEventListener('resize', this.onResize);
    this.mix.stop();
    this.at?.destroy();
  }

  /** Load every audio stem into the mixer — all on by default. */
  private async loadMixer(s: SongDetail) {
    const specs = s.stems.map((st) => ({
      name: st.name,
      url: this.api.fileUrl(this.trackId, st.name),
      offsetMs: st.offset_ms,
      trimStartMs: st.trim_start_ms,
      trimEndMs: st.trim_end_ms,
    }));
    if (!specs.length) return;
    await this.mix.load(specs);
    this.syncStems();
    this.mixerReady.set(true);
  }

  selectTab(id: number) {
    this.selectedId.set(id);
    this.mix.seek(0);
    this.playing.set(false);
    // The effect re-renders when `selected()` changes — no direct render call needed here.
  }

  /** Render the selected tab — or the live draft while editing. No-op until alphaTab + a tab are
   *  ready. `draft` is read untracked so the effect doesn't re-render on every keystroke (the
   *  editor debounces its own live preview); the effect still re-fires on selection/edit toggle. */
  private renderSelected() {
    const src = this.editing() ? untracked(() => this.draft()) : this.selected()?.alphatex;
    if (!this.at || !src) return;
    try {
      this.at.tex(src);
      // Re-apply layout once the host has its real width (it may be mid-layout on first paint):
      // recomputes bars-per-row from the container width and re-renders, so bars aren't tiny.
      requestAnimationFrame(() => this.applyLayout());
      this.status.set('');
    } catch {
      this.status.set('Could not render this tab.');
    }
  }

  // --- audio cross-check hints ---
  private dismissed = signal<Set<number>>(new Set());
  /** High-precision missing-note flags from the audio cross-check, formatted for the editor. */
  hints = computed(() => {
    const miss = this.selected()?.timing?.missing ?? [];
    const dis = this.dismissed();
    return miss
      .map((m, i) => ({
        i,
        bar: m.bar + 1,  // display 1-based to match the printed bar numbers
        label: m.midi.map((p) => this.noteName(p)).join('+'),
        token: this.midiToFret(m.midi[0]),
        rawBar: m.bar,
      }))
      .filter((h) => !dis.has(h.i));
  });
  private noteName(midi: number) {
    const N = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
    return `${N[midi % 12]}${Math.floor(midi / 12) - 1}`;
  }
  /** Best-guess fret.string for a pitch (lowest fret ≤15); the user can adjust in the text. */
  private midiToFret(midi: number) {
    const open = [0, 64, 59, 55, 50, 45, 40];  // index = string number (1..6)
    let best: { s: number; f: number } | null = null;
    for (let s = 1; s <= 6; s++) {
      const f = midi - open[s];
      if (f >= 0 && f <= 15 && (best === null || f < best.f)) best = { s, f };
    }
    return best ? `${best.f}.${best.s}` : '';
  }
  applyHint(h: { i: number; rawBar: number; token: string }) {
    if (!h.token) return;
    const lines = this.draft().split('\n');
    const sep = lines.findIndex((l) => l.trim() === '.');
    const head = sep >= 0 ? lines.slice(0, sep + 1) : [];
    const segs = (sep >= 0 ? lines.slice(sep + 1) : lines).join('\n').split('|');
    const idx = Math.min(Math.max(h.rawBar, 0), segs.length - 1);
    const ts = segs[idx].match(/^(\s*\\ts\s+\d+\s+\d+\s+)/);  // keep a leading time signature first
    segs[idx] = ts
      ? ts[1] + h.token + ' ' + segs[idx].slice(ts[1].length)
      : segs[idx].replace(/^(\s*)/, `$1${h.token} `);
    this.onDraft([...head, segs.join('|')].join('\n'));
    this.dismissHint(h.i);
  }
  dismissHint(i: number) {
    this.dismissed.update((s) => new Set(s).add(i));
  }

  // --- editor ---
  startEdit() {
    this.draft.set(this.selected()?.alphatex ?? '');
    this.dismissed.set(new Set());
    this.editing.set(true);  // the effect re-renders from the draft
  }
  cancelEdit() {
    this.editing.set(false);  // the effect re-renders the saved tab
  }
  private editTimer = 0;
  onDraft(value: string) {
    this.draft.set(value);
    // Debounced live preview: re-render the draft a beat after typing stops.
    clearTimeout(this.editTimer);
    this.editTimer = window.setTimeout(() => this.renderSelected(), 400);
  }
  saveEdit() {
    const id = this.selectedId();
    if (id == null) return;
    const alphatex = this.draft();
    this.saving.set(true);
    this.api.updateTab(id, alphatex).subscribe({
      next: (updated) => {
        this.tabs.update((ts) =>
          ts.map((t) => (t.id === id ? { ...t, alphatex: updated.alphatex, timing: updated.timing } : t)));
        this.saving.set(false);
        this.editing.set(false);
      },
      error: () => { this.saving.set(false); this.status.set('Save failed.'); },
    });
  }

  private ensureAlphaTab(host: HTMLDivElement) {
    if (this.at) return;
    this.at = new alphaTab.AlphaTabApi(host, {
      core: { fontDirectory: '/alphatab/font/', useWorkers: false },
      display: { layoutMode: alphaTab.LayoutMode.Page, scale: 1.0, barsPerRow: this.barsPerRow() },
      player: {
        playerMode: alphaTab.PlayerMode.EnabledExternalMedia,
        enableCursor: true,
        enableAnimatedBeatCursor: true,
        scrollMode: alphaTab.ScrollMode.Off,   // we autoscroll ourselves
      },
    });
    this.attachExternalMedia();
  }

  /** Bars per line from the SCORE CONTAINER's real width (not the window — the score area is
   *  much narrower than the window because of the page layout + stem sidebar). ~320px/bar reads
   *  comfortably. Capped at 4: songs are usually 4-bar phrases, so a 4-bar row reads far better
   *  than 5 even when there's room for more. Falls back to a sane default before layout (width 0). */
  private barsPerRow() {
    const w = this.atHost()?.nativeElement.clientWidth ?? 0;
    if (w < 100) return 4;
    return Math.max(1, Math.min(4, Math.round(w / 320)));
  }

  private applyLayout() {
    if (!this.at) return;
    this.at.settings.display.barsPerRow = this.barsPerRow();
    this.at.updateSettings();
    this.at.render();
  }

  private resizeTimer = 0;
  private onResize = () => {
    clearTimeout(this.resizeTimer);
    this.resizeTimer = window.setTimeout(() => this.applyLayout(), 150);
  };

  /** Drive alphaTab's transport from the multitrack mixer (instead of one <audio>). */
  private attachExternalMedia(retries = 30) {
    const output = this.at?.player?.output as any;
    if (output && 'handler' in output) {
      const mix = this.mix;
      output.handler = {
        get backingTrackDuration() { return mix.duration * 1000; },
        playbackRate: 1,
        masterVolume: 1,
        seekTo: (ms: number) => { mix.seek(ms / 1000); output.updatePosition(ms); },
        play: () => { mix.play(); this.playing.set(true); this.loop(); },
        pause: () => { mix.pause(); this.playing.set(false); },
      };
      return;
    }
    if (retries > 0) setTimeout(() => this.attachExternalMedia(retries - 1), 100);
  }

  private loop = () => {
    cancelAnimationFrame(this.raf);
    const output = this.at?.player?.output as any;
    if (output && this.mix.isPlaying) {
      // Feed alphaTab the NOTATED time (inverse-warped from the recording position) so its bar
      // highlight + autoscroll track the actual recording instead of drifting at the notated tempo.
      output.updatePosition(this.audioToNotated(this.mix.position()) * 1000);
      this.autoScroll();
      this.raf = requestAnimationFrame(this.loop);
    } else {
      this.playing.set(false);
    }
  };

  /** Map a recording time (s) to the tab's notated time (s) via the sync warp anchors, so
   *  alphaTab's own cursor/bar-highlight follows the recording. Identity when no warp exists. */
  private audioToNotated(audioSec: number): number {
    const anchors = this.selected()?.timing?.anchors;
    if (!anchors || anchors.length < 2) return audioSec;
    if (audioSec <= anchors[0][1]) return anchors[0][0];
    const last = anchors[anchors.length - 1];
    if (audioSec >= last[1]) return last[0];
    for (let k = 1; k < anchors.length; k++) {
      const [n0, a0] = anchors[k - 1];
      const [n1, a1] = anchors[k];
      if (audioSec <= a1) {
        const f = a1 > a0 ? (audioSec - a0) / (a1 - a0) : 0;
        return n0 + f * (n1 - n0);
      }
    }
    return last[0];
  }

  private autoScroll() {
    const scroller = this.scrollHost().nativeElement;
    const cursor = this.atHost()?.nativeElement.querySelector('.at-cursor-bar') as HTMLElement | null;
    if (!cursor) return;
    const cRect = cursor.getBoundingClientRect();
    const sRect = scroller.getBoundingClientRect();
    const yInView = cRect.top - sRect.top;
    if (yInView < 0 || yInView > sRect.height * 0.75) {
      scroller.scrollTop += yInView - sRect.height * 0.30;
    }
  }

  deleteTab() {
    const id = this.selectedId();
    if (id == null) return;
    const tab = this.selected();
    if (!confirm(`Delete tab "${tab?.name ?? ''}"? You can re-add it from the player page.`)) return;
    this.api.deleteTab(id).subscribe(() => {
      const remaining = this.tabs().filter((t) => t.id !== id);
      this.tabs.set(remaining);
      // Select the next remaining tab (the effect re-renders); if none left, clear selection.
      if (remaining.length) this.selectTab(remaining[0].id);
      else this.selectedId.set(null);
    });
  }

  togglePlay() { this.at?.playPause(); }
  stop() {
    this.mix.seek(0);
    this.at?.stop();
    this.playing.set(false);
  }

  // --- stem mixer sidecar (mute / focus) ---
  toggleMute(name: string) {
    this.mix.setMuted(name, !this.mix.isMuted(name));
    this.syncStems();
  }
  toggleFocus(name: string) {
    this.mix.toggleSolo(name);
    this.syncStems();
  }
  allOn() {
    this.mix.applyMutePreset([]);
    this.syncStems();
  }
  private syncStems() {
    this.stems.set(this.mix.stemNames.map((name) => ({
      name, muted: this.mix.isMuted(name), focused: this.mix.isSolo(name),
    })));
  }
}
