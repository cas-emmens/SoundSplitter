/**
 * Map a set of pitch classes (a scale or chord) onto fret positions for a given tuning, so a
 * fretboard diagram can highlight them. Strings are indexed 0 = lowest (6th) → last = highest.
 */
import { PitchClass, mod12, pcToName } from './notes';
import { Tuning } from './tunings';

export interface FretPosition {
  string: number; // 0-based, low to high
  fret: number;   // 0 = open
  pc: PitchClass;
  label: string;  // note name
  isRoot: boolean;
}

export interface FretboardOptions {
  maxFret?: number;     // highest fret to scan (default 15)
  useFlats?: boolean;   // note-name spelling
}

/**
 * Every position on the neck whose pitch class is in `pcs`. `rootPc` (if given) marks roots so the
 * diagram can emphasise them.
 */
export function fretPositions(
  tuning: Tuning,
  pcs: PitchClass[],
  rootPc: PitchClass | null,
  opts: FretboardOptions = {},
): FretPosition[] {
  const maxFret = opts.maxFret ?? 15;
  const wanted = new Set(pcs.map(mod12));
  const out: FretPosition[] = [];
  tuning.strings.forEach((s, string) => {
    for (let fret = 0; fret <= maxFret; fret++) {
      const pc = mod12(s.midi + fret);
      if (wanted.has(pc)) {
        out.push({ string, fret, pc, label: pcToName(pc, opts.useFlats), isRoot: rootPc !== null && pc === mod12(rootPc) });
      }
    }
  });
  return out;
}
