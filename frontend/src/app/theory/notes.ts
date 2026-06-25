/**
 * Core pitch model. A "pitch class" (pc) is an integer 0..11 where 0 = C, 1 = C#, ... 11 = B.
 * Octave-aware notes are MIDI numbers (C4 = 60). Everything else in the theory engine is built
 * on these two primitives.
 */

export type PitchClass = number; // 0..11

export const SHARP_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
export const FLAT_NAMES = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B'];

/** All twelve roots a user can pick from, in a sensible order for dropdowns. */
export const ROOT_CHOICES: { pc: PitchClass; label: string }[] = SHARP_NAMES.map((_, pc) => ({
  pc,
  // Show enharmonic spelling for the black keys so both names are visible.
  label: SHARP_NAMES[pc] === FLAT_NAMES[pc] ? SHARP_NAMES[pc] : `${SHARP_NAMES[pc]}/${FLAT_NAMES[pc]}`,
}));

/** Wrap any integer into a pitch class 0..11. */
export function mod12(n: number): PitchClass {
  return ((n % 12) + 12) % 12;
}

/** Name a pitch class, using flats when the key/context prefers them. */
export function pcToName(pc: PitchClass, useFlats = false): string {
  return (useFlats ? FLAT_NAMES : SHARP_NAMES)[mod12(pc)];
}

/** Parse a note name like "E", "Bb", "F#" into a pitch class (null if unrecognised). */
export function nameToPc(name: string): PitchClass | null {
  const trimmed = name.trim();
  let i = SHARP_NAMES.indexOf(trimmed);
  if (i >= 0) return i;
  i = FLAT_NAMES.indexOf(trimmed);
  if (i >= 0) return i;
  return null;
}

/** Transpose a pitch class by a number of semitones. */
export function transpose(pc: PitchClass, semitones: number): PitchClass {
  return mod12(pc + semitones);
}

/** Frequency (Hz) of a MIDI note. A4 (MIDI 69) = 440 Hz. */
export function midiToFreq(midi: number): number {
  return 440 * Math.pow(2, (midi - 69) / 12);
}

/** MIDI number for a pitch class in a given octave (C4 = 60, so octave 4 → pc 0 = 60). */
export function pcToMidi(pc: PitchClass, octave: number): number {
  return (octave + 1) * 12 + mod12(pc);
}

/**
 * Interval names by semitone distance (0..12). Used to label chord/scale tones.
 */
export const INTERVAL_NAMES = [
  'Root', 'b2', '2', 'b3', '3', '4', 'b5', '5', 'b6', '6', 'b7', '7', 'Octave',
];

/** Label the interval (relative to a root pc) of another pc. */
export function intervalLabel(rootPc: PitchClass, pc: PitchClass): string {
  return INTERVAL_NAMES[mod12(pc - rootPc)];
}
