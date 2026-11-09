# Institution packs

An institution pack is a folder of facts about one institution, each with the
page it was read from and the date: who holds an office, the holidays and term
dates, which sections a course has, the steps of a procedure with their forms
and deadlines, the letterhead colours and fonts. The `clerk` agent answers
from a pack and from nothing else. The full description, the schema and how to
keep a pack are in [`docs/institution_pack.md`](../docs/institution_pack.md).

```
institution/
  README.md            this file
  example/             a generic pack that ships with murmurent: a starting point and the tests' fixture
  <unique_name>/       a deployment's own pack, named after the centre's unique_name; never in the public release
```

To make your centre's pack:

```bash
murmurent institution init <unique_name> --name "Your University" --domain your.edu --seed-thesis
murmurent institution validate --pack <unique_name>
```

Then fill `directory.yaml`, `calendar.yaml`, `courses.yaml` and `templates/`,
one fact at a time, each with `source:` (a page on one of the pack's domains)
and `date_read:`. A fact that cannot be read from such a page is left out.
