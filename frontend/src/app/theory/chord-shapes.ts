/**
 * Curated guitar chord *fingerings* (in standard tuning) for the wiki's "how to play it" diagrams.
 *
 * Chord voicings can't be reliably derived from pitch classes — which strings to play/mute, where to
 * barre, and finger assignments are practical choices — so they're curated here. Two sources:
 *   - OPEN: position-specific open chords (only exist for certain roots).
 *   - MOVABLE: barre shapes (E-shape on the 6th string, A-shape on the 5th) that transpose to ANY
 *     root by sliding up the neck. These are the "bar chords".
 * Frets are low→high (index 0 = low E). -1 = muted (×), 0 = open.
 */
import { STANDARD_TUNING } from './tunings';
import { PitchClass, mod12, pcToName } from './notes';
import { FretPosition } from './fretboard';

export type ShapeKind = 'open' | 'E-barre' | 'A-barre';

export interface ResolvedShape {
  name: string;
  kind: ShapeKind;
  frets: number[];                                 // 6, absolute; -1 = muted, 0 = open
  fingers: number[];                               // 6; 0 = none
  barre?: { fret: number; from: number; to: number };
  baseFret: number;                                // lowest fret the diagram window shows
  midis: number[];                                 // sounding notes, for playback
}

interface MovableTemplate {
  name: string;
  rootString: number;                              // 0 = low E (E-shape), 1 = A (A-shape)
  frets: number[];                                 // relative to the barre fret (>= 0), -1 = muted
  fingers: number[];
  barre: { from: number; to: number };             // at the barre (relative fret 0)
}

interface OpenTemplate {
  name: string;
  frets: number[];
  fingers: number[];
  barre?: { fret: number; from: number; to: number };
}

const MOVABLE: Record<string, MovableTemplate[]> = {
  maj: [
    { name: 'E-shape barre', rootString: 0, frets: [0, 2, 2, 1, 0, 0], fingers: [1, 3, 4, 2, 1, 1], barre: { from: 0, to: 5 } },
    { name: 'A-shape barre', rootString: 1, frets: [-1, 0, 2, 2, 2, 0], fingers: [0, 1, 2, 3, 4, 1], barre: { from: 1, to: 5 } },
  ],
  min: [
    { name: 'Em-shape barre', rootString: 0, frets: [0, 2, 2, 0, 0, 0], fingers: [1, 3, 4, 1, 1, 1], barre: { from: 0, to: 5 } },
    { name: 'Am-shape barre', rootString: 1, frets: [-1, 0, 2, 2, 1, 0], fingers: [0, 1, 3, 4, 2, 1], barre: { from: 1, to: 5 } },
  ],
  dom7: [
    { name: 'E7-shape barre', rootString: 0, frets: [0, 2, 0, 1, 0, 0], fingers: [1, 3, 1, 2, 1, 1], barre: { from: 0, to: 5 } },
    { name: 'A7-shape barre', rootString: 1, frets: [-1, 0, 2, 0, 2, 0], fingers: [0, 1, 3, 1, 4, 1], barre: { from: 1, to: 5 } },
  ],
  maj7: [
    { name: 'Emaj7-shape barre', rootString: 0, frets: [0, 2, 1, 1, 0, 0], fingers: [1, 4, 2, 3, 1, 1], barre: { from: 0, to: 5 } },
    { name: 'Amaj7-shape barre', rootString: 1, frets: [-1, 0, 2, 1, 2, 0], fingers: [0, 1, 3, 2, 4, 1], barre: { from: 1, to: 5 } },
  ],
  min7: [
    { name: 'Em7-shape barre', rootString: 0, frets: [0, 2, 0, 0, 0, 0], fingers: [1, 3, 1, 1, 1, 1], barre: { from: 0, to: 5 } },
    { name: 'Am7-shape barre', rootString: 1, frets: [-1, 0, 2, 0, 1, 0], fingers: [0, 1, 3, 1, 2, 1], barre: { from: 1, to: 5 } },
  ],
};

const OPEN: Record<string, Record<number, OpenTemplate>> = {
  maj: {
    0: { name: 'Open C', frets: [-1, 3, 2, 0, 1, 0], fingers: [0, 3, 2, 0, 1, 0] },
    9: { name: 'Open A', frets: [-1, 0, 2, 2, 2, 0], fingers: [0, 0, 1, 2, 3, 0] },
    7: { name: 'Open G', frets: [3, 2, 0, 0, 0, 3], fingers: [2, 1, 0, 0, 0, 3] },
    4: { name: 'Open E', frets: [0, 2, 2, 1, 0, 0], fingers: [0, 2, 3, 1, 0, 0] },
    2: { name: 'Open D', frets: [-1, -1, 0, 2, 3, 2], fingers: [0, 0, 0, 1, 3, 2] },
  },
  min: {
    9: { name: 'Open Am', frets: [-1, 0, 2, 2, 1, 0], fingers: [0, 0, 2, 3, 1, 0] },
    4: { name: 'Open Em', frets: [0, 2, 2, 0, 0, 0], fingers: [0, 2, 3, 0, 0, 0] },
    2: { name: 'Open Dm', frets: [-1, -1, 0, 2, 3, 1], fingers: [0, 0, 0, 2, 3, 1] },
  },
  dom7: {
    0: { name: 'Open C7', frets: [-1, 3, 2, 3, 1, 0], fingers: [0, 3, 2, 4, 1, 0] },
    9: { name: 'Open A7', frets: [-1, 0, 2, 0, 2, 0], fingers: [0, 0, 2, 0, 3, 0] },
    2: { name: 'Open D7', frets: [-1, -1, 0, 2, 1, 2], fingers: [0, 0, 0, 2, 1, 3] },
    4: { name: 'Open E7', frets: [0, 2, 0, 1, 0, 0], fingers: [0, 2, 0, 1, 0, 0] },
    7: { name: 'Open G7', frets: [3, 2, 0, 0, 0, 1], fingers: [3, 2, 0, 0, 0, 1] },
    11: { name: 'Open B7', frets: [-1, 2, 1, 2, 0, 2], fingers: [0, 2, 1, 3, 0, 4] },
  },
  maj7: {
    0: { name: 'Open Cmaj7', frets: [-1, 3, 2, 0, 0, 0], fingers: [0, 3, 2, 0, 0, 0] },
    9: { name: 'Open Amaj7', frets: [-1, 0, 2, 1, 2, 0], fingers: [0, 0, 2, 1, 3, 0] },
    2: { name: 'Open Dmaj7', frets: [-1, -1, 0, 2, 2, 2], fingers: [0, 0, 0, 1, 1, 1] },
    4: { name: 'Open Emaj7', frets: [0, 2, 1, 1, 0, 0], fingers: [0, 3, 1, 2, 0, 0] },
    5: { name: 'Open Fmaj7', frets: [-1, -1, 3, 2, 1, 0], fingers: [0, 0, 3, 2, 1, 0] },
    7: { name: 'Open Gmaj7', frets: [3, 2, 0, 0, 0, 2], fingers: [3, 1, 0, 0, 0, 2] },
  },
  min7: {
    9: { name: 'Open Am7', frets: [-1, 0, 2, 0, 1, 0], fingers: [0, 0, 2, 0, 1, 0] },
    4: { name: 'Open Em7', frets: [0, 2, 0, 0, 0, 0], fingers: [0, 2, 0, 0, 0, 0] },
    2: { name: 'Open Dm7', frets: [-1, -1, 0, 2, 1, 1], fingers: [0, 0, 0, 2, 1, 1] },
  },
};

const OPEN_PC = STANDARD_TUNING.strings.map((s) => mod12(s.midi)); // [4,9,2,7,11,4]

function midisFor(frets: number[]): number[] {
  const out: number[] = [];
  frets.forEach((f, i) => { if (f >= 0) out.push(STANDARD_TUNING.strings[i].midi + f); });
  return out;
}

function baseFretFor(frets: number[]): number {
  const fretted = frets.filter((f) => f > 0);
  if (!fretted.length) return 1;
  const min = Math.min(...fretted);
  return min <= 1 ? 1 : min;
}

function finishOpen(t: OpenTemplate): ResolvedShape {
  return { ...t, kind: 'open', baseFret: baseFretFor(t.frets), midis: midisFor(t.frets) };
}

function finishMovable(t: MovableTemplate, barreFret: number): ResolvedShape {
  const frets = t.frets.map((f) => (f < 0 ? -1 : f + barreFret));
  return {
    name: t.name,
    kind: t.rootString === 0 ? 'E-barre' : 'A-barre',
    frets,
    fingers: t.fingers,
    barre: { fret: barreFret, from: t.barre.from, to: t.barre.to },
    baseFret: baseFretFor(frets),
    midis: midisFor(frets),
  };
}

/** Playable fingerings for a chord: any open shape for this root, plus the movable barre shapes. */
export function resolveShapes(rootPc: PitchClass, chordId: string): ResolvedShape[] {
  const out: ResolvedShape[] = [];
  const open = OPEN[chordId]?.[mod12(rootPc)];
  if (open) out.push(finishOpen(open));
  for (const t of MOVABLE[chordId] ?? []) {
    const barreFret = mod12(rootPc - OPEN_PC[t.rootString]);
    if (barreFret === 0) continue;            // barre at the nut = the open chord, already covered
    out.push(finishMovable(t, barreFret));
  }
  return out;
}

/**
 * All playable voicings of a chord across the neck: the open shape plus every barre shape at each
 * octave that fits within `maxFret`. Used to auto-pick a voicing for a hand-position window.
 */
export function voicingCandidates(rootPc: PitchClass, chordId: string, maxFret = 15): ResolvedShape[] {
  const out: ResolvedShape[] = [];
  const open = OPEN[chordId]?.[mod12(rootPc)];
  if (open) out.push(finishOpen(open));
  for (const t of MOVABLE[chordId] ?? []) {
    const base = mod12(rootPc - OPEN_PC[t.rootString]);
    const maxRel = Math.max(...t.frets.filter((f) => f >= 0));
    for (let barreFret = base; barreFret + maxRel <= maxFret; barreFret += 12) {
      if (barreFret === 0) continue;          // nut barre = open chord
      out.push(finishMovable(t, barreFret));
    }
  }
  return out;
}

/** The fretted-note span [lo, hi] of a shape (ignoring open strings). */
function frettedSpan(s: ResolvedShape): { lo: number; hi: number } {
  const f = s.frets.filter((x) => x > 0);
  return f.length ? { lo: Math.min(...f), hi: Math.max(...f) } : { lo: 0, hi: 0 };
}

/**
 * Choose the best voicing for a hand-position window: the one whose fretted notes sit inside the
 * window (heavily preferred), then closest to the window's centre, with a nudge toward open shapes.
 * With no window, returns the easiest shape (open, else lowest position).
 */
export function pickVoicing(candidates: ResolvedShape[], window: { start: number; end: number } | null): ResolvedShape | null {
  if (!candidates.length) return null;
  if (!window) {
    return candidates.find((c) => c.kind === 'open')
      ?? candidates.slice().sort((a, b) => a.baseFret - b.baseFret)[0];
  }
  const wCenter = (window.start + window.end) / 2;
  let best = candidates[0], bestScore = Infinity;
  for (const c of candidates) {
    const { lo, hi } = frettedSpan(c);
    const outside = Math.max(0, window.start - lo) + Math.max(0, hi - window.end);
    const score = outside * 100 + Math.abs((lo + hi) / 2 - wCenter) + (c.kind === 'open' ? -0.5 : 0);
    if (score < bestScore) { bestScore = score; best = c; }
  }
  return best;
}

/** Convert a shape into fretboard positions (standard tuning) for the neck diagram. */
export function shapePositions(shape: ResolvedShape, rootPc: PitchClass): FretPosition[] {
  const out: FretPosition[] = [];
  shape.frets.forEach((f, i) => {
    if (f < 0) return;
    const pc = mod12(STANDARD_TUNING.strings[i].midi + f);
    out.push({ string: i, fret: f, pc, label: pcToName(pc), isRoot: pc === mod12(rootPc) });
  });
  return out;
}
