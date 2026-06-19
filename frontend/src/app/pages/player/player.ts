import { Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { Api, SongDetail, Stem } from '../../services/api';
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
  imports: [RouterLink, StemWaveform],
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

  fmt(sec: number): string {
    if (!isFinite(sec) || sec < 0) sec = 0;
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
  }
  pretty(name: string) { return name.charAt(0).toUpperCase() + name.slice(1); }
}
