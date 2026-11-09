# The example pack

A generic institution pack that ships with murmurent, for two uses: the tests
load it, and a centre copies it to start its own. Every fact in it is invented
and every source is on the reserved `example.edu` domain, which resolves
nowhere, so `murmurent institution refresh` reports every fact unreachable.
That is correct for a fixture and wrong for an institution: a real pack's
sources are pages the clerk can read.

The one real-shaped file is `procedures/thesis_examination.yaml`, written by
`murmurent institution init --seed-thesis` from the SGPS seed built into
murmurent. A centre that is not Western rewrites it, or deletes it when it has
no thesis procedure (a company, say).

How a pack is made and kept: `docs/institution_pack.md`.
