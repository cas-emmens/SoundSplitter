import { Component, ElementRef, OnDestroy, OnInit, computed, inject, signal, viewChild } from '@angular/core';
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
export class TabsPage implements OnInit, OnDestroy {
  private api = inject(Api);
  private route = inject(ActivatedRoute);
  private mix = inject(MultitrackPlayer);

  private atHost = viewChild.required<ElementRef<HTMLDivElement>>('atHost');
  private scrollHost = viewChild.required<ElementRef<HTMLDivElement>>('scrollHost');

  song = signal<SongDetail | null>(null);
  tabs = signal<Tab[]>([]);
  selectedId = signal<number | null>(null);
  selected = computed(() => this.tabs().find((t) => t.id === this.selectedId()) ?? null);
  stems = signal<StemRow[]>([]);
  status = signal('');
  playing = signal(false);
  mixerReady = signal(false);
  trackId = '';

  private at?: alphaTab.AlphaTabApi;
  private raf = 0;

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

  ngOnDestroy() {
    cancelAnimationFrame(this.raf);
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
    const tab = this.selected();
    if (!tab?.alphatex) return;
    this.mix.seek(0);
    this.playing.set(false);
    this.ensureAlphaTab();
    try { this.at!.tex(tab.alphatex); this.status.set(''); }
    catch { this.status.set('Could not render this tab.'); }
  }

  private ensureAlphaTab() {
    if (this.at) return;
    this.at = new alphaTab.AlphaTabApi(this.atHost().nativeElement, {
      core: { fontDirectory: '/alphatab/font/', useWorkers: false },
      display: { layoutMode: alphaTab.LayoutMode.Page, scale: 0.9 },
      player: {
        playerMode: alphaTab.PlayerMode.EnabledExternalMedia,
        enableCursor: true,
        enableAnimatedBeatCursor: true,
        scrollMode: alphaTab.ScrollMode.Off,   // we autoscroll ourselves
      },
    });
    this.attachExternalMedia();
  }

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
      output.updatePosition(this.mix.position() * 1000);
      this.autoScroll();
      this.raf = requestAnimationFrame(this.loop);
    } else {
      this.playing.set(false);
    }
  };

  private autoScroll() {
    const scroller = this.scrollHost().nativeElement;
    const cursor = this.atHost().nativeElement.querySelector('.at-cursor-bar') as HTMLElement | null;
    if (!cursor) return;
    const cRect = cursor.getBoundingClientRect();
    const sRect = scroller.getBoundingClientRect();
    const yInView = cRect.top - sRect.top;
    if (yInView < 0 || yInView > sRect.height * 0.75) {
      scroller.scrollTop += yInView - sRect.height * 0.30;
    }
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
