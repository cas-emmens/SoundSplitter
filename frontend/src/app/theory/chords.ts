/**
 * Chords as semitone offsets from the root, plus triad/seventh inversions.
 */
import { PitchClass, intervalLabel, mod12 } from './notes';

export interface ChordDef {
  id: string;
  /** Suffix appended to the root name, e.g. 'm', 'maj7', 'dim'. '' = major triad. */
  symbol: string;
  name: string;
  intervals: number[];
}

export const CHORDS: ChordDef[] = [
  { id: 'maj', symbol: '', name: 'Major triad', intervals: [0, 4, 7] },
  { id: 'min', symbol: 'm', name: 'Minor triad', intervals: [0, 3, 7] },
  { id: 'dim', symbol: 'dim', name: 'Diminished triad', intervals: [0, 3, 6] },
  { id: 'aug', symbol: 'aug', name: 'Augmented triad', intervals: [0, 4, 8] },
  { id: 'sus2', symbol: 'sus2', name: 'Suspended 2nd', intervals: [0, 2, 7] },
  { id: 'sus4', symbol: 'sus4', name: 'Suspended 4th', intervals: [0, 5, 7] },
  { id: 'maj7', symbol: 'maj7', name: 'Major 7th', intervals: [0, 4, 7, 11] },
  { id: 'min7', symbol: 'm7', name: 'Minor 7th', intervals: [0, 3, 7, 10] },
  { id: 'dom7', symbol: '7', name: 'Dominant 7th', intervals: [0, 4, 7, 10] },
  { id: 'm7b5', symbol: 'm7b5', name: 'Half-diminished (m7b5)', intervals: [0, 3, 6, 10] },
  { id: 'dim7', symbol: 'dim7', name: 'Diminished 7th', intervals: [0, 3, 6, 9] },
];

export function getChord(id: string): ChordDef | undefined {
  return CHORDS.find((c) => c.id === id);
}

/** Concrete pitch classes of a chord. */
export function chordNotes(rootPc: PitchClass, chord: ChordDef): PitchClass[] {
  return chord.intervals.map((i) => mod12(rootPc + i));
}

export interface ChordTone {
  pc: PitchClass;
  label: string; // interval name relative to the chord root
}

export function chordTones(rootPc: PitchClass, chord: ChordDef): ChordTone[] {
  return chord.intervals.map((i) => ({ pc: mod12(rootPc + i), label: intervalLabel(rootPc, mod12(rootPc + i)) }));
}

export const INVERSION_NAMES = ['Root position', '1st inversion', '2nd inversion', '3rd inversion'];

/**
 * Octave-aware voicing of a chord for a given inversion. Returns MIDI numbers: the lowest
 * `inversion` chord tones are moved up an octave so the bass note changes, which is what an
 * inversion actually is. `inversion` 0 = root position.
 */
export function chordVoicing(rootPc: PitchClass, chord: ChordDef, startOctave: number, inversion = 0): number[] {
  const base = (startOctave + 1) * 12 + mod12(rootPc);
  const voicing = chord.intervals.map((i) => base + i);
  const inv = ((inversion % voicing.length) + voicing.length) % voicing.length;
  for (let k = 0; k < inv; k++) {
    voicing.push(voicing.shift()! + 12); // lift the current bass note an octave
  }
  return voicing;
}

/** Format a chord name from a root pc + chord def (sharp spelling by default). */
export function chordName(rootName: string, chord: ChordDef): string {
  return rootName + chord.symbol;
}
