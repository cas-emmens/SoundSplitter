import { Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { marked } from 'marked';
import { Fretboard } from './fretboard';
import { ChordDiagram } from './chord-diagram';
import { resolveShapes, ResolvedShape } from '../../theory/chord-shapes';
import { Api, WikiArticle, WikiCategory } from '../../services/api';
import { PracticeAudio } from '../../services/practice-audio';
import { ROOT_CHOICES, midiToFreq, pcToName, pcToMidi, PitchClass } from '../../theory/notes';
import { SCALES, getScale, scaleNotes } from '../../theory/scales';
import { CHORDS, getChord, chordNotes, chordTones, chordVoicing, chordName, INVERSION_NAMES } from '../../theory/chords';
import { TUNINGS, getTuning, STANDARD_TUNING } from '../../theory/tunings';
import { fretPositions } from '../../theory/fretboard';
import { PROGRESSIONS, getProgression, resolveProgression } from '../../theory/progressions';
import { KeyQuality, DiatonicChord, diatonicChords } from '../../theory/keys';

const FULL_INTERVALS = [
  'Unison', 'Minor 2nd', 'Major 2nd', 'Minor 3rd', 'Major 3rd', 'Perfect 4th',
  'Tritone', 'Perfect 5th', 'Minor 6th', 'Major 6th', 'Minor 7th', 'Major 7th', 'Octave',
];

@Component({
  selector: 'app-theory',
  standalone: true,
  imports: [FormsModule, Fretboard, ChordDiagram],
  templateUrl: './theory.html',
  styleUrl: './theory.css',
})
export class TheoryPage {
  private api = inject(Api);
  private router = inject(Router);
  private route = inject(ActivatedRoute);
  audio = inject(PracticeAudio);

  readonly roots = ROOT_CHOICES;
  readonly scales = SCALES;
  readonly chords = CHORDS;
  readonly tunings = TUNINGS;
  readonly presets = PROGRESSIONS;
  readonly inversionNames = INVERSION_NAMES;
  readonly fullIntervals = FULL_INTERVALS;

  // --- wiki ---
  categories = signal<WikiCategory[]>([]);
  currentSlug = signal<string | null>(null);
  article = signal<WikiArticle | null>(null);
  readonly widget = computed(() => this.article()?.widget ?? null);
  readonly renderedBody = computed(() => {
    const a = this.article();
    return a ? (marked.parse(a.body, { async: false }) as string) : '';
  });

  // --- shared explorer state ---
  keyRoot = signal<PitchClass>(0);
  tuningId = signal('standard');
  scaleId = signal('major');
  chordRoot = signal<PitchClass>(0);
  chordId = signal('maj');
  inversion = signal(0);
  keyQuality = signal<KeyQuality>('major');
  sevenths = signal(false);
  progId = signal('I-V-vi-IV');
  progPreview = signal(0);

  readonly tuning = computed(() => getTuning(this.tuningId()) ?? STANDARD_TUNING);

  // scales
  readonly scale = computed(() => getScale(this.scaleId())!);
  readonly scalePcs = computed(() => scaleNotes(this.keyRoot(), this.scale()));
  readonly scalePositions = computed(() =>
    fretPositions(this.tuning(), this.scalePcs(), this.keyRoot(), { useFlats: this.scale().preferFlats }));

  // chords
  readonly chord = computed(() => getChord(this.chordId())!);
  readonly chordTones = computed(() => chordTones(this.chordRoot(), this.chord()));
  readonly chordPcs = computed(() => chordNotes(this.chordRoot(), this.chord()));
  readonly chordPositions = computed(() => fretPositions(this.tuning(), this.chordPcs(), this.chordRoot()));
  readonly chordVoicingMidi = computed(() => chordVoicing(this.chordRoot(), this.chord(), 3, this.inversion()));
  readonly chordLabel = computed(() => chordName(pcToName(this.chordRoot()), this.chord()));
  readonly chordShapes = computed(() => resolveShapes(this.chordRoot(), this.chordId()));

  // keys
  readonly diatonic = computed(() => diatonicChords(this.keyRoot(), this.keyQuality(), this.sevenths()));

  // progressions
  readonly preset = computed(() => getProgression(this.progId())!);
  readonly progQuality = computed(() => this.preset().quality);
  readonly progChords = computed(() => resolveProgression(this.preset().chords, this.keyRoot(), this.progQuality()));
  readonly progPositions = computed(() => {
    const c = this.progChords()[this.progPreview()];
    return c ? fretPositions(this.tuning(), chordNotes(c.rootPc, c.chord), c.rootPc) : [];
  });

  constructor() {
    this.api.wiki().subscribe((r) => {
      this.categories.set(r.categories);
      const wanted = this.route.snapshot.queryParamMap.get('article');
      const first = r.categories[0]?.articles[0]?.slug;
      const slug = (wanted && this.hasArticle(r.categories, wanted)) ? wanted : first;
      if (slug) this.openArticle(slug);
    });
  }

  private hasArticle(cats: WikiCategory[], slug: string) {
    return cats.some((c) => c.articles.some((a) => a.slug === slug));
  }

  openArticle(slug: string) {
    if (slug === this.currentSlug()) return;
    this.currentSlug.set(slug);
    this.api.wikiArticle(slug).subscribe((a) => {
      this.article.set(a);
      this.applyWidgetArg(a);
      // Keep the URL shareable without reloading the component.
      this.router.navigate([], { relativeTo: this.route, queryParams: { article: slug }, replaceUrl: true });
    });
  }

  /** Preset the embedded explorer to match the article (e.g. the Dorian page opens on Dorian). */
  private applyWidgetArg(a: WikiArticle) {
    const arg = a.widget_arg;
    if (!arg) return;
    switch (a.widget) {
      case 'scales': if (getScale(arg)) this.scaleId.set(arg); break;
      case 'chords': if (getChord(arg)) { this.chordId.set(arg); this.inversion.set(0); } break;
      case 'progressions': if (getProgression(arg)) { this.progId.set(arg); this.progPreview.set(0); } break;
    }
  }

  // --- audio previews ---
  playScale() {
    const base = pcToMidi(this.keyRoot(), 4);
    const midi = this.scale().intervals.map((i) => base + i);
    midi.push(base + 12);
    midi.forEach((m, i) => setTimeout(() => this.audio.preview([midiToFreq(m)], 0.35), i * 260));
  }
  playChord() { this.audio.preview(this.chordVoicingMidi().map(midiToFreq), 1.1); }
  playShape(s: ResolvedShape) { this.audio.preview(s.midis.map(midiToFreq), 1.2); }
  playInterval(semis: number) {
    const root = pcToMidi(this.keyRoot(), 4);
    this.audio.preview([midiToFreq(root), midiToFreq(root + semis)], 0.9);
  }
  playDiatonic(d: DiatonicChord) {
    this.audio.preview(chordVoicing(d.rootPc, d.chord, 3).map(midiToFreq), 1.0);
  }
  playProgChord(i: number) {
    this.progPreview.set(i);
    const c = this.progChords()[i];
    if (c) this.audio.preview(chordVoicing(c.rootPc, c.chord, 3).map(midiToFreq), 1.0);
  }
  cycleInversion() { this.inversion.update((v) => (v + 1) % this.chord().intervals.length); }

  // --- deep links into the practice tool ---
  practiceScale() {
    this.router.navigate(['/practice'],
      { queryParams: { mode: 'scale', root: this.keyRoot(), scale: this.scaleId() } });
  }
  practiceProgression() {
    this.router.navigate(['/practice'],
      { queryParams: { mode: 'progression', prog: this.progId(), root: this.keyRoot() } });
  }

  // --- helpers ---
  pcName(pc: number, flats = false) { return pcToName(pc, flats); }
}
