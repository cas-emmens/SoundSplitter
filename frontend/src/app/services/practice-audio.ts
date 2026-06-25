import { Injectable } from '@angular/core';

/** What to sound on a given step. `freqs` empty = a rest (click only). */
export interface StepContent {
  freqs: number[];
  /** How long the tones ring, in beats. Defaults to one subdivision. */
  durationBeats?: number;
}

export interface PracticeConfig {
  bpm: number;
  /** Subdivisions per beat: 1 = one note per click, 2 = eighths, 4 = sixteenths, etc. */
  notesPerBeat: number;
  /** Beats per bar — only used to accent the downbeat click. */
  beatsPerBar: number;
  /** Content for each step (0-based, strictly increasing). Wrap/loop inside if desired. */
  getStep: (index: number) => StepContent | null;
  /** Fired at the *audible* moment of each step, for UI highlighting. */
  onStep?: (index: number) => void;
}

const LOOKAHEAD_MS = 25;       // how often the scheduler wakes
const SCHEDULE_AHEAD_S = 0.12; // how far ahead it schedules audio

/**
 * Web-Audio metronome + soft synth for the practice tool. A classic look-ahead scheduler keeps
 * clicks and reference tones sample-accurate; the click always sounds, while tones are gated by
 * the `referenceTones` toggle. A requestAnimationFrame drain fires `onStep` exactly when each
 * step becomes audible so the UI advances in time with the sound.
 */
@Injectable({ providedIn: 'root' })
export class PracticeAudio {
  /** The "play reference tones" toggle. Click always plays regardless. */
  referenceTones = true;

  private ctx?: AudioContext;
  private master?: GainNode;

  private cfg?: PracticeConfig;
  private bpm = 100;
  private timer?: ReturnType<typeof setInterval>;
  private raf = 0;
  private step = 0;
  private nextStepTime = 0;
  private oscillators: OscillatorNode[] = [];
  private drawQueue: { index: number; time: number }[] = [];

  private _running = false;
  get running() { return this._running; }

  /** Live tempo change (e.g. from a slider) without restarting. */
  setBpm(bpm: number) {
    this.bpm = bpm;
    if (this.cfg) this.cfg.bpm = bpm;
  }

  /** Audition a single chord/note immediately (used by the theory page's "hear it" buttons). */
  preview(freqs: number[], durationS = 0.7) {
    const ctx = this.ensureCtx();
    ctx.resume();
    this.playTones(freqs, ctx.currentTime + 0.02, durationS);
  }

  start(cfg: PracticeConfig) {
    this.stop();
    const ctx = this.ensureCtx();
    ctx.resume();
    this.cfg = cfg;
    this.bpm = cfg.bpm;
    this.step = 0;
    this.nextStepTime = ctx.currentTime + 0.1;
    this._running = true;
    this.timer = setInterval(() => this.scheduler(), LOOKAHEAD_MS);
    this.drainLoop();
  }

  stop() {
    this._running = false;
    if (this.timer) { clearInterval(this.timer); this.timer = undefined; }
    if (this.raf) { cancelAnimationFrame(this.raf); this.raf = 0; }
    for (const o of this.oscillators) { try { o.stop(); } catch {} }
    this.oscillators = [];
    this.drawQueue = [];
  }

  private ensureCtx(): AudioContext {
    if (!this.ctx) {
      this.ctx = new AudioContext();
      this.master = this.ctx.createGain();
      this.master.gain.value = 0.9;
      this.master.connect(this.ctx.destination);
    }
    return this.ctx;
  }

  // --- scheduling ---

  private scheduler() {
    const ctx = this.ctx!;
    const cfg = this.cfg!;
    while (this.nextStepTime < ctx.currentTime + SCHEDULE_AHEAD_S) {
      const secondsPerBeat = 60 / this.bpm;
      const stepDur = secondsPerBeat / cfg.notesPerBeat;
      const beatInBar = Math.floor(this.step / cfg.notesPerBeat) % cfg.beatsPerBar;
      const stepInBeat = this.step % cfg.notesPerBeat;

      // Click on every beat; accent the downbeat.
      if (stepInBeat === 0) this.click(this.nextStepTime, beatInBar === 0);

      const content = cfg.getStep(this.step);
      if (content && this.referenceTones && content.freqs.length) {
        const dur = (content.durationBeats ?? 1 / cfg.notesPerBeat) * secondsPerBeat;
        this.playTones(content.freqs, this.nextStepTime, dur * 0.95);
      }

      this.drawQueue.push({ index: this.step, time: this.nextStepTime });
      this.nextStepTime += stepDur;
      this.step++;
    }
  }

  /** Fire onStep callbacks as the audio clock reaches each queued step. */
  private drainLoop = () => {
    const ctx = this.ctx;
    if (!ctx || !this._running) return;
    while (this.drawQueue.length && this.drawQueue[0].time <= ctx.currentTime) {
      const { index } = this.drawQueue.shift()!;
      this.cfg?.onStep?.(index);
    }
    this.raf = requestAnimationFrame(this.drainLoop);
  };

  // --- sound generation ---

  private click(time: number, accent: boolean) {
    const ctx = this.ctx!;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = accent ? 1760 : 1100;
    gain.gain.setValueAtTime(0.0001, time);
    gain.gain.exponentialRampToValueAtTime(accent ? 0.5 : 0.32, time + 0.001);
    gain.gain.exponentialRampToValueAtTime(0.0001, time + 0.05);
    osc.connect(gain).connect(this.master!);
    osc.start(time);
    osc.stop(time + 0.06);
    this.track(osc);
  }

  private playTones(freqs: number[], time: number, durS: number) {
    const ctx = this.ctx!;
    const peak = 0.22 / Math.max(1, Math.sqrt(freqs.length)); // keep chords from clipping
    for (const f of freqs) {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'triangle';
      osc.frequency.value = f;
      // Soft pluck-ish envelope.
      gain.gain.setValueAtTime(0.0001, time);
      gain.gain.exponentialRampToValueAtTime(peak, time + 0.012);
      gain.gain.exponentialRampToValueAtTime(0.0001, time + Math.max(0.08, durS));
      osc.connect(gain).connect(this.master!);
      osc.start(time);
      osc.stop(time + Math.max(0.1, durS) + 0.05);
      this.track(osc);
    }
  }

  private track(osc: OscillatorNode) {
    this.oscillators.push(osc);
    osc.onended = () => {
      const i = this.oscillators.indexOf(osc);
      if (i >= 0) this.oscillators.splice(i, 1);
    };
  }
}
