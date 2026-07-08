import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';

export interface Stem {
  id: number;
  track_id: string;
  kind: 'model' | 'user';
  name: string;
  gain: number;
  offset_ms: number;
  trim_start_ms: number;
  trim_end_ms: number;
}
export interface Peaks { peaks: number[]; duration: number; }
export interface Song {
  track_id: string;
  title: string;
  artist: string;
  album: string;
  art_url: string;
  duration_ms: number;
  status: 'capturing' | 'queued' | 'separating' | 'done' | 'error';
  error?: string;
  stem_count?: number;
}
export interface SongDetail extends Song {
  stems: Stem[];
  practice_mute: string[];
}
export interface FailedCapture {
  id: number;
  track_id: string;
  title: string;
  artist: string;
  captured_s: number;
  expected_s: number;
  reason: string;
  at: number;
}
export interface SearchResult {
  track_id: string;
  uri: string;
  title: string;
  artist: string;
  album: string;
  art_url: string | null;
  duration_ms: number;
}
export interface CaptureStatus {
  armed: boolean;
  device: string | null;
  capturing_track: string | null;
  requested_track: string | null;
  requested_meta: { title?: string; artist?: string; art_url?: string; duration_ms?: number } | null;
  spotify_authenticated: boolean;
  spotify_configured: boolean;
  error: string | null;
  failed_captures: FailedCapture[];
}
export interface NowPlaying {
  is_playing: boolean;
  track_id: string | null;
  title?: string;
  artist?: string;
  art_url?: string;
  duration_ms?: number;
  progress_ms?: number;
  is_ad?: boolean;
}
export interface Jobs { current: string | null; queued: string[]; }

export interface TabTiming {
  version: number;
  anchors: [number, number][];   // [notated_s, audio_s] confident matches
  bar_times: number[];           // audio start time (s) per bar, in render order
  notated_bars?: number[];       // notated start time (s) per bar (tab-tempo ruler)
  manual?: [number, number][];   // hand-placed anchors (timing editor); survive re-syncs
  synced_at?: number;            // unix stamp of the last engine sync (editor polls this)
  missing: { bar: number; midi: number[]; t: number; amp: number }[];  // audio cross-check hints
}
export interface Tab {
  id: number;
  track_id: string;
  stem_id: number | null;
  name: string;
  source_url: string | null;
  status: 'pending' | 'done' | 'error';
  error: string | null;
  alphatex: string | null;
  timing: TabTiming | null;      // tabsync warp; null until computed in the background
  created_at: number;
}

export interface Progression {
  id: number;
  name: string;
  root_pc: number;          // default key pitch-class (0=C .. 11=B)
  quality: 'major' | 'minor';
  chords: string[];         // roman numerals
  tempo: number;            // default BPM
  created_at: number;
}
export type ProgressionInput = Omit<Progression, 'id' | 'created_at'>;

export interface WikiArticleStub {
  slug: string;
  title: string;
  widget: string | null;       // interactive explorer to embed (or null)
  widget_arg: string | null;   // preset for that explorer
}
export interface WikiCategory { name: string; articles: WikiArticleStub[]; }
export interface WikiArticle extends WikiArticleStub {
  category: string;
  body: string;                // Markdown
}

@Injectable({ providedIn: 'root' })
export class Api {
  private http = inject(HttpClient);
  private base = '/api';

  health() { return this.http.get<any>(`${this.base}/health`); }
  nowPlaying() { return this.http.get<NowPlaying>(`${this.base}/now-playing`); }

  captureStatus() { return this.http.get<CaptureStatus>(`${this.base}/capture/status`); }
  captureStart() { return this.http.post<CaptureStatus>(`${this.base}/capture/start`, {}); }
  captureStop() { return this.http.post<CaptureStatus>(`${this.base}/capture/stop`, {}); }
  captureDevices() { return this.http.get<any>(`${this.base}/capture/devices`); }
  dismissFailedCapture(id: number) { return this.http.delete<CaptureStatus>(`${this.base}/capture/failed/${id}`); }

  searchTracks(q: string) { return this.http.get<{ results: SearchResult[] }>(`${this.base}/spotify/search`, { params: { q } }); }
  spotifyDevices() { return this.http.get<{ devices: any[]; product: string | null }>(`${this.base}/spotify/devices`); }
  recordTrack(r: SearchResult) {
    return this.http.post<CaptureStatus>(`${this.base}/spotify/record`, {
      track_id: r.track_id,
      meta: { title: r.title, artist: r.artist, art_url: r.art_url, duration_ms: r.duration_ms },
    });
  }
  spotifyPause() { return this.http.post<CaptureStatus>(`${this.base}/spotify/pause`, {}); }

  library() { return this.http.get<{ songs: Song[] }>(`${this.base}/library`); }
  song(id: string) { return this.http.get<SongDetail>(`${this.base}/songs/${id}`); }
  deleteSong(id: string) { return this.http.delete<{ ok: boolean }>(`${this.base}/songs/${id}`); }
  jobs() { return this.http.get<Jobs>(`${this.base}/jobs`); }

  importStem(id: string, file: File, name: string, offsetMs: number) {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('name', name);
    fd.append('offset_ms', String(offsetMs));
    return this.http.post<Stem>(`${this.base}/songs/${id}/stems`, fd);
  }
  patchStem(stemId: number, body: Partial<Pick<Stem, 'name' | 'gain' | 'offset_ms' | 'trim_start_ms' | 'trim_end_ms'>>) {
    return this.http.patch<Stem>(`${this.base}/stems/${stemId}`, body);
  }
  exportToDaw(id: string) { return this.http.post<{ path: string }>(`${this.base}/songs/${id}/export`, {}); }
  stemPeaks(trackId: string, stemName: string) {
    return this.http.get<Peaks>(`${this.base}/files/${trackId}/${encodeURIComponent(stemName)}/peaks`);
  }
  deleteStem(stemId: number) { return this.http.delete<any>(`${this.base}/stems/${stemId}`); }

  spotifyLoginUrl() { return `${this.base}/spotify/login`; }
  fileUrl(trackId: string, stemName: string) {
    return `${this.base}/files/${trackId}/${encodeURIComponent(stemName)}.flac`;
  }

  // --- tabs (generated from a webpage URL via the image-tabs library) ---
  listTabs(trackId: string) {
    return this.http.get<{ tabs: Tab[] }>(`${this.base}/songs/${trackId}/tabs`);
  }
  createTab(trackId: string, body: { name: string; url: string; stem_id: number | null }) {
    return this.http.post<Tab>(`${this.base}/songs/${trackId}/tabs`, body);
  }
  /** One song URL -> a tab per guitar part (discovered from the page's track list). */
  createTabsFromSong(trackId: string, body: { url: string; stem_id: number | null }) {
    return this.http.post<{ tabs: Tab[] }>(`${this.base}/songs/${trackId}/tabs/from-song`, body);
  }
  getTab(tabId: number) {
    return this.http.get<Tab>(`${this.base}/tabs/${tabId}`);
  }
  updateTab(tabId: number, alphatex: string) {
    return this.http.patch<Tab>(`${this.base}/tabs/${tabId}`, { alphatex });
  }
  updateTabTiming(tabId: number, manual: [number, number][]) {
    return this.http.patch<Tab>(`${this.base}/tabs/${tabId}/timing`, { manual });
  }
  /** Re-run the automatic timing sync in the background (manual anchors guide it). */
  syncTab(tabId: number) {
    return this.http.post<{ ok: boolean }>(`${this.base}/tabs/${tabId}/sync`, {});
  }
  deleteTab(tabId: number) {
    return this.http.delete<{ ok: boolean }>(`${this.base}/tabs/${tabId}`);
  }

  // --- practice: user-saved chord progressions ---
  listProgressions() {
    return this.http.get<{ progressions: Progression[] }>(`${this.base}/progressions`);
  }
  createProgression(body: ProgressionInput) {
    return this.http.post<Progression>(`${this.base}/progressions`, body);
  }
  updateProgression(id: number, body: ProgressionInput) {
    return this.http.patch<Progression>(`${this.base}/progressions/${id}`, body);
  }
  deleteProgression(id: number) {
    return this.http.delete<{ ok: boolean }>(`${this.base}/progressions/${id}`);
  }

  // --- music-theory wiki ---
  wiki() {
    return this.http.get<{ categories: WikiCategory[] }>(`${this.base}/wiki`);
  }
  wikiArticle(slug: string) {
    return this.http.get<WikiArticle>(`${this.base}/wiki/${slug}`);
  }
}
