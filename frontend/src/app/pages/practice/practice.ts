import { Component, OnDestroy, computed, effect, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { Api, Progression, ProgressionInput } from '../../services/api';
import { PracticeAudio, StepContent } from '../../services/practice-audio';
import { Fretboard } from '../theory/fretboard';
import { ChordDiagram } from '../theory/chord-diagram';
import { voicingCandidates, pickVoicing, shapePositions } from '../../theory/chord-shapes';
import { ROOT_CHOICES, mod12, midiToFreq, pcToName, PitchClass } from '../../theory/notes';
import { SCALES, getScale, scaleNotes, scaleMidi } from '../../theory/scales';
import { TUNINGS, getTuning, STANDARD_TUNING } from '../../theory/tunings';
import { fretPositions } from '../../theory/fretboard';
import { chordNotes, chordVoicing } from '../../theory/chords';
import { PROGRESSIONS, getProgression, resolveProgression } from '../../theory/progressions';
import { KeyQuality, diatonicChords } from '../../theory/keys';

type Mode = 'progression' | 'scale';

@Component({
  selector: 'app-practice',
  standalone: true,
  imports: [RouterLink, FormsModule, Fretboard, ChordDiagram],
  templateUrl: './practice.html',
  styleUrl: './practice.css',
})
export class PracticePage implements OnDestroy {
  private api = inject(Api);
  private route = inject(ActivatedRoute);
  audio = inject(PracticeAudio);

  // Shared
  readonly roots = ROOT_CHOICES;
  readonly scales = SCALES;
  readonly tunings = TUNINGS;

  mode = signal<Mode>('progression');
  keyRoot = signal<PitchClass>(0);          // C
  tuningId = signal('standard');
  bpm = signal(100);
  playing = signal(false);
  currentStep = signal(-1);

  // Progression mode
  progSource = signal('I-V-vi-IV');         // preset id, or `custom:<id>`
  progChords = signal<string[]>(['I', 'V', 'vi', 'IV']);
  progQuality = signal<KeyQuality>('major');
  beatsPerChord = signal(4);
  readonly standardTuning = STANDARD_TUNING;  // chord shapes are standard-tuning fingerings

  // Scale mode
  scaleId = signal('major');
  direction = signal<'asc' | 'desc' | 'both'>('asc');
  notesPerBeat = signal(1);

  // Fretboard "hand position" window — keeps only one stretch of the neck lit for easy reading.
  handPosition = signal(false);
  handStart = signal(5);
  handSpan = signal(4);
  readonly MAX_FRET = 15;
  readonly handWindow = computed(() =>
    this.handPosition() ? { start: this.handStart(), end: this.handStart() + this.handSpan() } : null);

  // Custom progressions (from backend)
  customs = signal<Progression[]>([]);
  editorOpen = signal(false);
  editorId = signal<number | null>(null);   // editing an existing custom, else new
  editorName = signal('');
  editorChords = signal<string[]>([]);
  saving = signal(false);

  readonly tuning = computed(() => getTuning(this.tuningId()) ?? STANDARD_TUNING);

  // Resolved progression chords for the chosen key.
  readonly resolved = computed(() =>
    resolveProgression(this.progChords(), this.keyRoot(), this.progQuality()));

  readonly currentChordIndex = computed(() => {
    const n = this.resolved().length;
    if (this.mode() !== 'progression' || n === 0 || this.currentStep() < 0) return -1;
    return Math.floor(this.currentStep() / this.beatsPerChord()) % n;
  });

  // For each chord, auto-pick the voicing (open / E-barre / A-barre, at whatever neck position) that
  // fits the hand-position window — so sliding the window re-voices the whole progression.
  readonly progShapes = computed(() => {
    const win = this.handWindow();
    const romans = this.progChords();
    return this.resolved().map((rc, i) => ({
      rc,
      roman: romans[i],
      shape: pickVoicing(voicingCandidates(rc.rootPc, rc.chord.id), win),
    }));
  });

  // Only the current chord's chosen voicing is lit on the neck (standard tuning).
  readonly progNeckPositions = computed(() => {
    const item = this.progShapes()[Math.max(0, this.currentChordIndex())];
    return item?.shape ? shapePositions(item.shape, item.rc.rootPc) : [];
  });

  // Octave-aware scale run for the current settings.
  readonly scaleSeq = computed(() => {
    const scale = getScale(this.scaleId());
    if (!scale) return [] as number[];
    const asc = scaleMidi(this.keyRoot(), scale, 4);
    if (this.direction() === 'asc') return asc;
    if (this.direction() === 'desc') return asc.slice().reverse();
    return asc.concat(asc.slice(0, -1).reverse().slice(0, -1)); // up then back down to the root
  });

  readonly currentNoteIndex = computed(() => {
    const n = this.scaleSeq().length;
    if (this.mode() !== 'scale' || n === 0 || this.currentStep() < 0) return -1;
    return this.currentStep() % n;
  });

  // Fretboard positions + the pitch classes to flash as "active".
  readonly positions = computed(() => {
    const tuning = this.tuning();
    if (this.mode() === 'progression') {
      const chord = this.resolved()[Math.max(0, this.currentChordIndex())];
      if (!chord) return [];
      return fretPositions(tuning, chordNotes(chord.rootPc, chord.chord), chord.rootPc);
    }
    const scale = getScale(this.scaleId());
    if (!scale) return [];
    return fretPositions(tuning, scaleNotes(this.keyRoot(), scale), this.keyRoot());
  });

  readonly highlightPcs = computed<number[]>(() => {
    if (this.mode() === 'progression') {
      const chord = this.resolved()[this.currentChordIndex()];
      return chord ? chordNotes(chord.rootPc, chord.chord) : [];
    }
    const i = this.currentNoteIndex();
    const seq = this.scaleSeq();
    return i >= 0 ? [mod12(seq[i])] : [];
  });

  readonly diatonic = computed(() => diatonicChords(this.keyRoot(), this.progQuality()));

  constructor() {
    this.audio.referenceTones = true;
    this.api.listProgressions().subscribe((r) => this.customs.set(r.progressions));
    this.applyDeepLink();
    // Keep the engine's live tempo in sync with the slider.
    effect(() => this.audio.setBpm(this.bpm()));
  }

  // --- deep-linking from the Theory page ---
  private applyDeepLink() {
    const q = this.route.snapshot.queryParamMap;
    const root = q.get('root');
    if (root !== null && !isNaN(+root)) this.keyRoot.set(mod12(+root));
    const bpm = q.get('bpm');
    if (bpm && !isNaN(+bpm)) this.bpm.set(+bpm);
    const mode = q.get('mode');
    if (mode === 'scale') {
      this.mode.set('scale');
      const scale = q.get('scale');
      if (scale && getScale(scale)) this.scaleId.set(scale);
    } else if (mode === 'progression') {
      this.mode.set('progression');
      const prog = q.get('prog');
      if (prog && getProgression(prog)) this.selectProgression(prog);
    }
  }

  // --- progression selection ---
  selectProgression(source: string) {
    this.stop();
    this.progSource.set(source);
    if (source.startsWith('custom:')) {
      const id = +source.slice(7);
      const c = this.customs().find((p) => p.id === id);
      if (c) {
        this.progChords.set(c.chords);
        this.progQuality.set(c.quality);
        this.keyRoot.set(c.root_pc);
        this.bpm.set(c.tempo);
      }
    } else {
      const p = getProgression(source);
      if (p) {
        this.progChords.set(p.chords);
        this.progQuality.set(p.quality);
      }
    }
  }

  setMode(m: Mode) { this.stop(); this.mode.set(m); }
  setKeyRoot(pc: number) { this.stop(); this.keyRoot.set(mod12(pc)); }

  /** Commit a typed tempo, clamped to the slider's range. */
  setTempo(v: string | number) {
    const n = Math.round(Number(v));
    if (Number.isFinite(n)) this.bpm.set(Math.max(40, Math.min(240, n)));
  }

  setHandSpan(n: number) {
    this.handSpan.set(n);
    if (this.handStart() > this.MAX_FRET - n) this.handStart.set(this.MAX_FRET - n);
  }

  // --- transport ---
  togglePlay() { this.playing() ? this.stop() : this.play(); }

  private play() {
    this.currentStep.set(-1);
    const cfg = this.mode() === 'progression' ? this.progressionConfig() : this.scaleConfig();
    if (!cfg) return;
    this.audio.start(cfg);
    this.playing.set(true);
  }

  stop() {
    this.audio.stop();
    this.playing.set(false);
    this.currentStep.set(-1);
  }

  ngOnDestroy() { this.audio.stop(); } // don't leave the metronome running after leaving the page

  private progressionConfig() {
    if (!this.resolved().length) return null;
    const beats = this.beatsPerChord();
    return {
      bpm: this.bpm(),
      notesPerBeat: 1,
      beatsPerBar: beats,
      getStep: (i: number): StepContent | null => {
        if (i % beats !== 0) return { freqs: [] };           // sustain — click only
        // Sound the actual displayed guitar shape, so the Shape selector changes what you hear too.
        const items = this.progShapes();
        const item = items[Math.floor(i / beats) % items.length];
        const midis = item.shape ? item.shape.midis : chordVoicing(item.rc.rootPc, item.rc.chord, 3, 0);
        return { freqs: midis.map(midiToFreq), durationBeats: beats };
      },
      onStep: (i: number) => this.currentStep.set(i),
    };
  }

  private scaleConfig() {
    const seq = this.scaleSeq();
    if (!seq.length) return null;
    return {
      bpm: this.bpm(),
      notesPerBeat: this.notesPerBeat(),
      beatsPerBar: 4,
      getStep: (i: number): StepContent => ({ freqs: [midiToFreq(seq[i % seq.length])] }),
      onStep: (i: number) => this.currentStep.set(i),
    };
  }

  // --- custom progression editor ---
  newProgression() {
    this.editorId.set(null);
    this.editorName.set('');
    this.editorChords.set([]);
    this.editorOpen.set(true);
  }

  editCustom(p: Progression) {
    this.editorId.set(p.id);
    this.editorName.set(p.name);
    this.editorChords.set([...p.chords]);
    this.progQuality.set(p.quality);
    this.keyRoot.set(p.root_pc);
    this.editorOpen.set(true);
  }

  addChord(roman: string) { this.editorChords.update((c) => [...c, roman]); }
  removeLastChord() { this.editorChords.update((c) => c.slice(0, -1)); }
  clearChords() { this.editorChords.set([]); }

  saveProgression() {
    const name = this.editorName().trim();
    const chords = this.editorChords();
    if (!name || !chords.length) return;
    this.saving.set(true);
    const body: ProgressionInput = {
      name, chords, quality: this.progQuality(), root_pc: this.keyRoot(), tempo: this.bpm(),
    };
    const id = this.editorId();
    const req = id === null ? this.api.createProgression(body) : this.api.updateProgression(id, body);
    req.subscribe({
      next: (saved) => {
        this.api.listProgressions().subscribe((r) => this.customs.set(r.progressions));
        this.saving.set(false);
        this.editorOpen.set(false);
        this.selectProgression(`custom:${saved.id}`);
      },
      error: () => this.saving.set(false),
    });
  }

  deleteCustom(p: Progression) {
    this.api.deleteProgression(p.id).subscribe(() => {
      this.customs.update((list) => list.filter((x) => x.id !== p.id));
      if (this.progSource() === `custom:${p.id}`) this.selectProgression('I-V-vi-IV');
    });
  }

  // --- display helpers ---
  readonly presets = PROGRESSIONS;
  pcName(pc: number) { return pcToName(pc, this.progQuality() === 'minor'); }
  noteName(midi: number) { return pcToName(mod12(midi), this.progQuality() === 'minor'); }
  currentScaleNoteName() {
    const i = this.currentNoteIndex();
    const seq = this.scaleSeq();
    return i >= 0 ? this.noteName(seq[i]) : '';
  }
}
