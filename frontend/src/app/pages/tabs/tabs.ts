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
  private atMode?: 'recording' | 'synth';
  private raf = 0;

  // --- playback source: the real recording (warp-synced cursor) or alphaTab's synthesizer
  // (raw tab timing, speed control — for slow practice before trying the real thing) ---
  mode = signal<'recording' | 'synth'>(
    localStorage.getItem('tabs.mode') === 'synth' ? 'synth' : 'recording');
  synthSpeed = signal(Number(localStorage.getItem('tabs.synthSpeed')) || 1);
  synthReady = signal(false);

  setMode(m: 'recording' | 'synth') {
    if (m === this.mode()) return;
    this.stop();  // switching modes restarts the song
    this.mode.set(m);
    localStorage.setItem('tabs.mode', m);
  }

  setSynthSpeed(v: number) {
    this.synthSpeed.set(v);
    localStorage.setItem('tabs.synthSpeed', String(v));
    if (this.at && this.atMode === 'synth') this.at.playbackSpeed = v;
  }

  constructor() {
    // The score host lives inside an `@if (tabs().length)` block, so it does NOT exist yet when
    // ngAfterViewInit fires (tabs load async, after first paint). Creating alphaTab there read a
    // required viewChild that wasn't in the DOM and threw, so the api was never built and the
    // score stayed blank forever — no tab-switch could recover it. An effect instead runs after
    // change detection: it builds alphaTab the moment the host appears, and re-renders whenever
    // the selected tab changes. (Reads `atHost()` + `selected()` so it re-fires on both.)
    effect(() => {
      const host = this.atHost();
      const mode = this.mode();
      if (!host) return;
      if (this.at && this.atMode !== mode) {
        // Mode switch rebuilds the player (external-media vs synthesizer wiring differs
        // at construction); playback deliberately restarts from the top.
        this.at.destroy();
        this.at = undefined;
      }
      this.ensureAlphaTab(host.nativeElement, mode);
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
    // Keep the recording rolling (and the position) across tab switches: swapping from the
    // intro tab to the lead mid-song just re-renders the score and the cursor carries on.
    // The effect re-renders when `selected()` changes; renderSelected() re-arms playback.
    this.selectedId.set(id);
  }

  /** Render the selected tab — or the live draft while editing. No-op until alphaTab + a tab are
   *  ready. `draft` is read untracked so the effect doesn't re-render on every keystroke (the
   *  editor debounces its own live preview); the effect still re-fires on selection/edit toggle. */
  private renderSelected() {
    const src = this.editing() ? untracked(() => this.draft()) : this.selected()?.alphatex;
    if (!this.at || !src) return;
    try {
      // Loading a new score STOPS alphaTab's transport, which pauses/rewinds the mixer
      // through our handler — so capture the state first and suppress those transport
      // commands during the switch; then re-arm so the cursor carries on mid-song.
      // (Recording mode only: the synth has no mixer to carry on with — a tab switch
      // there just stops, like the mode switch does.)
      const wasRolling = this.atMode !== 'synth' && this.mix.isPlaying;
      if (wasRolling) this.suppressTransportUntil = performance.now() + 1000;
      this.at.tex(src);
      // Re-apply layout once the host has its real width (it may be mid-layout on first paint):
      // recomputes bars-per-row from the container width and re-renders, so bars aren't tiny.
      requestAnimationFrame(() => this.applyLayout());
      if (wasRolling) {
        requestAnimationFrame(() => this.at?.play());
      }
      this.status.set('');
    } catch {
      this.status.set('Could not render this tab.');
    }
  }

  private suppressTransportUntil = 0;

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

  private ensureAlphaTab(host: HTMLDivElement, mode: 'recording' | 'synth') {
    if (this.at) return;
    this.atMode = mode;
    const synth = mode === 'synth';
    this.at = new alphaTab.AlphaTabApi(host, {
      core: {
        fontDirectory: '/alphatab/font/',
        scriptFile: '/alphatab/alphaTab.min.js',  // the synth's audio worklet loads this
        useWorkers: false,
      },
      display: { layoutMode: alphaTab.LayoutMode.Page, scale: 1.0, barsPerRow: this.barsPerRow() },
      player: {
        playerMode: synth
          ? alphaTab.PlayerMode.EnabledSynthesizer
          : alphaTab.PlayerMode.EnabledExternalMedia,
        soundFont: synth ? '/alphatab/soundfont/sonivox.sf3' : undefined,
        enableCursor: true,
        enableAnimatedBeatCursor: true,
        scrollMode: alphaTab.ScrollMode.Off,   // we autoscroll ourselves
      },
    });
    if (synth) {
      this.synthReady.set(false);
      this.at.playerReady.on(() => this.synthReady.set(true));
      this.at.playerStateChanged.on((e) =>
        this.playing.set(e.state === alphaTab.synth.PlayerState.Playing));
      this.at.playerPositionChanged.on(() => this.autoScroll());
      this.at.playbackSpeed = this.synthSpeed();
      this.at.countInVolume = this.countIn() ? 1 : 0;  // native count-in (tempo-correct at any speed)
    } else {
      this.attachExternalMedia();
    }
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
        seekTo: (ms: number) => {
          if (performance.now() < this.suppressTransportUntil) {
            // Transport reset from a mid-song tab switch — keep the real position instead.
            output.updatePosition(this.audioToNotated(mix.position()) * 1000);
            return;
          }
          mix.seek(ms / 1000); output.updatePosition(ms);
        },
        play: () => { mix.play(); this.playing.set(true); this.loop(); },
        pause: () => {
          if (performance.now() < this.suppressTransportUntil) return;  // mid-switch reset
          mix.pause(); this.playing.set(false);
        },
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
    // Beyond the anchored region, continue at slope 1 (tempo-exact) instead of clamping:
    // a flat clamp froze the cursor on the last anchored note while the tab's final bars
    // (an unanchorable fast run) played on — and parked it on the first anchor before it.
    if (audioSec <= anchors[0][1]) return anchors[0][0] - (anchors[0][1] - audioSec);
    const last = anchors[anchors.length - 1];
    if (audioSec >= last[1]) return last[0] + (audioSec - last[1]);
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

  // --- count-in: four metronome ticks at the local tempo before the recording starts ---
  countIn = signal(localStorage.getItem('tabs.countIn') !== '0');  // on by default
  countingIn = signal(false);
  private countInTimer = 0;
  private tickCtx?: AudioContext;

  toggleCountIn() {
    this.countIn.update((v) => !v);
    localStorage.setItem('tabs.countIn', this.countIn() ? '1' : '0');
    if (this.at && this.atMode === 'synth') this.at.countInVolume = this.countIn() ? 1 : 0;
  }

  togglePlay() {
    if (this.atMode === 'synth') { this.at?.playPause(); return; }  // count-in is native there
    if (this.countingIn()) { this.cancelCountIn(); return; }
    if (!this.playing() && this.countIn()) { this.startCountIn(); return; }
    this.at?.playPause();
  }

  private cancelCountIn() {
    clearTimeout(this.countInTimer);
    this.countingIn.set(false);
  }

  private startCountIn() {
    const interval = this.beatInterval();
    const ctx = (this.tickCtx ??= new AudioContext());
    ctx.resume();
    this.countingIn.set(true);
    const t0 = ctx.currentTime + 0.05;
    for (let i = 0; i < 4; i++) this.tick(ctx, t0 + i * interval, i === 0);
    this.countInTimer = window.setTimeout(() => {
      this.countingIn.set(false);
      this.at?.playPause();
    }, (0.05 + 4 * interval) * 1000);
  }

  /** One metronome tick: a short pitched blip (the first beat of the count is accented). */
  private tick(ctx: AudioContext, when: number, accent: boolean) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = accent ? 1568 : 1047;  // G6 / C6
    gain.gain.setValueAtTime(accent ? 0.5 : 0.35, when);
    gain.gain.exponentialRampToValueAtTime(0.001, when + 0.08);
    osc.connect(gain).connect(ctx.destination);
    osc.start(when);
    osc.stop(when + 0.1);
  }

  /** Seconds per beat at the CURRENT position — from the sync warp's bar times (real
   *  performance tempo) when available, else the tab's notated tempo, else 120 bpm. */
  private beatInterval(): number {
    const bt = this.selected()?.timing?.bar_times;
    const pos = this.mix.position();
    if (bt && bt.length > 2) {
      let k = bt.findIndex((t: number) => t > pos) - 1;
      if (k < 0) k = pos >= bt[bt.length - 1] ? bt.length - 2 : 0;
      const barSecs = bt[k + 1] - bt[k];
      if (barSecs > 0.5 && barSecs < 12) return barSecs / 4;
    }
    const m = this.selected()?.alphatex?.match(/\\tempo\s+(\d+)/);
    return 60 / (m ? parseInt(m[1], 10) : 120);
  }

  stop() {
    this.cancelCountIn();
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
