---
name: Smoke-test feedback
about: One issue per finding from the murmurent smoke test
title: "Smoke test: <one-line summary>"
labels: smoke-test
assignees: hallettmiket
---

## Persona

Which fake persona were you running as?

- [ ] @mhallet
- [ ] @allie
- [ ] @bob
- [ ] @cassie

## What were you trying to do?

(Day 1 orientation, day 2 SEA work, day 3 finalisation, day 4 deliberate breakage, day 5 debrief, or something off-script.)

## What was confusing?

(A short paragraph; what didn't make sense the first time you saw it.)

## What was broken?

(Exact command + exact output. Use code fences.)

```bash
$ murmurent ...
<paste output>
```

## What was missing?

(Something the design implies should exist but the smoke test didn't expose, or a verb that didn't behave as described.)

## What was surprising in a good way?

(Anything that worked unexpectedly well. Useful counter-signal so we don't refactor it away.)

## Suggested fix

(Optional. One sentence.)

## Environment

- OS:
- Python:
- gh auth: (`gh auth status` first line)
- murmurent commit: (`git -C ~/repos/murmurent rev-parse --short HEAD`)
