"""Bundled music-theory wiki content.

This module is the source of truth for the in-app theory wiki. On startup `db.seed_wiki` upserts it
into the `wiki_articles` table, guarded by `WIKI_VERSION`. Bump `WIKI_VERSION` whenever ARTICLES
change so an app update re-seeds the database on next launch.

Each article: slug, title, category, category_order, order, widget, widget_arg, body (Markdown).
`widget` embeds an interactive explorer on the Theory page; `widget_arg` presets it:
  - intervals      (no arg)
  - scales         arg = scale id   (major, dorian, …, minor_pentatonic, blues)
  - chords         arg = chord id   (maj, min, maj7, dom7, …)
  - keys           (no arg)
  - progressions   arg = progression id (I-V-vi-IV, ii-V-I, blues12, …)
"""
from __future__ import annotations

WIKI_VERSION = 1

# Category display order.
FOUNDATIONS, SCALES, HARMONY, GUITAR = 0, 1, 2, 3

ARTICLES: list[dict] = [
    # ----------------------------------------------------------------- Foundations
    dict(
        slug="notes-octaves", title="Notes, octaves & the chromatic scale",
        category="Foundations", category_order=FOUNDATIONS, order=1,
        widget=None, widget_arg=None,
        body="""# Notes, octaves & the chromatic scale

Western music divides the octave into **twelve equally-spaced pitches**. The seven *natural* notes are
named with letters:

**A B C D E F G** — then it repeats.

The distance between two adjacent pitches is a **semitone** (one fret on a guitar). Two semitones make
a **tone** (a whole step). Between most letter names there is a tone, with two exceptions where the gap
is only a semitone: **B–C** and **E–F**.

## Sharps and flats

The five pitches that fall *between* the natural notes are named relative to their neighbours:

- A **sharp** (♯) raises a note by a semitone: C♯ is one semitone above C.
- A **flat** (♭) lowers a note by a semitone: D♭ is one semitone below D.

So C♯ and D♭ are the **same pitch** with two names — these are called **enharmonic equivalents**. Which
spelling you use depends on the key (more on that in *The circle of fifths*).

## The chromatic scale

Playing all twelve pitches in order gives the **chromatic scale**:

`C  C♯  D  D♯  E  F  F♯  G  G♯  A  A♯  B  (C)`

## Octaves

When you reach the twelfth semitone you arrive at a note with the **same name** as where you started,
but twice the frequency — an **octave** higher. A4 (the A above middle C) is defined as **440 Hz**;
the A an octave up is 880 Hz, an octave down 220 Hz. The ear hears octave-related notes as "the same
note, higher or lower", which is why they share a name.
""",
    ),
    dict(
        slug="intervals", title="Intervals",
        category="Foundations", category_order=FOUNDATIONS, order=2,
        widget="intervals", widget_arg=None,
        body="""# Intervals

An **interval** is the distance between two notes, measured in semitones. Intervals are the building
blocks of theory — scales and chords are just particular stacks of them.

## The intervals within an octave

| Semitones | Name | Quality |
|---|---|---|
| 0 | Unison | Perfect |
| 1 | Minor 2nd | Dissonant |
| 2 | Major 2nd | Mild |
| 3 | Minor 3rd | Consonant (minor) |
| 4 | Major 3rd | Consonant (major) |
| 5 | Perfect 4th | Consonant |
| 6 | Tritone | Most dissonant |
| 7 | Perfect 5th | Most consonant |
| 8 | Minor 6th | Consonant |
| 9 | Major 6th | Consonant |
| 10 | Minor 7th | Dissonant |
| 11 | Major 7th | Sharp/tense |
| 12 | Octave | Perfect |

## Consonance and dissonance

The **perfect 5th** (7 semitones) and the **major 3rd** (4) are the most restful intervals — they form
the major chord. The **tritone** (6 semitones, an augmented 4th / diminished 5th) is the most unstable
and *wants* to resolve; it's the engine of the dominant 7th chord.

## Why the names matter

The **3rd** decides whether a chord sounds major or minor. The **7th** colours dominant, major-7th and
minor-7th chords differently. Train your ear to recognise these and most harmony becomes audible at a
glance. Use the explorer below to play each interval against a root.
""",
    ),
    dict(
        slug="major-scale", title="The major scale",
        category="Foundations", category_order=FOUNDATIONS, order=3,
        widget="scales", widget_arg="major",
        body="""# The major scale

The **major scale** is the reference point for nearly all Western theory — every other scale and the
roman-numeral system are described relative to it. It's the familiar *do–re–mi–fa–sol–la–ti–do*.

## The formula

A major scale is built from a fixed pattern of **whole (W)** and **half (H)** steps:

**W – W – H – W – W – W – H**

Starting on C (which uses only natural notes):

`C – D – E – F – G – A – B – C`

Apply the same pattern from any note and you get that note's major scale. Starting on G:

`G – A – B – C – D – E – F♯ – G` (the F must be sharp to keep the pattern).

## Scale degrees

Each note has a **degree** number and a name:

| Degree | Name |
|---|---|
| 1 | Tonic |
| 2 | Supertonic |
| 3 | Mediant |
| 4 | Subdominant |
| 5 | Dominant |
| 6 | Submediant |
| 7 | Leading tone |

The **tonic** is home; the **dominant** (5th) creates the strongest pull back to it; the **leading
tone** (7th) sits a semitone below the tonic and leans into it. These tendencies drive melody and
harmony alike.
""",
    ),
    dict(
        slug="rhythm-note-values", title="Rhythm & note values",
        category="Foundations", category_order=FOUNDATIONS, order=4,
        widget=None, widget_arg=None,
        body="""# Rhythm & note values

Pitch is only half of music — **rhythm** organises sound in time. The basic pulse you tap your foot to
is the **beat**.

## Note durations

Durations are defined as fractions of a **whole note**, each one half the length of the previous:

| Note | British name | Beats (in 4/4) |
|---|---|---|
| Whole note | Semibreve | 4 |
| Half note | Minim | 2 |
| Quarter note | Crotchet | 1 |
| Eighth note | Quaver | ½ |
| Sixteenth note | Semiquaver | ¼ |

A **dot** after a note adds half its value again: a dotted half note = 3 beats. A **tie** joins two
notes into one sustained duration. **Rests** are silences with the same set of durations.

## Subdividing the beat

Counting subdivisions keeps you steady. One beat split into:

- **2** = eighth notes — count "1 & 2 & 3 & 4 &"
- **3** = triplets — "1-trip-let 2-trip-let"
- **4** = sixteenths — "1 e & a 2 e & a"

The practice tool's **notes-per-tick** setting plays exactly these subdivisions against the metronome,
so you can drill 2 or 4 notes per click.

## Tempo

**Tempo** is the speed of the beat in **beats per minute (BPM)**. 60 BPM is one beat per second; 120
BPM is two. Practising slowly and pushing the tempo up gradually is the fastest route to clean playing.
""",
    ),
    dict(
        slug="time-signatures", title="Time signatures",
        category="Foundations", category_order=FOUNDATIONS, order=5,
        widget=None, widget_arg=None,
        body="""# Time signatures

A **time signature** groups beats into repeating **bars** (measures). It's written as two stacked
numbers at the start of a piece:

- The **top number** = how many beats are in each bar.
- The **bottom number** = which note value gets one beat (4 = quarter note, 8 = eighth note).

## Common time signatures

- **4/4** — four quarter-note beats per bar. By far the most common; also written **C** ("common
  time"). Almost all pop, rock and blues.
- **3/4** — three quarter-note beats. The waltz feel: *ONE-two-three*.
- **2/4** — two beats; marches and polkas.
- **6/8** — six eighth notes, felt in **two** groups of three (*ONE-two-three FOUR-five-six*). A rolling,
  lilting feel — ballads, jigs.

## Simple vs compound

In **simple** metres (4/4, 3/4) each beat divides into **two**. In **compound** metres (6/8, 9/8, 12/8)
each beat divides into **three**. That triple subdivision is what gives 6/8 its distinctive bounce.

## Odd metres

Time signatures like **5/4** (*Take Five*) or **7/8** group beats unevenly — e.g. 7/8 as 2+2+3. They
feel lopsided and propulsive, common in prog and folk traditions.

The downbeat — beat 1 of each bar — is where the metronome in the practice tool plays an **accented
click**, so you always know where the bar begins.
""",
    ),

    # ----------------------------------------------------------------- Scales & Modes
    dict(
        slug="minor-scales", title="Minor scales (natural, harmonic, melodic)",
        category="Scales & Modes", category_order=SCALES, order=1,
        widget="scales", widget_arg="aeolian",
        body="""# Minor scales

Where the major scale sounds bright, the **minor** scales sound darker or sadder. There are three
related forms, all sharing a flattened 3rd (♭3) — the note that makes a scale *minor*.

## Natural minor

The **natural minor** scale (also called the Aeolian mode) has the formula:

**W – H – W – W – H – W – W**

In A: `A – B – C – D – E – F – G – A`. Note it contains exactly the same notes as C major — it's C
major's **relative minor** (see *The circle of fifths*).

Scale degrees relative to major: **1 2 ♭3 4 5 ♭6 ♭7**.

## Harmonic minor

The natural minor's 7th sits a whole tone below the tonic, which makes a weak ending. Raising it back
up a semitone gives the **harmonic minor** (**1 2 ♭3 4 5 ♭6 7**). This restores a strong leading tone
so the V chord becomes major/dominant — but it opens a tense gap of three semitones between ♭6 and 7,
giving that distinctive exotic, classical/flamenco colour.

## Melodic minor

To smooth out that gap, the **melodic minor** also raises the 6th: **1 2 ♭3 4 5 6 7**. Classically it's
played raised when ascending and reverts to natural minor descending; in jazz the raised form is used
both ways ("jazz minor"). It's a minor tonality with an almost major-bright top.
""",
    ),
    dict(
        slug="modes-overview", title="The modes (overview)",
        category="Scales & Modes", category_order=SCALES, order=2,
        widget="scales", widget_arg="major",
        body="""# The modes

The seven **modes** are what you get by playing the major scale but treating a **different degree as
home**. Same seven notes, different centre of gravity — and therefore a different mood.

Starting all modes from the white notes of C major makes this clear:

| Mode | Start note | Quality | Character |
|---|---|---|---|
| Ionian (major) | C | Major | Bright, resolved |
| Dorian | D | Minor | Minor but hopeful |
| Phrygian | E | Minor | Dark, Spanish |
| Lydian | F | Major | Dreamy, floating |
| Mixolydian | G | Major | Bluesy, dominant |
| Aeolian (minor) | A | Minor | Sad, natural minor |
| Locrian | B | Diminished | Unstable |

## Two ways to think about modes

1. **Derivative** (above): D Dorian = the notes of C major from D. Easy to *find*.
2. **Parallel**: compare each mode to the major or minor scale **on the same root**. This is how you
   *hear* a mode. D Dorian vs D minor: Dorian raises the 6th. That single **characteristic note** is
   what your ear latches onto.

## The characteristic note

Each mode has one note that defines its flavour:

- **Lydian** — the ♯4
- **Mixolydian** — the ♭7
- **Dorian** — the natural 6 (in a minor scale)
- **Phrygian** — the ♭2
- **Locrian** — the ♭5

Lean on that note over a static chord and the mode sings. The individual mode pages go deeper on each.
""",
    ),
    dict(
        slug="dorian", title="Dorian mode",
        category="Scales & Modes", category_order=SCALES, order=3,
        widget="scales", widget_arg="dorian",
        body="""# Dorian mode

**Dorian** is a **minor** mode — it has the ♭3 — but with a **major 6th**, where natural minor has a
♭6. That single raised note lifts the darkness, giving Dorian its hopeful, soulful, "minor but not
sad" quality.

Formula relative to major: **1 2 ♭3 4 5 6 ♭7**

D Dorian (the white notes from D): `D – E – F – G – A – B – C – D`.

## The sound

Compared to natural minor, the natural 6th brightens the iv chord into a **major IV** and lets melodies
reach up without resolving downward. It feels groovy and open rather than mournful.

## Where you hear it

Funk, modal jazz (*So What*, *Impressions*), Santana-style Latin rock, Celtic and folk tunes, and
countless minor-key grooves. A static **i – IV** vamp (e.g. Dm – G) is the classic way to establish
Dorian, because the major IV reveals the natural 6th.

Try soloing the Dorian shape below over a minor vamp and target that 6th to hear the mode's signature.
""",
    ),
    dict(
        slug="phrygian", title="Phrygian mode",
        category="Scales & Modes", category_order=SCALES, order=4,
        widget="scales", widget_arg="phrygian",
        body="""# Phrygian mode

**Phrygian** is a **minor** mode with a **flat 2nd (♭2)** — a semitone right above the root. That ♭2 is
its defining sound: dark, tense and unmistakably Spanish/flamenco, and a staple of metal.

Formula relative to major: **1 ♭2 ♭3 4 5 ♭6 ♭7**

E Phrygian (white notes from E): `E – F – G – A – B – C – D – E`.

## The sound

The semitone between root and ♭2 creates a heavy, exotic pull. Built into a chord, the root major chord
with a ♭2 above gives the "Phrygian dominant" flavour heard in flamenco when the 3rd is raised.

## Phrygian dominant

Raise Phrygian's ♭3 to a major 3rd and you get the **Phrygian dominant** (the 5th mode of harmonic
minor): **1 ♭2 3 4 5 ♭6 ♭7**. This is *the* flamenco/Middle-Eastern scale, and the sound of a V chord
in a minor key.

## Where you hear it

Flamenco, metal (the ♭2 riff), film scores reaching for menace or the exotic. A droning root with the
♭2 leaning into it is the quickest way to summon Phrygian.
""",
    ),
    dict(
        slug="lydian", title="Lydian mode",
        category="Scales & Modes", category_order=SCALES, order=5,
        widget="scales", widget_arg="lydian",
        body="""# Lydian mode

**Lydian** is a **major** mode with one alteration: a **sharp 4th (♯4)**. It's the brightest of all the
modes — major already, then lifted further by that raised, floating fourth.

Formula relative to major: **1 2 3 ♯4 5 6 7**

F Lydian (white notes from F): `F – G – A – B – C – D – E – F`.

## The sound

In the plain major scale the natural 4th wants to fall to the 3rd. Raising it removes that pull, so
Lydian feels weightless and dreamy — wonder, magic, wide-open space. The ♯4 is the same tritone above
the root that makes the sound shimmer rather than resolve.

## Where you hear it

Film and TV scores (think the dreamy, "looking up at the stars" cue — a Lydian signature of composers
like John Williams and Joe Hisaishi), fusion, and progressive rock. A static **Imaj7 – II** vamp
(e.g. Cmaj7 – D) keeps the ♯4 ringing.
""",
    ),
    dict(
        slug="mixolydian", title="Mixolydian mode",
        category="Scales & Modes", category_order=SCALES, order=6,
        widget="scales", widget_arg="mixolydian",
        body="""# Mixolydian mode

**Mixolydian** is a **major** mode with a **flat 7th (♭7)**. It keeps the major 3rd's brightness but
swaps the tense leading tone for the relaxed, bluesy ♭7 — the sound of dominant 7th chords, blues-rock
and jam bands.

Formula relative to major: **1 2 3 4 5 6 ♭7**

G Mixolydian (white notes from G): `G – A – B – C – D – E – F – G`.

## The sound

The ♭7 means the tonic chord is a **dominant 7th** (G7), and the scale no longer pulls hard toward a
resolution — so it can sit on one chord indefinitely. That's why it's perfect for grooves and riffs
that stay put.

## Where you hear it

Blues and rock riffs, *Sweet Home Alabama* / *Sweet Child o' Mine*-style vamps, the Grateful Dead and
jam bands, Irish and folk tunes, and any dominant-7th groove. A **I – ♭VII – IV** progression
(e.g. G – F – C) is pure Mixolydian because the ♭VII is built from that flat 7th.
""",
    ),
    dict(
        slug="aeolian", title="Aeolian mode (natural minor)",
        category="Scales & Modes", category_order=SCALES, order=7,
        widget="scales", widget_arg="aeolian",
        body="""# Aeolian mode

**Aeolian** *is* the **natural minor scale** — the default "sad" sound and the relative minor of every
major key. As a mode, it's the major scale started from its 6th degree.

Formula relative to major: **1 2 ♭3 4 5 ♭6 ♭7**

A Aeolian (white notes from A): `A – B – C – D – E – F – G – A` — the same notes as C major, centred on
A.

## The sound

The ♭3 makes it minor; the ♭6 and ♭7 keep everything dark and grounded. Unlike harmonic minor, the ♭7
gives a **minor v** chord, so it lacks a strong leading-tone pull — restful and melancholic rather than
dramatic.

## Aeolian vs Dorian vs Phrygian

All three are minor modes; the difference is one note each:

- **Aeolian** — the baseline natural minor (♭6, ♭7).
- **Dorian** — Aeolian with a **natural 6**.
- **Phrygian** — Aeolian with a **♭2**.

## Where you hear it

Vast amounts of minor-key pop, rock and metal. The **i – ♭VI – ♭III – ♭VII** loop (e.g. Am – F – C – G)
is the anthemic Aeolian progression behind countless songs.
""",
    ),
    dict(
        slug="locrian", title="Locrian mode",
        category="Scales & Modes", category_order=SCALES, order=8,
        widget="scales", widget_arg="locrian",
        body="""# Locrian mode

**Locrian** is the darkest and least-used mode. It's minor (♭3) but also has a **♭2 and a ♭5**, and that
flattened fifth makes its tonic chord a **diminished triad** — which can't provide a stable home. So
Locrian is mostly a colour, not a key.

Formula relative to major: **1 ♭2 ♭3 4 ♭5 ♭6 ♭7**

B Locrian (white notes from B): `B – C – D – E – F – G – A – B`.

## Why it's unstable

The 5th is the note that anchors a tonal centre. With the 5th flattened, the root chord (B–D–F) is
diminished and **dissonant by nature** — the ear never feels "at rest", so it's hard to write a tune
that lives in Locrian.

## Where it's actually used

Most often as the sound of the **vii°** (or **ii°** in minor) chord passing through a progression, and
over **half-diminished (m7♭5)** chords — which are exactly Locrian harmony. Some metal and experimental
music exploits its instability deliberately. Treat it as a flavour for tension rather than a home base.
""",
    ),
    dict(
        slug="pentatonic-scales", title="Pentatonic scales",
        category="Scales & Modes", category_order=SCALES, order=9,
        widget="scales", widget_arg="minor_pentatonic",
        body="""# Pentatonic scales

**Pentatonic** scales have just **five notes** per octave. By dropping the two most dissonant notes of
the seven-note scale, they remove nearly every chance of a clashing note — which is why they're the
go-to scales for soloing and the first ones most guitarists learn.

## Minor pentatonic

The **minor pentatonic** is the natural minor scale minus the 2nd and ♭6:

**1 ♭3 4 5 ♭7**

A minor pentatonic: `A – C – D – E – G`. This is the bedrock of rock and blues lead guitar.

## Major pentatonic

The **major pentatonic** is the major scale minus the 4th and 7th:

**1 2 3 5 6**

C major pentatonic: `C – D – E – G – A`. Brighter and sweeter — country, folk, and major-key solos.

## The shared shape

A major pentatonic and its **relative minor** pentatonic contain the **same five notes** (C major
pentatonic = A minor pentatonic). So one fretboard shape covers both — you just shift which note you
treat as home. Learning the five connected "boxes" of this shape unlocks the whole neck.

## The blues connection

Add one chromatic passing note (the ♭5) to the minor pentatonic and you get the **blues scale** — see
its own page.
""",
    ),
    dict(
        slug="blues-scale", title="The blues scale",
        category="Scales & Modes", category_order=SCALES, order=10,
        widget="scales", widget_arg="blues",
        body="""# The blues scale

The **blues scale** is the minor pentatonic with one extra chromatic note — the **♭5**, the famous
**"blue note"** — slotted between the 4th and 5th:

**1 ♭3 4 ♭5 5 ♭7**

A blues scale: `A – C – D – E♭ – E – G`.

## The blue note

That ♭5 is dissonant on paper, but as a quick **passing tone** — slid or bent into the 4th or 5th — it
delivers the grit and vocal "cry" at the heart of blues. It's rarely landed on; it's a note you move
*through*.

## Major blues

There's also a **major blues scale** — the major pentatonic with an added ♭3 passing tone
(**1 2 ♭3 3 5 6**) — which gives a sweeter, more rolling country-blues sound.

## How to use it

Play it over a **12-bar blues** (see *Common chord progressions*). Crucially, the same minor blues
scale works over the **whole** progression — all three dominant chords (I7, IV7, V7) — which is what
makes it so forgiving. Mix in bends, slides and the blue note for expression rather than running the
scale straight.
""",
    ),

    # ----------------------------------------------------------------- Chords & Harmony
    dict(
        slug="triads", title="Triads",
        category="Chords & Harmony", category_order=HARMONY, order=1,
        widget="chords", widget_arg="maj",
        body="""# Triads

A **triad** is a three-note chord built by stacking two **thirds** — a root, a third, and a fifth. The
qualities of those thirds determine the chord's flavour.

## The four triad types

| Triad | Intervals from root | Formula | Sound |
|---|---|---|---|
| **Major** | major 3rd + minor 3rd | 1 3 5 | Bright, happy |
| **Minor** | minor 3rd + major 3rd | 1 ♭3 5 | Dark, sad |
| **Diminished** | minor 3rd + minor 3rd | 1 ♭3 ♭5 | Tense, unstable |
| **Augmented** | major 3rd + major 3rd | 1 3 ♯5 | Dreamlike, restless |

The **third** is the note that flips a chord between major and minor; the **fifth** anchors it.
Diminished and augmented triads alter that fifth (♭5 / ♯5), which is why they sound unsettled.

## Suspended chords

A **sus** chord replaces the third with a neighbour: **sus2** (1 2 5) or **sus4** (1 4 5). With no third
they're neither major nor minor — open and ringing, often resolving back to a normal triad.

## Building them in a key

Stack thirds on each degree of a scale using only that scale's notes and you get the **diatonic triads**
of the key — see *Diatonic chords & roman numerals*. Use the explorer below to see and hear each triad
across the fretboard, and try its inversions.
""",
    ),
    dict(
        slug="seventh-chords", title="Seventh chords",
        category="Chords & Harmony", category_order=HARMONY, order=2,
        widget="chords", widget_arg="maj7",
        body="""# Seventh chords

Stack **one more third** on top of a triad and you get a **seventh chord** — a four-note chord with a
richer, more coloured sound. The 7th is what gives jazz, soul and R&B their lushness.

## The main seventh chords

| Chord | Symbol | Formula | Sound |
|---|---|---|---|
| Major 7th | maj7 | 1 3 5 7 | Lush, dreamy |
| Dominant 7th | 7 | 1 3 5 ♭7 | Bluesy, wants to resolve |
| Minor 7th | m7 | 1 ♭3 5 ♭7 | Smooth, mellow |
| Half-diminished | m7♭5 | 1 ♭3 ♭5 ♭7 | Dark, jazzy tension |
| Diminished 7th | dim7 | 1 ♭3 ♭5 ♭♭7 | Maximum tension |

## The all-important dominant 7th

The **dominant 7th** (e.g. G7) contains a **tritone** between its 3rd and ♭7. That tritone is unstable
and resolves powerfully to the tonic — making the dominant 7th the strongest "take me home" chord in
tonal music, and the V chord of every key.

## Major 7th vs dominant 7th

Just one note apart (natural 7 vs ♭7), but worlds apart in feel: **maj7** is restful and floating,
**7** is tense and bluesy. Hearing that difference is a big step in training your harmonic ear.
""",
    ),
    dict(
        slug="chord-inversions", title="Chord inversions",
        category="Chords & Harmony", category_order=HARMONY, order=3,
        widget="chords", widget_arg="maj",
        body="""# Chord inversions

A chord is the same chord no matter which of its notes is in the bass. **Inverting** a chord means
putting a note other than the root at the bottom — same notes, different voicing.

## The inversions of a triad

For a C major triad (C–E–G):

| Position | Bass note | Notes (low→high) |
|---|---|---|
| **Root position** | C (root) | C E G |
| **1st inversion** | E (3rd) | E G C |
| **2nd inversion** | G (5th) | G C E |

A seventh chord has a **3rd inversion** as well, with the 7th in the bass.

## Why inversions matter

- **Smooth voice leading** — moving between chords with minimal motion. Instead of jumping the bass
  around, you pick the inversion whose notes are closest to the next chord, so lines glide.
- **Bass lines** — inversions let the bass walk stepwise (a "slash chord" like **C/E** means a C chord
  with E in the bass).
- **Voicing colour** — the same chord sounds more open or more compact depending on its inversion.

On guitar, every chord shape is really an inversion/voicing decision. The explorer's **inversion
stepper** below cycles root → 1st → 2nd so you can hear how the bass note changes the character while
the chord's identity stays the same.
""",
    ),
    dict(
        slug="extended-altered-chords", title="Extended & altered chords",
        category="Chords & Harmony", category_order=HARMONY, order=4,
        widget="chords", widget_arg="dom7",
        body="""# Extended & altered chords

Keep stacking thirds past the 7th and you reach the **extensions** — the 9th, 11th and 13th. These are
the same notes as the 2nd, 4th and 6th, but an octave up, and they add colour without changing the
chord's basic function.

## Extensions

| Chord | Adds | Typical use |
|---|---|---|
| 9th (e.g. C9, Cmaj9, Cm9) | the 9th (= 2nd) | Lush, soulful |
| 11th | the 11th (= 4th) | Suspended, airy |
| 13th | the 13th (= 6th) | Full, jazzy dominant |

A **maj9** is dreamy; a **m9** is smooth and neo-soul; a **13** chord is the big band dominant sound. You
rarely play every note — guitarists drop the 5th (and often the root) and keep the colour tones.

## Add chords

An **add9** (1 3 5 9) adds the 9th **without** the 7th — so it's a triad plus colour, not a full
extended chord. Bright and modern (think jangly pop).

## Altered dominants

On a **dominant** chord you can sharpen or flatten the 5th and 9th to crank up tension before a
resolution: **7♭9, 7♯9** (the "Hendrix chord"), **7♯5, 7♭5**, or the catch-all **7alt**. These extra
dissonances make the pull to the tonic even stronger and are the spice of jazz and funk.
""",
    ),
    dict(
        slug="power-chords-voicings", title="Power chords & guitar voicings",
        category="Chords & Harmony", category_order=HARMONY, order=5,
        widget=None, widget_arg=None,
        body="""# Power chords & guitar voicings

## Power chords

A **power chord** ("5 chord", e.g. **E5**) is just the **root and 5th** — no third. With no third it's
**neither major nor minor**, which is exactly why it works under heavy distortion: thirds clash and
sound muddy when overdriven, but the bare root–fifth (often plus the octave) stays clean and powerful.

A power chord is two or three notes: **1 – 5 – (1)**. The same two-finger shape slides anywhere on the
6th or 5th string, so it's movable and fast — the engine of punk, rock and metal riffs.

## Open vs barre chords

- **Open chords** use unfretted (open) strings — the first shapes you learn (E, A, D, G, C). They ring
  brightly but are tied to specific keys.
- **Barre chords** lay one finger across all six strings to form a movable "nut", letting you shift an
  open shape (E or A) up the neck to any key. Harder to fret, but they unlock every chord.

## Voicing on guitar

A six-string instrument can't always play a chord's notes in textbook order, so guitarists use
**voicings** — practical fingerings that may double, omit (commonly the 5th) or reorder notes. The same
C chord has dozens of voicings up the neck, each with a different thickness and brightness. The **CAGED
system** (see the Guitar section) is the map of how those voicings connect.
""",
    ),
    dict(
        slug="diatonic-roman-numerals", title="Diatonic chords & roman numerals",
        category="Chords & Harmony", category_order=HARMONY, order=6,
        widget="keys", widget_arg=None,
        body="""# Diatonic chords & roman numerals

Build a triad on **each degree** of a scale using only the notes of that scale, and you get the seven
**diatonic chords** — the chords that naturally "belong together" in a key. Almost every song is built
from them.

## Roman numerals

Chords are labelled with **roman numerals** so a progression can be described independently of key:

- **UPPERCASE** = major (I, IV, V)
- **lowercase** = minor (ii, iii, vi)
- **°** = diminished (vii°)

### Major key

| Degree | I | ii | iii | IV | V | vi | vii° |
|---|---|---|---|---|---|---|---|
| Quality | maj | min | min | maj | maj | min | dim |

In C major: **C  Dm  Em  F  G  Am  B°**.

### Minor key

| Degree | i | ii° | III | iv | v | VI | VII |
|---|---|---|---|---|---|---|---|
| Quality | min | dim | maj | min | min | maj | maj |

In A minor: **Am  B°  C  Dm  Em  F  G**.

## Chord function

Three "jobs" drive harmony: **Tonic** (I/vi — home, rest), **Subdominant** (IV/ii — motion away), and
**Dominant** (V/vii° — tension demanding resolution to the tonic). Understanding which numeral does
which is the key to writing and transposing progressions — and it's why the practice tool stores
progressions as roman numerals, so they work in **any** key. The explorer below shows the diatonic
chords for whatever key you choose.
""",
    ),
    dict(
        slug="circle-of-fifths", title="The circle of fifths",
        category="Chords & Harmony", category_order=HARMONY, order=7,
        widget="keys", widget_arg=None,
        body="""# The circle of fifths

The **circle of fifths** arranges the twelve keys so that each step **clockwise** moves up a **perfect
5th** — and adds one **sharp** to the key signature. Each step **counter-clockwise** moves up a 4th and
adds one **flat**. It's the single most useful map in music.

## The layout

Starting at the top with **C major** (no sharps or flats) and going clockwise:

`C → G → D → A → E → B → F♯ → … → F → C`

- Clockwise (sharps): G (1♯), D (2♯), A (3♯), E (4♯), B (5♯)…
- Counter-clockwise (flats): F (1♭), B♭ (2♭), E♭ (3♭), A♭ (4♭)…

## What it tells you

- **Key signatures** — how many sharps or flats any key has, at a glance.
- **Relative minors** — each major key shares its signature with the minor key a **minor 3rd below**
  (its relative minor): C major / A minor, G major / E minor, and so on.
- **Closely related keys** — neighbours on the circle differ by only one note, so modulating between
  them sounds smooth.

## Why "fifths" power harmony

Movement by a 5th (or its inverse, a 4th) is the strongest root motion in music — it's the V → I
resolution. Many progressions are just journeys **around the circle**: the classic jazz turnaround
**iii – vi – ii – V – I** walks four steps counter-clockwise straight home.
""",
    ),
    dict(
        slug="cadences", title="Cadences",
        category="Chords & Harmony", category_order=HARMONY, order=8,
        widget="progressions", widget_arg="I-IV-V",
        body="""# Cadences

A **cadence** is a chord progression that ends a phrase — musical punctuation. It tells the ear whether
the music has come to rest, paused, or been pleasantly surprised.

## The four main cadences

| Cadence | Motion | Effect |
|---|---|---|
| **Authentic (perfect)** | **V → I** | Full stop. Conclusive, "the end". |
| **Plagal** | **IV → I** | The "Amen" cadence — gentle, settled. |
| **Half** | ends on **V** | A comma — unfinished, asks a question. |
| **Deceptive** | **V → vi** | A surprise — sets up resolution then dodges it. |

## Authentic cadence

**V → I** is the strongest resolution in tonal music, driven by the dominant chord's tritone collapsing
into the tonic. A **perfect authentic cadence** (both chords in root position, melody landing on the
tonic) is the most final-sounding of all.

## Half cadence

Ending a phrase on **V** leaves things hanging — the music *expects* a continuation. Think of the first
half of a verse that pauses on the dominant before answering itself.

## Deceptive cadence

The ear is primed for V → I, but the music goes **V → vi** instead. Same bass-note neighbourhood, but
minor and unresolved — a favourite for extending a phrase or adding poignancy before the *real* ending.

Cadences are why progressions feel like sentences. Listen for them and song structure becomes obvious.
""",
    ),
    dict(
        slug="common-progressions", title="Common chord progressions",
        category="Chords & Harmony", category_order=HARMONY, order=9,
        widget="progressions", widget_arg="I-V-vi-IV",
        body="""# Common chord progressions

A handful of progressions underpin a huge share of popular music. Because they're written as roman
numerals, each one works in **any** key — pick a key and the chords come along for the ride.

## The essentials

- **I – IV – V** — the three primary chords. Blues, folk, early rock and roll. Everything else is
  decoration on this.
- **I – V – vi – IV** — the "four-chord song". Endless pop hits (e.g. C – G – Am – F). Starting the same
  loop on the vi gives **vi – IV – I – V**, a more wistful spin.
- **I – vi – IV – V** — the **'50s doo-wop** progression (*Stand By Me*).
- **ii – V – I** — the fundamental **jazz cadence**. The ii sets up the V, which resolves home; chain
  several to move through keys.
- **12-bar blues** — `I7 I7 I7 I7 | IV7 IV7 I7 I7 | V7 IV7 I7 V7`. The backbone of blues and rock, all
  dominant 7ths.

## Minor-key staples

- **i – ♭VI – ♭III – ♭VII** — the anthemic minor-rock loop (Am – F – C – G).
- **i – ♭VII – ♭VI – V** — the **Andalusian cadence**, a descending flamenco/rock line where the final
  **V is major** (borrowed from harmonic minor).

## Make them your own

Vary the **rhythm**, **inversions** and **voicings** and the same four chords sound brand new. Load any
of these into the practice tool to loop them under a metronome and drill your changes.
""",
    ),
    dict(
        slug="secondary-dominants", title="Secondary dominants",
        category="Chords & Harmony", category_order=HARMONY, order=10,
        widget="progressions", widget_arg="ii-V-I",
        body="""# Secondary dominants

A **secondary dominant** borrows the powerful **V → I** pull and aims it at a chord **other than** the
tonic — temporarily treating that chord as a mini "home" to spotlight it.

## The idea

Every major or minor chord has its own dominant (the chord a 5th above it). If you precede a diatonic
chord with *its* dominant, you get a stronger, more colourful approach. These are labelled **V/x**
("five of x"):

- **V/V** — the dominant of the dominant. In C major, that's **D7** leading to G. (D7 introduces an
  F♯, a note outside the key — the giveaway of a secondary dominant.)
- **V/vi** — in C, **E7** leading to Am.
- **V/ii**, **V/IV**, etc.

## Why it works

A diatonic chord built on the 2nd degree is **minor** (Dm in C). Make it **major/dominant** (D7) and its
new 3rd (F♯) becomes a leading tone into G — borrowing the dominant's resolving energy. The chord is
"tonicised" without actually changing key.

## Hearing it

That brief out-of-key note creates a momentary lift and a stronger gravitational pull to the target
chord. Ragtime, jazz and the Beatles are full of them (e.g. the **I – V/V – V** move). They're the
easiest way to add sophistication to a plain diatonic progression.
""",
    ),
    dict(
        slug="modal-interchange", title="Modal interchange (borrowed chords)",
        category="Chords & Harmony", category_order=HARMONY, order=11,
        widget="progressions", widget_arg="minor-i-VI-III-VII",
        body="""# Modal interchange (borrowed chords)

**Modal interchange** (or *borrowing*) means using chords from a **parallel** key or mode — the scale
with the **same root** but a different quality. It's the most common way to add unexpected colour while
staying centred on the same tonic.

## Borrowing from parallel minor

The richest source is the parallel minor. In a **major** key you can borrow:

- **♭VII** — from Mixolydian/minor (in C: **B♭**). The rock "flat-seven".
- **♭VI** — (in C: **A♭**). Dramatic, cinematic.
- **iv** — the **minor four** (in C: **Fm**). A gorgeous, bittersweet substitute for the major IV —
  beloved in pop ballads (the "Creep" / "Radiohead" chord move I – III – IV – iv).
- **♭III** and **ii°**.

## Why it works

The tonic stays the same, so your ear keeps its bearings — but a chord arrives with a note from outside
the key, creating a momentary shift in mood (usually a darkening). Because the root note is unchanged,
it feels like a *colour* rather than a *modulation*.

## Hearing it

Listen for a major-key song that suddenly leans dark for one chord and then brightens again — that's
almost always a borrowed minor chord. **I – ♭VII – IV** (Mixolydian borrowing) and the **major-to-minor
IV** are the two you'll spot most often.
""",
    ),

    # ----------------------------------------------------------------- Guitar
    dict(
        slug="fretboard-notes", title="The fretboard & note names",
        category="Guitar", category_order=GUITAR, order=1,
        widget="scales", widget_arg="major",
        body="""# The fretboard & note names

Learning where the notes live on the neck is the single biggest unlock for a guitarist. The fretboard
looks daunting, but it's built from simple, repeating logic.

## Standard tuning

From the **lowest** (thickest) string to the highest, standard tuning is:

**E – A – D – G – B – E**

Each fret raises the pitch by **one semitone**. So on the low E string: open = E, 1st fret = F, 2nd =
F♯, 3rd = G, and so on up the chromatic scale.

## Landmarks and the octave

A few facts make navigation easy:

- The **12th fret** is one octave above the open string — the note names repeat from there.
- Natural semitones (no sharp between) occur at **B–C** and **E–F**, so those notes are only one fret
  apart.
- The **5th fret** of one string usually matches the **open** next string up (the basis of 5-fret
  tuning) — except the **G→B** pair, which matches at the **4th** fret.

## Octave shapes

The fastest way to find a note anywhere: learn the **octave shapes**. From any note on the 6th string,
the same note an octave up sits **two strings over and two frets up**. These movable shapes let you map
one known note across the whole neck without memorising all 72 positions individually.

Use the explorer below to switch tunings and see how the note positions shift.
""",
    ),
    dict(
        slug="caged-system", title="The CAGED system",
        category="Guitar", category_order=GUITAR, order=2,
        widget="chords", widget_arg="maj",
        body="""# The CAGED system

**CAGED** is a system for visualising the entire fretboard using five chord shapes you already know. The
name is the five open major-chord shapes: **C – A – G – E – D**.

## The core idea

Any chord can be played in **five places** up the neck, each based on one of those five open shapes made
movable (barred). The five shapes **connect** — the top of one shape is the bottom of the next — so
together they tile the whole neck without gaps.

For example, a **C major** chord can be played as:

- the open **C** shape (around the 1st fret),
- an **A** shape barred at the 3rd fret,
- a **G** shape at the 5th,
- an **E** shape at the 8th,
- a **D** shape at the 10th,

…all the same C chord, climbing the neck in CAGED order.

## Why it's useful

- **Scales** map onto the same five zones — each CAGED shape has a matching scale/pentatonic "box", so
  your chords and your soloing positions line up.
- **Arpeggios** — the chord tones inside each shape show you exactly where the "safe" target notes are.
- **Navigation** — instead of seeing a wall of frets, you see five linked shapes.

It takes time to internalise, but CAGED turns the fretboard from a grid of dots into five familiar,
connected pictures. Use the chord explorer to see how a shape's notes lie across the strings.
""",
    ),
    dict(
        slug="alternate-tunings", title="Alternate tunings",
        category="Guitar", category_order=GUITAR, order=3,
        widget="scales", widget_arg="major",
        body="""# Alternate tunings

Re-tuning the strings changes the chord shapes under your fingers and the resonances of the instrument —
opening up sounds that are awkward or impossible in standard tuning.

## Drop tunings

- **Drop D** — lower the 6th string from E to **D**. Now the lowest three strings make a **power chord
  with one finger**, and you gain a low D for heavier riffs. The rest of the neck is unchanged.
- **Drop C** (and lower) — Drop D taken down further for metal: heavier, slacker strings.

## Lowered tunings

- **Half-step down (E♭)** — every string down one semitone. Slightly darker, easier to bend, and kinder
  to singers. Used by Hendrix, SRV and many rock acts.

## Open tunings

Tune the open strings to a **chord**, so strumming open gives that chord and a barre across any fret
gives another — the foundation of **slide guitar**:

- **Open G** (D–G–D–G–B–D) and **Open D** (D–A–D–F♯–A–D) are the classics.
- **DADGAD** — a modal, suspended tuning (neither major nor minor) loved in Celtic and fingerstyle
  playing for its ringing, droning open strings.

## Practical notes

Alternate tunings move all the note positions, so your memorised shapes shift. The practice tool's
**tuning selector** re-maps the fretboard diagram for any of these, so you can see exactly where scales
and chords fall before you commit them to muscle memory.
""",
    ),
]
