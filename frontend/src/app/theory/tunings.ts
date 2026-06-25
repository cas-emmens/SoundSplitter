/**
 * Guitar tunings. A tuning is just the open-string notes from lowest (6th string) to highest
 * (1st string), as octave-aware MIDI numbers so the fretboard knows both pitch class and register.
 * Standard tuning is E2 A2 D3 G3 B3 E4.
 */
import { PitchClass, mod12, nameToPc, pcToMidi } from './notes';

export interface OpenString {
  midi: number; // open-string pitch
}

export interface Tuning {
  id: string;
  name: string;
  /** Open strings, low to high. */
  strings: OpenString[];
}

/** Build a tuning from note+octave pairs given low → high. */
function t(id: string, name: string, specs: [string, number][]): Tuning {
  return {
    id,
    name,
    strings: specs.map(([n, oct]) => ({ midi: pcToMidi(nameToPc(n) ?? 0, oct) })),
  };
}

export const TUNINGS: Tuning[] = [
  t('standard', 'Standard (E A D G B E)', [['E', 2], ['A', 2], ['D', 3], ['G', 3], ['B', 3], ['E', 4]]),
  t('drop_d', 'Drop D (D A D G B E)', [['D', 2], ['A', 2], ['D', 3], ['G', 3], ['B', 3], ['E', 4]]),
  t('eb', 'Half-step down (Eb)', [['D#', 2], ['G#', 2], ['C#', 3], ['F#', 3], ['A#', 3], ['D#', 4]]),
  t('drop_c', 'Drop C (C G C F A D)', [['C', 2], ['G', 2], ['C', 3], ['F', 3], ['A', 3], ['D', 4]]),
  t('dadgad', 'DADGAD', [['D', 2], ['A', 2], ['D', 3], ['G', 3], ['A', 3], ['D', 4]]),
  t('open_g', 'Open G (D G D G B D)', [['D', 2], ['G', 2], ['D', 3], ['G', 3], ['B', 3], ['D', 4]]),
  t('open_d', 'Open D (D A D F# A D)', [['D', 2], ['A', 2], ['D', 3], ['F#', 3], ['A', 3], ['D', 4]]),
  t('seven_standard', '7-string (B E A D G B E)',
    [['B', 1], ['E', 2], ['A', 2], ['D', 3], ['G', 3], ['B', 3], ['E', 4]]),
];

export const STANDARD_TUNING = TUNINGS[0];

export function getTuning(id: string): Tuning | undefined {
  return TUNINGS.find((t) => t.id === id);
}

/** Pitch class of an open string. */
export function openPc(s: OpenString): PitchClass {
  return mod12(s.midi);
}
