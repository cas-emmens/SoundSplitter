import { Injectable } from '@angular/core';

export interface StemSpec {
  name: string;
  url: string;
  offsetMs: number;
}

interface Track {
  name: string;
  buffer: AudioBuffer;
  gain: GainNode;
  offset: number;        // seconds, positive = stem starts later
  source?: AudioBufferSourceNode;
  muted: boolean;
  volume: number;        // 0..1 user volume (independent of mute/solo)
}

/**
 * Synchronized multi-stem player using the Web Audio API.
 * All stems share one timeline; mute/solo/volume flip gains instantly.
 * Transport (play/pause/seek) recreates the one-shot source nodes in sync.
 */
@Injectable({ providedIn: 'root' })
export class MultitrackPlayer {
  private ctx?: AudioContext;
  private tracks = new Map<string, Track>();
  private order: string[] = [];
  private soloName: string | null = null;

  private playing = false;
  private startCtxTime = 0;   // ctx.currentTime when playback (re)started
  private startPos = 0;       // timeline position at that moment
  private pausedPos = 0;
  private _duration = 0;

  get duration() { return this._duration; }
  get isPlaying() { return this.playing; }
  get stemNames() { return this.order.slice(); }

  async load(stems: StemSpec[]): Promise<void> {
    this.stop();
    this.ctx?.close();
    this.ctx = new AudioContext();
    this.tracks.clear();
    this.order = [];
    this.soloName = null;
    this.pausedPos = 0;
    this._duration = 0;

    const buffers = await Promise.all(
      stems.map(async (s) => {
        const resp = await fetch(s.url);
        const arr = await resp.arrayBuffer();
        const buf = await this.ctx!.decodeAudioData(arr);
        return { s, buf };
      })
    );

    for (const { s, buf } of buffers) {
      const gain = this.ctx.createGain();
      gain.connect(this.ctx.destination);
      const offset = s.offsetMs / 1000;
      this.tracks.set(s.name, {
        name: s.name, buffer: buf, gain, offset, muted: false, volume: 1,
      });
      this.order.push(s.name);
      this._duration = Math.max(this._duration, offset + buf.duration);
    }
    this.applyGains();
  }

  private effectiveGain(t: Track): number {
    if (this.soloName) return t.name === this.soloName ? t.volume : 0;
    return t.muted ? 0 : t.volume;
  }
  private applyGains() {
    if (!this.ctx) return;
    for (const t of this.tracks.values()) {
      t.gain.gain.setTargetAtTime(this.effectiveGain(t), this.ctx.currentTime, 0.01);
    }
  }

  setMuted(name: string, muted: boolean) {
    const t = this.tracks.get(name); if (!t) return;
    t.muted = muted; this.applyGains();
  }
  isMuted(name: string) { return this.tracks.get(name)?.muted ?? false; }

  setVolume(name: string, v: number) {
    const t = this.tracks.get(name); if (!t) return;
    t.volume = v; this.applyGains();
  }
  getVolume(name: string) { return this.tracks.get(name)?.volume ?? 1; }

  toggleSolo(name: string) {
    this.soloName = this.soloName === name ? null : name;
    this.applyGains();
  }
  isSolo(name: string) { return this.soloName === name; }

  /** Apply a preset: mute exactly the named stems, unmute the rest. */
  applyMutePreset(names: string[]) {
    this.soloName = null;
    for (const t of this.tracks.values()) t.muted = names.includes(t.name);
    this.applyGains();
  }

  play() {
    if (!this.ctx || this.playing) return;
    this.ctx.resume();
    const startAt = this.ctx.currentTime + 0.03;
    const pos = this.pausedPos >= this._duration ? 0 : this.pausedPos;
    for (const t of this.tracks.values()) {
      const src = this.ctx.createBufferSource();
      src.buffer = t.buffer;
      src.connect(t.gain);
      const local = pos - t.offset;          // source time corresponding to timeline pos
      if (local >= t.buffer.duration) { continue; }
      if (local >= 0) src.start(startAt, local);
      else src.start(startAt - local, 0);    // stem hasn't begun yet; delay its start
      t.source = src;
    }
    this.startCtxTime = startAt;
    this.startPos = pos;
    this.playing = true;
  }

  pause() {
    if (!this.playing) return;
    this.pausedPos = this.position();
    this.stopSources();
    this.playing = false;
  }

  seek(pos: number) {
    const clamped = Math.max(0, Math.min(pos, this._duration));
    if (this.playing) { this.stopSources(); this.playing = false; this.pausedPos = clamped; this.play(); }
    else this.pausedPos = clamped;
  }

  position(): number {
    if (!this.ctx) return 0;
    if (!this.playing) return this.pausedPos;
    return this.startPos + (this.ctx.currentTime - this.startCtxTime);
  }

  private stopSources() {
    for (const t of this.tracks.values()) {
      try { t.source?.stop(); } catch { /* already stopped */ }
      t.source = undefined;
    }
  }
  stop() {
    this.stopSources();
    this.playing = false;
    this.pausedPos = 0;
  }
}
