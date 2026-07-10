# Rename research: retiring "wigamig" — candidate names + rationale

**Date:** 2026-07-07
**Requested by:** centre leadership (via main session), non-Indigenous
**Status:** advisory research — not a decision

## 1. Etymology check

"wigamig" is a variant spelling of Ojibwe **wiigiwaam** (wigwam), from
Algonquian root *wik-/wig-* = "to dwell," literally close to "their
house/dwelling." It denotes the domed or pointed bark-and-sapling
lodge historically built by Anishinaabe and related peoples, still
used today for ceremonial purposes — i.e., it is not a dead/generic
loanword like "canoe" or "moccasin" that has fully entered general
English; it names a specific, still-living structure tied to
Anishinaabe material and ceremonial culture.

Sources: [Ojibwe People's Dictionary — wiigiwaam](https://ojibwe.lib.umn.edu/main-entry/wiigiwaam-ni),
[Wigwam — Wikipedia](https://en.wikipedia.org/wiki/Wigwam),
[Wigwam — Etymonline](https://www.etymonline.com/word/wigwam),
[Wigwam — Canadian Encyclopedia](https://www.thecanadianencyclopedia.ca/en/article/wigwam),
[Kiinawin Kawindomowin / Story Nations — Wigwam](https://storynations.utoronto.ca/index.php/wig-wam/).

**Verdict on the concern:** justified. The leadership's read is
correct — a non-Indigenous team branding infrastructure with an
Anishinaabe word for a living ceremonial dwelling, with no
relationship to or consent from an Anishinaabe community, and no
benefit flowing back, fits the standard definition of appropriation
even though the "village of collaborating agents" metaphor is a
reasonable *reason* someone reached for the word.

## 2. Practice scan — how the field handles this

- **Cautionary precedent inside software naming itself:** the
  "Tomahawk" Node.js web server and the "Hiawatha" web server are
  cited examples of Indigenous-word/imagery branding adopted with no
  Indigenous involvement, in one case paired with racist cartoon
  branding. (Geek Feminism Wiki, cultural appropriation entry.)
- **The legitimate alternative — co-creation, not solo borrowing:**
  **Mukurtu CMS** is held up as the ethical counter-example: a digital
  heritage platform built *with* Indigenous communities from the
  start, governed by Indigenous protocols for what can be seen by
  whom. The naming/branding is a consequence of an actual, ongoing
  relationship, not a metaphor lifted from a dictionary.
  ([mukurtu.org](https://mukurtu.org/), [Humanities for All writeup](https://humanitiesforall.org/projects/mukurtu-an-indigenous-archive-and-publishing-tool))
- **Underlying ethical framework:** "Free, Prior and Informed Consent"
  (FPIC) is the standard repeatedly invoked for using
  Indigenous cultural/linguistic material — consent from the specific
  community, obtained before use, with adequate information about how
  it will be used. Absent that, use is appropriation regardless of
  the namer's intent. (Cultural Survival; UW research on open-source
  cultural misrecognition — [ResearchGate](https://www.researchgate.net/publication/297386532_Do_not_do_unto_others_Cultural_misrecognition_and_the_harms_of_appropriation_in_an_open-source_world),
  [UW Anthropology](https://anthropology.washington.edu/research/publications/do-not-do-unto-others-cultural-misrecognition-and-harms-appropriation-open))
- **General naming-ethics literature** (less software-specific, thinner
  evidence base): recommends favoring neutral/technical or
  already-shared-commons vocabulary (Greco-Latin scientific roots,
  invented coinages, functional metaphors) over borrowing from any
  specific living culture without relationship, and weighing historical
  power asymmetry, not just literal translation accuracy. (Geography
  Compass review of colonial place-naming; "Decolonizing Our Names in
  the 21st Century," Beck & Gomashie, Routledge 2024 — book-level
  treatment, not fully verified beyond publisher listing, flagged as
  lower-confidence.)

**Caveat on evidence depth:** the software-specific literature here is
thin — mostly wiki/blog-level commentary (Geek Feminism) plus one
anthropology paper, rather than a large peer-reviewed corpus. Treat the
practice scan as directionally solid but not exhaustively cited.

## 3. The line leadership should hold

| Mode | What it looks like | Verdict for this project |
|---|---|---|
| **(a) Respectful metaphor the namers have a right to** | Drawing on Greco-Latin scientific commons vocabulary, general-English words, or invented coinages that don't index a specific living culture's closed/sacred material | Available and low-risk — this is where the candidates below live |
| **(b) Genuine co-creation** | Approaching a specific Anishinaabe (or other) community, asking if they'd want to be named partners, agreeing on a word *with* consent, relationship, and reciprocal benefit (FPIC) | Legitimate *if* leadership wants to pursue an Indigenous concept — but it is a relationship-building project, not a naming exercise, and shouldn't be done retroactively just to justify "wigamig" |
| **(c) Extraction** | Taking a sacred/living-culture word or concept because it "sounds good" or fits a metaphor, with no relationship, consent, or benefit-sharing | What "wigamig" currently is, unintentionally — this is what's being retired |

Recommendation: don't try to retrofit (b) onto the current name. If the
centre later wants a real Indigenous-language name, that should be its
own initiative (community relationship first, name second — never the
reverse).

## 4. Candidate names

| Candidate | Root / metaphor | Fit for the software | Origin | Appropriation risk |
|---|---|---|---|---|
| **Commonwealth** *(as component; avoid as sole name — colonial/political baggage)* | Latin *commune* + *wealth*/"weal" (public good) | Names the "commons" concept directly | English, but "Commonwealth" carries British-imperial political connotations | Not cultural appropriation, but flagged for a *different* colonial connotation — probably rule out as standalone |
| **Agora** | Greek ἀγορά — open assembly/marketplace, self-governing public space | Strong fit: a shared commons where autonomous members convene by choice, no central ruler | Ancient Greek, long absorbed into English/scientific/civic vocabulary (already used broadly: "Agora" is used by many orgs) | Low — dead/classical language, no living community it extracts from, but check for name collisions (e.g., existing "Agora" projects) |
| **Commons** (plain word, e.g. "The Commons" or a portmanteau like "Comensa") | English "the commons" — shared pasture/resource governed by mutual custom, not a central authority | Extremely literal fit — the manuscript already uses "the commons" as the core concept | Plain English / general property-law history (English enclosure-era commons) | Low — descriptive English term, not tied to a specific living minority culture |
| **Confluence** | Latin *confluere*, "flow together" — where rivers/streams meet without merging identity | Captures groups/cores/collaborations joining while keeping autonomy — literal "choreography not orchestration" | Latin/general scientific English | Low |
| **Ensemble** | French/Latin *insimul*, "at the same time" — musical ensemble: independent players, shared timing, no conductor dictating every note | Very strong fit for choreography-not-orchestration; "ensemble" is standard in both music and stats/ML (ensemble methods) — a nice double resonance for a research-computing audience | French, fully naturalized in English and in CS/stats jargon | Low |
| **Murmuration** | Behavior of starling flocks — decentralized local coordination producing coherent global pattern, no leader bird | Excellent metaphor for choreography/emergent coordination across autonomous agents | English natural-history term, describes an animal behavior, not a human culture | Low — but slightly whimsical/indirect; may need explaining |
| **Sodality** | Latin *sodalitas*, a voluntary fellowship/association (used historically for guilds, mutual-aid societies) | Fits "collaboration by choice" framing; slightly formal/academic register | Latin, long used in English institutional naming (e.g., Catholic sodalities, some university societies) | Low — but check it doesn't read as too tied to a specific religious usage; largely secular-safe in current English |
| **Atrium** | Latin — the open central courtyard of a Roman house, or a shared entry hall in modern architecture | Good fit for "a shared space every member draws on, with private rooms around it" | Latin/architectural, thoroughly generic in modern building design | Low |
| **Mycelium** / **Mycorrhiza** | Fungal network metaphor — decentralized resource-sharing network connecting many independent organisms | Excellent scientific fit for "pool agents/data when it helps, otherwise stay independent"; already popular in tech/systems-design metaphor (may feel slightly trend-worn) | Biological/general-science term | Low — but somewhat overused as a startup/network metaphor in 2020s tech writing; check freshness |
| **Weft** / **Loom** (e.g., "Weftwork") | Weaving metaphor — independent threads interlaced into a whole, no single thread in control | Fits "each group runs its own pattern, woven into a larger fabric"; weaving-as-metaphor is used across many cultures (not exclusive to one), so if handled as a *generic* textile metaphor (not citing a specific culture's textile tradition) it stays low-risk | Generic craft vocabulary, cross-cultural | Low, **provided** it's presented as a generic weaving metaphor and not attached to any one culture's specific weaving tradition (e.g., do not pair with imagery evoking a specific Indigenous or other minority textile practice) |

Explicitly ruled out as "would repeat the mistake": any other
Indigenous-language word chosen purely for vibe (e.g., other
Anishinaabe/Haudenosaunee/other First Nations terms for
"gathering place," "council," "village") without the same (b)-path
relationship-first process — same appropriation risk as "wigamig,"
just swapped.

## 5. Recommendation

Ranked shortlist:

1. **Ensemble** — best single-word fit: already double-coded for this
   audience (musical "independent players, shared tempo, no
   conductor" *and* statistical "ensemble method" — a nice wink for a
   research-computing tool), fully naturalized English/French root,
   no living-culture extraction risk. Trade-off: fairly common word,
   may need a distinguishing subtitle/logo to stand out and avoid
   collision with other "Ensemble"-named software.
2. **Confluence** — very close second; strong metaphor precision for
   "autonomous streams joining without losing identity," Latin root
   already part of the scientific commons vocabulary. Trade-off:
   "Confluence" is the name of a well-known Atlassian wiki product —
   real collision/SEO/trademark risk, would need a differentiator.
3. **Commons** (or a coined variant, e.g. "Comensa"/"Communa") — most
   literal fit to the manuscript's own language ("the commons"), but
   as a bare common noun it's weak as a distinctive proper-noun brand;
   works better as a subtitle/tagline ("[Name]: an agentic commons for
   the Bioconvergence Centre") than as the software's own name.

My pick if forced to one: **Ensemble**, with **Confluence** as
runner-up pending a trademark/collision check.

**Before finalizing:** hand the shortlist to `conscience` for an
EDID + Indigenization-lens review — not because these candidates
draw on Indigenous material (they don't), but because conscience is
the right agent to sanity-check that the *replacement* doesn't
introduce a new, less-obvious issue (e.g., colonial connotations in
"Commonwealth," or a metaphor that reads as trivializing something
sacred to *another* culture I haven't flagged), before leadership
commits.
