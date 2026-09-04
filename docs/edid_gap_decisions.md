# EDID gap decisions — the centre-wide list

**What this is.** Gaps that have been *promoted* — raised out of one member's
local ledger because they matter beyond one review — together with what was
decided about each. This is the only gap list in the repo, and it is
human-curated.

**What this is not.** It is not where gaps are recorded. The
[conscience](https://github.com/hallettmiket/murmurent/blob/main/agents/conscience.md) ends every report with its own gap table;
the `murmurent.hooks.conscience_gaps` hook appends those to
`~/.murmurent/edid_gaps/gap_log.md` — **on that member's own machine, never
here.** Gap text is free prose the agent wrote about whatever it just reviewed,
this repo is public, and *"no source on consent framing for incarcerated
participants"* names somebody's study. Promotion is the deliberate step where a
person reads the wording before it becomes public.

The cost of that, stated plainly: hit counts only aggregate across the centre
for gaps somebody promoted. The ranking is partial by construction, and that is
the price of not publishing everyone's review context.

## The three states

| State | Means | Effect |
|---|---|---|
| `open` | not yet worked | counts, and can trip the nudge threshold |
| `filled` | a source was added — **name it in the reason** | stops counting; the agent can now cite |
| `declined` | decided not to fill — **give the reason** | stops counting, stops nudging |

`declined` is the one that keeps this alive. A gap you have deliberately
decided against will keep recurring in real reviews, and without a way to say
no permanently it nudges forever until people stop reading nudges — at which
point the whole loop is decoration. Deciding once should mean deciding once.

A `declined` gap also reaches the agent: rather than reporting the same gap
again, it can say *out of scope by decision* and move on. Your judgment becomes
something it carries instead of something you re-make.

| Gap | State | Reason |
|---|---|---|
| Research ethics + data governance: REB / TCPS 2 Ch. 9, SAGER | `open` | governs the two artefacts the agent sees most. Candidate sources verified 2026-08-29 and **offered to the compiler, not yet added**: TCPS 2 (2022) Ch. 9, OCAP® (FNIGC), SAGER (EASE), CIHR sex-and-gender guidance, the Ontario HEIA tool, and Ontario Health's HEIA Indigenous Lens supplement. Adding them means a sixth domain, which is the compiler's call. |
| OCAP® | `open` | Still open, but **no longer blocked**: `www.fnigc.ca` 403s, while [`fnigc.ca/ocap-training/`](https://fnigc.ca/ocap-training/) returns 200 (checked 2026-08-29). The earlier 403s were the `www.` host, not the resource. Awaiting the decision on the clinical/health-equity set below. |
| Disability as a design constraint | `open` | the resources reach disability only as the word *ableism* in a language list, so no flag on an access barrier is possible |
| Intersectionality (Crenshaw) | `open` | findings that exist only at an intersection can be observed but not cited |
| Citation and authorship diversity | `open` | the agent is told to check author lists; nothing supports it |
| Migration status, age, class | `open` | named in the domains, unsupported |
| Training course catalogues | `open` | referral list is empty, so no course may be named |
| Non-Anglophone scholarship | `open` | domain 5 sources non-Western science through English popularizations |
| Hiring and letters of reference | `filled` | **Reversed 2026-08-29 by the compiler**, who directed that the two papers the source document had marked "are these worth including?" be included. Previously `declined` as personnel practice rather than study design. Filled by Schmader et al. (2007) and Gaucher et al. (2011), now included under Domain 1 and scoped there to postings, reference letters, recruitment calls and award nominations — **not** to research protocols. The earlier reasoning was not wrong about scope; the decision is that the scope is wider than study design. |

Seeded from the adversary's and conscience's reviews of the agent rather than
from usage, so these arrived by inspection rather than by blocking anyone.
