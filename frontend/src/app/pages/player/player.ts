import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { Api, SongDetail, Stem, Tab } from '../../services/api';
import { MultitrackPlayer } from '../../services/multitrack-player';
import { StemWaveform } from './stem-waveform';

interface StemVM {
  id: number;
  name: string;
  kind: 'model' | 'user';
  offsetMs: number;
  trimStartMs: number;
  trimEndMs: number;
  muted: boolean;
  solo: boolean;
  volume: number;
}

@Component({
  selector: 'app-player',
  imports: [RouterLink, StemWaveform, FormsModule],
  templateUrl: './player.html',
  styleUrl: './player.css',
})
export class PlayerPage implements OnInit, OnDestroy {
  private api = inject(Api);
  private route = inject(ActivatedRoute);
  player = inject(MultitrackPlayer);

  song = signal<SongDetail | null>(null);
  stems = signal<StemVM[]>([]);
  loading = signal(true);
  ready = signal(false);
  pos = signal(0);
  playing = signal(false);
  duration = signal(0);

  // import form
  importName = signal('My take');
  importOffset = signal(0);
  importFile: File | null = null;
  importing = signal(false);

  // export
  exporting = signal(false);
  exportPath = signal<string | null>(null);

  // tabs
  tabs = signal<Tab[]>([]);
  hasTabs = computed(() => this.tabs().some((t) => t.status === 'done'));
  pendingTabs = computed(() => this.tabs().filter((t) => t.status === 'pending'));
  errorTabs = computed(() => this.tabs().filter((t) => t.status === 'error'));
  showTabModal = signal(false);
  tabName = signal('');
  tabUrl = signal('');
  allGuitars = signal(true); // default: one URL -> every guitar part of the song
  tabStemId = signal<number | null>(null);
  creatingTab = signal(false);
  tabError = signal('');

  private raf = 0;
  private trackId = '';

  ngOnInit() {
    this.trackId = this.route.snapshot.paramMap.get('id') || '';
    this.load();
    const tick = () => {
      this.pos.set(this.player.position());
      this.playing.set(this.player.isPlaying);
      if (this.player.isPlaying && this.player.position() >= this.player.duration) {
        this.player.pause();
      }
      this.raf = requestAnimationFrame(tick);
    };
    this.raf = requestAnimationFrame(tick);
  }
  ngOnDestroy() {
    cancelAnimationFrame(this.raf);
    this.player.stop();
  }

  load() {
    this.loading.set(true);
    this.api.song(this.trackId).subscribe(async (s) => {
      this.song.set(s);
      await this.buildPlayer(s);
      this.loading.set(false);
    });
    this.refreshTabs();
  }

  private refreshTabs() {
    this.api.listTabs(this.trackId).subscribe((r) => {
      this.tabs.set(r.tabs);
      // resume polling any still-generating tabs (e.g. after a page reload)
      for (const t of r.tabs) if (t.status === 'pending') this.pollTab(t.id);
    });
  }

  private async buildPlayer(s: SongDetail) {
    this.ready.set(false);
    const specs = s.stems.map((st) => ({
      name: st.name, url: this.api.fileUrl(s.track_id, st.name), offsetMs: st.offset_ms,
      trimStartMs: st.trim_start_ms, trimEndMs: st.trim_end_ms,
    }));
    await this.player.load(specs);
    this.duration.set(this.player.duration);
    this.stems.set(s.stems.map((st) => this.toVM(st)));
    this.ready.set(true);
  }

  private toVM(st: Stem): StemVM {
    return {
      id: st.id, name: st.name, kind: st.kind, offsetMs: st.offset_ms,
      trimStartMs: st.trim_start_ms, trimEndMs: st.trim_end_ms,
      muted: this.player.isMuted(st.name), solo: this.player.isSolo(st.name),
      volume: this.player.getVolume(st.name),
    };
  }

  togglePlay() { this.player.isPlaying ? this.player.pause() : this.player.play(); }
  seek(ev: Event) { this.player.seek(+(ev.target as HTMLInputElement).value); }

  toggleMute(vm: StemVM) {
    this.player.setMuted(vm.name, !vm.muted);
    this.syncVMs();
  }
  toggleSolo(vm: StemVM) {
    this.player.toggleSolo(vm.name);
    this.syncVMs();
  }
  setVolume(vm: StemVM, ev: Event) {
    const v = +(ev.target as HTMLInputElement).value;
    this.player.setVolume(vm.name, v);
    this.syncVMs();
  }
  practiceMode() {
    const mute = this.song()?.practice_mute || [];
    this.player.applyMutePreset(mute);
    this.syncVMs();
  }
  private syncVMs() {
    this.stems.update((list) => list.map((vm) => ({
      ...vm,
      muted: this.player.isMuted(vm.name),
      solo: this.player.isSolo(vm.name),
      volume: this.player.getVolume(vm.name),
    })));
  }

  // --- user stem management ---
  onFile(ev: Event) {
    const f = (ev.target as HTMLInputElement).files?.[0];
    this.importFile = f || null;
  }
  doImport() {
    if (!this.importFile) return;
    this.importing.set(true);
    this.api.importStem(this.trackId, this.importFile, this.importName(), this.importOffset())
      .subscribe({
        next: () => { this.importing.set(false); this.importFile = null; this.load(); },
        error: () => this.importing.set(false),
      });
  }
  deleteStem(vm: StemVM) {
    if (vm.kind !== 'user') return;
    this.api.deleteStem(vm.id).subscribe(() => this.load());
  }
  updateOffset(vm: StemVM, ev: Event) {
    const ms = +(ev.target as HTMLInputElement).value;
    this.api.patchStem(vm.id, { offset_ms: ms }).subscribe(() => this.load());
  }

  onTrim(vm: StemVM, e: { startMs: number; endMs: number }) {
    vm.trimStartMs = e.startMs;
    vm.trimEndMs = e.endMs;
    this.duration.set(this.player.setTrim(vm.name, e.startMs, e.endMs));
    this.api.patchStem(vm.id, { trim_start_ms: e.startMs, trim_end_ms: e.endMs }).subscribe();
  }

  exportDaw() {
    this.exporting.set(true);
    this.exportPath.set(null);
    this.api.exportToDaw(this.trackId).subscribe({
      next: (r) => { this.exporting.set(false); this.exportPath.set(r.path); },
      error: () => this.exporting.set(false),
    });
  }

  // --- tabs (generate from a webpage URL) ---
  openTabModal() {
    const stems = this.song()?.stems ?? [];
    // Default to the guitar stem when there is one — that's what tabs follow.
    const guitar = stems.find((st) => /guitar/i.test(st.name));
    this.tabStemId.set(guitar?.id ?? stems[0]?.id ?? null);
    this.tabName.set('');
    this.tabUrl.set('');
    this.tabError.set('');
    this.showTabModal.set(true);
  }
  closeTabModal() { this.showTabModal.set(false); }

  createTab() {
    const url = this.tabUrl().trim();
    if (this.allGuitars()) {
      if (!url) { this.tabError.set('URL is required.'); return; }
      this.creatingTab.set(true);
      this.api.createTabsFromSong(this.trackId, { url, stem_id: this.tabStemId() }).subscribe({
        next: (r) => {
          this.creatingTab.set(false);
          this.showTabModal.set(false);
          this.tabs.update((list) => [...list, ...r.tabs]);
          for (const tab of r.tabs) this.pollTab(tab.id);
        },
        error: (e) => {
          this.creatingTab.set(false);
          this.tabError.set(e?.error?.detail || 'Could not read the song\'s track list.');
        },
      });
      return;
    }
    const name = this.tabName().trim();
    if (!name || !url) { this.tabError.set('Name and URL are required.'); return; }
    this.creatingTab.set(true);
    this.api.createTab(this.trackId, { name, url, stem_id: this.tabStemId() }).subscribe({
      next: (tab) => {
        this.creatingTab.set(false);
        this.showTabModal.set(false);
        this.tabs.update((list) => [...list, tab]);
        this.pollTab(tab.id);
      },
      error: (e) => {
        this.creatingTab.set(false);
        this.tabError.set(e?.error?.detail || 'Could not start tab generation.');
      },
    });
  }

  private pollTab(id: number) {
    const iv = setInterval(() => {
      this.api.getTab(id).subscribe((t) => {
        this.tabs.update((list) => list.map((x) => (x.id === id ? t : x)));
        if (t.status !== 'pending') clearInterval(iv);
      });
    }, 3000);
  }

  fmt(sec: number): string {
    if (!isFinite(sec) || sec < 0) sec = 0;
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
  }
  pretty(name: string) { return name.charAt(0).toUpperCase() + name.slice(1); }
}
