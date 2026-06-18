import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api, CaptureStatus, NowPlaying, SearchResult } from '../../services/api';

@Component({
  selector: 'app-capture',
  imports: [FormsModule],
  templateUrl: './capture.html',
  styleUrl: './capture.css',
})
export class CapturePage implements OnInit, OnDestroy {
  private api = inject(Api);
  status = signal<CaptureStatus | null>(null);
  nowPlaying = signal<NowPlaying | null>(null);
  queueCount = signal(0);
  busy = signal(false);

  query = signal('');
  results = signal<SearchResult[]>([]);
  searching = signal(false);
  recordError = signal<string | null>(null);

  // A recording is locked-in once a track is requested or actively capturing.
  recording = computed(() => {
    const s = this.status();
    return !!(s?.requested_track || s?.capturing_track);
  });

  private timer?: any;

  ngOnInit() {
    this.poll();
    this.timer = setInterval(() => this.poll(), 2000);
  }
  ngOnDestroy() { clearInterval(this.timer); }

  poll() {
    this.api.captureStatus().subscribe((s) => this.status.set(s));
    this.api.nowPlaying().subscribe((n) => this.nowPlaying.set(n));
    this.api.jobs().subscribe((j) => this.queueCount.set((j.current ? 1 : 0) + j.queued.length));
  }

  connectSpotify() { window.location.href = this.api.spotifyLoginUrl(); }

  dismissFailed(id: number) {
    this.api.dismissFailedCapture(id).subscribe((s) => this.status.set(s));
  }

  search() {
    const q = this.query().trim();
    if (!q) return;
    this.searching.set(true);
    this.recordError.set(null);
    this.api.searchTracks(q).subscribe({
      next: (r) => { this.results.set(r.results); this.searching.set(false); },
      error: () => { this.searching.set(false); },
    });
  }

  record(r: SearchResult) {
    if (this.recording()) return;
    this.recordError.set(null);
    this.busy.set(true);
    this.api.recordTrack(r).subscribe({
      next: (s) => { this.status.set(s); this.results.set([]); this.query.set(''); this.busy.set(false); },
      error: (e) => { this.recordError.set(e?.error?.detail || 'Could not start recording.'); this.busy.set(false); },
    });
  }

  stopRecording() {
    this.busy.set(true);
    this.api.spotifyPause().subscribe({
      next: (s) => { this.status.set(s); this.busy.set(false); },
      error: () => this.busy.set(false),
    });
  }

  toggleCapture() {
    this.busy.set(true);
    const call = this.status()?.armed ? this.api.captureStop() : this.api.captureStart();
    call.subscribe({
      next: (s) => { this.status.set(s); this.busy.set(false); },
      error: () => this.busy.set(false),
    });
  }

  fmtDur(ms?: number): string {
    if (!ms) return '';
    const s = Math.round(ms / 1000);
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  }

  progressPct(): number {
    const n = this.nowPlaying();
    if (!n?.duration_ms || !n.progress_ms) return 0;
    return Math.min(100, (n.progress_ms / n.duration_ms) * 100);
  }
}
