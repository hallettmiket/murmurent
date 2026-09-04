---
name: Bug report
about: Something murmurent does is wrong, broken, or contradicts the docs
title: "Bug: <one-line summary>"
labels: bug
---

## What happened

(One or two sentences. What you ran, what you got.)

## What you expected instead

(And, if it applies, where the docs say so: a link or a file:line is ideal.)

## Exact command and output

```bash
$ murmurent ...
<paste the full output, including any traceback>
```

## Steps to reproduce

1.
2.
3.

## Environment

Run `murmurent doctor` and paste the output. It reports the install layout,
the hook/MCP registration, and the version in one go:

```
<paste `murmurent doctor` output>
```

- OS:
- Python (`python --version`):
- murmurent (`murmurent --version`):
- Installed via: [ ] PyPI  [ ] one-command clone  [ ] dev clone (`murmurent_dev`)

## Anything else

(Workarounds you found, related issues, or "this used to work in <version>".)

<!--
Please do not paste secrets, tokens, participant data, or anything from
immutable/ or append_only/ into a public issue. Redact paths if you need to.
-->
