/**
 * Built-in chord-progression presets, stored as roman numerals so they transpose to any key.
 * User-saved progressions (from the backend) use the same shape.
 */
import { KeyQuality, ResolvedChord, resolveRoman } from './keys';
import { PitchClass } from './notes';

export interface ProgressionPreset {
  id: string;
  name: string;
  quality: KeyQuality; // the key flavour the roman numerals are written for
  chords: string[];    // roman numerals
  blurb: string;
}

export const PROGRESSIONS: ProgressionPreset[] = [
  { id: 'I-IV-V', name: 'I – IV – V', quality: 'major', chords: ['I', 'IV', 'V'],
    blurb: 'The three primary chords. Most folk, blues and early rock lives here.' },
  { id: 'I-V-vi-IV', name: 'I – V – vi – IV', quality: 'major', chords: ['I', 'V', 'vi', 'IV'],
    blurb: 'The "four-chord song" — countless pop hits use exactly these four.' },
  { id: 'vi-IV-I-V', name: 'vi – IV – I – V', quality: 'major', chords: ['vi', 'IV', 'I', 'V'],
    blurb: 'The same four chords starting on the relative minor — a more wistful spin.' },
  { id: 'ii-V-I', name: 'ii – V – I', quality: 'major', chords: ['ii', 'V', 'I'],
    blurb: 'The fundamental jazz cadence. The ii sets up the V, which resolves home.' },
  { id: 'ii-V-I-7', name: 'ii7 – V7 – Imaj7', quality: 'major', chords: ['ii7', 'V7', 'Imaj7'],
    blurb: 'The seventh-chord jazz version of the ii–V–I.' },
  { id: '50s', name: '50s (I – vi – IV – V)', quality: 'major', chords: ['I', 'vi', 'IV', 'V'],
    blurb: 'The doo-wop / "Stand By Me" progression.' },
  { id: 'blues12', name: '12-bar blues', quality: 'major',
    chords: ['I7', 'I7', 'I7', 'I7', 'IV7', 'IV7', 'I7', 'I7', 'V7', 'IV7', 'I7', 'V7'],
    blurb: 'The backbone of blues and rock & roll — twelve bars of dominant 7ths.' },
  { id: 'andalusian', name: 'Andalusian (i – VII – VI – V)', quality: 'minor', chords: ['i', 'VII', 'VI', 'V'],
    blurb: 'A descending minor-key cadence with a flamenco/rock flavour (V is major).' },
  { id: 'minor-i-iv-v', name: 'i – iv – v', quality: 'minor', chords: ['i', 'iv', 'v'],
    blurb: 'The minor-key primary chords.' },
  { id: 'minor-i-VI-III-VII', name: 'i – VI – III – VII', quality: 'minor', chords: ['i', 'VI', 'III', 'VII'],
    blurb: 'The epic/anthemic minor pop-rock loop.' },
];

export function getProgression(id: string): ProgressionPreset | undefined {
  return PROGRESSIONS.find((p) => p.id === id);
}

/** Resolve a progression's roman numerals into concrete chords for a chosen key. */
export function resolveProgression(chords: string[], keyRootPc: PitchClass, keyQuality: KeyQuality): ResolvedChord[] {
  return chords
    .map((r) => resolveRoman(r, keyRootPc, keyQuality))
    .filter((c): c is ResolvedChord => c !== null);
}
