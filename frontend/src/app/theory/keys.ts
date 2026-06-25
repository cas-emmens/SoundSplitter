/**
 * Keys, diatonic chords and roman-numeral resolution.
 *
 * Roman numerals are stored key-relative so a progression transposes to any key. The reference
 * scale depends on the key's quality: major keys reference the major scale, minor keys reference
 * the natural-minor scale. So in a minor key "III" is the (major) relative-major chord at +3
 * semitones and "VII" is the subtonic at +10 — matching the usual i / ii° / III / iv / v / VI / VII
 * notation. Chord quality follows the standard case convention: UPPER = major, lower = minor,
 * a trailing ° = diminished, + = augmented, with optional 7th suffixes.
 */
import { CHORDS, ChordDef, chordName, getChord } from './chords';
import { PitchClass, mod12, pcToName } from './notes';

export type KeyQuality = 'major' | 'minor';

// Reference degree → semitone offset, per key quality.
const MAJOR_DEGREES = [0, 2, 4, 5, 7, 9, 11];
const MINOR_DEGREES = [0, 2, 3, 5, 7, 8, 10];

// Diatonic triad quality per degree (chord ids), per key quality.
const MAJOR_TRIAD_IDS = ['maj', 'min', 'min', 'maj', 'maj', 'min', 'dim'];
const MINOR_TRIAD_IDS = ['min', 'dim', 'maj', 'min', 'min', 'maj', 'maj'];
const MAJOR_SEVENTH_IDS = ['maj7', 'min7', 'min7', 'maj7', 'dom7', 'min7', 'm7b5'];
const MINOR_SEVENTH_IDS = ['min7', 'm7b5', 'maj7', 'min7', 'min7', 'maj7', 'dom7'];

const ROMAN_TO_DEGREE: Record<string, number> = { i: 1, ii: 2, iii: 3, iv: 4, v: 5, vi: 6, vii: 7 };

export function degreeOffsets(quality: KeyQuality): number[] {
  return quality === 'major' ? MAJOR_DEGREES : MINOR_DEGREES;
}

export interface ResolvedChord {
  rootPc: PitchClass;
  chord: ChordDef;
  /** Display name like "Am", "G7", "Bdim". */
  name: string;
  roman: string;
}

/**
 * Resolve a roman numeral (e.g. "ii", "V7", "bVII", "vii°", "IVmaj7") against a key.
 * Returns null if the numeral can't be parsed.
 */
export function resolveRoman(roman: string, keyRootPc: PitchClass, keyQuality: KeyQuality): ResolvedChord | null {
  const m = roman.trim().match(/^(b|#)?([iIvV]+)(.*)$/);
  if (!m) return null;
  const [, accidental, letters, rawSuffix] = m;
  const degree = ROMAN_TO_DEGREE[letters.toLowerCase()];
  if (!degree) return null;

  const offsets = degreeOffsets(keyQuality);
  let semis = offsets[degree - 1];
  if (accidental === 'b') semis -= 1;
  if (accidental === '#') semis += 1;
  const rootPc = mod12(keyRootPc + semis);

  const isUpper = letters === letters.toUpperCase();
  const chord = chordFromSuffix(rawSuffix.trim(), isUpper);
  if (!chord) return null;

  const useFlats = keyQuality === 'minor' || accidental === 'b';
  return { rootPc, chord, name: chordName(pcToName(rootPc, useFlats), chord), roman };
}

/**
 * Map a roman-numeral suffix + case into a concrete chord definition. Quality follows the standard
 * convention: case decides major vs minor (so an UPPER "V" in a minor key is the major dominant),
 * with explicit suffixes/symbols (°, +, 7, maj7, …) overriding.
 */
function chordFromSuffix(suffix: string, isUpper: boolean): ChordDef | undefined {
  const s = suffix.replace('°', 'dim').replace('+', 'aug');
  // Explicit, unambiguous quality suffixes win.
  if (/maj7/i.test(s)) return getChord('maj7');
  if (/m7b5/i.test(s)) return getChord('m7b5');
  if (/dim7/i.test(s)) return getChord('dim7');
  if (/sus2/i.test(s)) return getChord('sus2');
  if (/sus4/i.test(s)) return getChord('sus4');
  if (/dim/i.test(s)) return getChord('dim');
  if (/aug/i.test(s)) return getChord('aug');

  // Otherwise case encodes the triad quality; a "7" adds the appropriate seventh.
  const hasSeventh = /(^|[^b])7/.test(s);
  if (hasSeventh) return getChord(isUpper ? 'dom7' : 'min7');
  return getChord(isUpper ? 'maj' : 'min');
}

export interface DiatonicChord extends ResolvedChord {
  degree: number;
}

const ROMAN_NUMERALS = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII'];

/** The seven diatonic triads (or sevenths) of a key, with proper roman-numeral labels. */
export function diatonicChords(keyRootPc: PitchClass, keyQuality: KeyQuality, sevenths = false): DiatonicChord[] {
  const offsets = degreeOffsets(keyQuality);
  const triadIds = keyQuality === 'major' ? MAJOR_TRIAD_IDS : MINOR_TRIAD_IDS;
  const ids = sevenths
    ? (keyQuality === 'major' ? MAJOR_SEVENTH_IDS : MINOR_SEVENTH_IDS)
    : triadIds;
  const useFlats = keyQuality === 'minor';
  return offsets.map((semis, i) => {
    const rootPc = mod12(keyRootPc + semis);
    const chord = getChord(ids[i])!;
    const triadId = triadIds[i];
    let roman = ROMAN_NUMERALS[i];
    if (triadId === 'min' || triadId === 'dim') roman = roman.toLowerCase();
    if (triadId === 'dim') roman += '°';
    if (sevenths) roman += chord.symbol.includes('7') ? (chord.id === 'dom7' ? '7' : chord.symbol.replace(/^m/, '')) : '';
    return { degree: i + 1, rootPc, chord, name: chordName(pcToName(rootPc, useFlats), chord), roman };
  });
}

export { CHORDS };
