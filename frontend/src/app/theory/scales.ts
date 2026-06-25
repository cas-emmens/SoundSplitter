/**
 * Scales & modes as semitone offsets from the root. `scaleNotes` turns a root pitch class +
 * a scale type into the concrete pitch classes of that scale.
 */
import { PitchClass, mod12 } from './notes';

export interface ScaleDef {
  id: string;
  name: string;
  /** Ascending semitone offsets from the root, NOT including the octave. */
  intervals: number[];
  /** Whether the key built on this scale reads more naturally with flats. */
  preferFlats?: boolean;
  blurb: string;
}

export const SCALES: ScaleDef[] = [
  { id: 'major', name: 'Major (Ionian)', intervals: [0, 2, 4, 5, 7, 9, 11],
    blurb: 'The "do-re-mi" scale — bright and resolved. The reference every other mode is measured against.' },
  { id: 'dorian', name: 'Dorian', intervals: [0, 2, 3, 5, 7, 9, 10],
    blurb: 'A minor mode with a raised 6th — minor but hopeful. Heard all over funk, jazz and modal rock.' },
  { id: 'phrygian', name: 'Phrygian', intervals: [0, 1, 3, 5, 7, 8, 10], preferFlats: true,
    blurb: 'Minor with a flat 2nd — a dark, Spanish/metal flavour from that semitone above the root.' },
  { id: 'lydian', name: 'Lydian', intervals: [0, 2, 4, 6, 7, 9, 11],
    blurb: 'Major with a sharp 4th — dreamy and floating. The "film score" mode.' },
  { id: 'mixolydian', name: 'Mixolydian', intervals: [0, 2, 4, 5, 7, 9, 10],
    blurb: 'Major with a flat 7th — the dominant/blues-rock sound. Think riffs and jam bands.' },
  { id: 'aeolian', name: 'Minor (Aeolian)', intervals: [0, 2, 3, 5, 7, 8, 10], preferFlats: true,
    blurb: 'The natural minor scale — the default "sad" sound.' },
  { id: 'locrian', name: 'Locrian', intervals: [0, 1, 3, 5, 6, 8, 10], preferFlats: true,
    blurb: 'Minor with a flat 2nd AND flat 5th — unstable, rarely a home key. The diminished mode.' },
  { id: 'harmonic_minor', name: 'Harmonic minor', intervals: [0, 2, 3, 5, 7, 8, 11], preferFlats: true,
    blurb: 'Natural minor with a raised 7th — the gap between b6 and 7 gives that exotic, classical tension.' },
  { id: 'melodic_minor', name: 'Melodic minor', intervals: [0, 2, 3, 5, 7, 9, 11], preferFlats: true,
    blurb: 'Minor with a raised 6th and 7th — smooth leading tone, a jazz workhorse.' },
  { id: 'major_pentatonic', name: 'Major pentatonic', intervals: [0, 2, 4, 7, 9],
    blurb: 'Major scale minus the 4th and 7th — five notes that never clash. Folk and country lead.' },
  { id: 'minor_pentatonic', name: 'Minor pentatonic', intervals: [0, 3, 5, 7, 10], preferFlats: true,
    blurb: 'The rock/blues lead scale — five safe notes over a minor or blues backing.' },
  { id: 'blues', name: 'Blues', intervals: [0, 3, 5, 6, 7, 10], preferFlats: true,
    blurb: 'Minor pentatonic plus the "blue note" (b5) — the grit between the 4th and 5th.' },
];

export function getScale(id: string): ScaleDef | undefined {
  return SCALES.find((s) => s.id === id);
}

/** Concrete pitch classes of a scale, ascending from the root. */
export function scaleNotes(rootPc: PitchClass, scale: ScaleDef): PitchClass[] {
  return scale.intervals.map((i) => mod12(rootPc + i));
}

/**
 * Scale tones as octave-aware MIDI numbers, ascending from a starting octave. Used by the
 * practice player so it can walk the scale up (and across an octave boundary) note by note.
 */
export function scaleMidi(rootPc: PitchClass, scale: ScaleDef, startOctave: number): number[] {
  const start = (startOctave + 1) * 12 + mod12(rootPc);
  const midi = scale.intervals.map((i) => start + i);
  midi.push(start + 12); // include the octave so a run resolves on the root
  return midi;
}
