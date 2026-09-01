# EDID PDF store

Full texts for pool entries the [conscience](../../agents/conscience.md)
cannot reach. The agent does not browse — `WebFetch` and `WebSearch` are
denied in its frontmatter — so a source behind a bot block, a captcha, or a
paywall is unciteable until its text is here.

Each file is linked from its entry in
[`docs/edid_resources.md`](../edid_resources.md) alongside the public URL.
The URL stays authoritative; the local file is what the agent actually reads.

## Redistribution

**Only openly-licensed PDFs are committed.** `hallettmiket/murmurent` is a
public repo, so a subscription or all-rights-reserved PDF committed here would
be republished to anyone. `.gitignore` in this directory blocks `*.pdf` and
allowlists the open-access one; the rest are local-only and must be fetched
per machine by the person who needs them.

| File | Source | Licence | Committed? |
|---|---|---|---|
| `traditional_ancient_egyptian_medicine_2021.pdf` | *Saudi J. Biol. Sci.*, [10.1016/j.sjbs.2021.06.044](https://doi.org/10.1016/j.sjbs.2021.06.044) | **CC BY-NC-ND 4.0** — © 2021 The Author(s), Elsevier on behalf of King Saud University | **yes** |
| `trc_2015_calls_to_action.pdf` | Truth and Reconciliation Commission of Canada (2015), via [NCTR](https://nctr.ca/records/reports/) | **Public domain** — the report states: "Anyone may, without charge or request for permission, reproduce all or part of this report" | **yes** |
| `falagas_2006_science_in_greece.pdf` | *FASEB J.* 20(14), [10.1096/fj.06-1002ufm](https://doi.org/10.1096/fj.06-1002ufm) | Wiley, all rights reserved. This copy came through Western University's subscription | no — local only |
| `shahjahan_2021_decolonizing_curriculum.pdf` | *Rev. Educ. Res.*, [10.3102/00346543211042423](https://doi.org/10.3102/00346543211042423) | SAGE, all rights reserved | no — local only |
| `clrn_is_science_objective_or_subjective.pdf` | [clrn.org](https://www.clrn.org/is-science-objective-or-subjective/), "By CLRN team", 2025-07-02 | © CLRN, no open licence stated. Browser print-to-PDF; the site returns HTTP 403 to automated fetchers | no — local only |

## Adding one

1. Fetch or print-to-PDF the source yourself. Name it `snake_case.pdf`.
2. Check the licence. If it is not openly licensed, leave it gitignored.
3. Add a row above, and link the file from its `edid_resources.md` entry.
4. Clear the item from that file's ingestion backlog.
