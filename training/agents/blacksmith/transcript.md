# The exchange shown in the movie

Real reply, run on 2026-11-07 (Murmurent 2026.11.0). The verdict line is verbatim; the detail is rewritten in plain words to fit a frame. `make.py` reads this file: each `## <key>` section starts with `<who>: <question>`, then the reply lines. Run on the simulated colony data of the example paper.

## 1
Member: Medium is mixed up with country in our colony data, so compute the serum effect on colony size within each country, with a shuffle test that respects country.
Done: the serum effect survives when each country is compared with itself. The within-country difference is 0.85 mm, and the chance of that by luck is about 4 in 1,000. But it is not consistent across countries.

- Confirmed: in two of the four countries, most isolates got one medium.
- Pooled over countries, serum colonies are 0.95 mm larger (20 isolates each).
- Within each country, the difference runs from -0.31 mm to +2.23 mm.
- Combined, weighted by group size: +0.85 mm; shuffle test two-sided, p = 0.0036.
- Caveat: one country goes the other way, and two have only 2 isolates in one medium.
- Saved: a results table and the code that made it.
