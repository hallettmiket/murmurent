# wigamig tutorial — DRAFT

> Phase 2 stub. The full day-by-day walkthrough lands in phase 5; this file
> currently captures the manual setup steps phase 2 introduced.

## Manual hook registration (raw-data guard)

The full hook installer ships in phase 4 (`wigamig install`). Until then,
register the raw-data guard manually:

1. Make sure `wigamig` is installed in the Python environment Claude Code can reach
   (e.g. `uv pip install -e ~/repos/wigamig`).
2. Add the following entry to `~/.claude/settings.json` (merging with whatever
   else is already there):

   ```json
   {
     "hooks": {
       "PreToolUse": [
         {
           "matcher": "Write|Edit|Bash|NotebookEdit",
           "hooks": [
             {
               "type": "command",
               "command": "python -m wigamig.hooks.raw_guard"
             }
           ]
         }
       ]
     }
   }
   ```

3. Restart Claude Code so the new hook is picked up.
4. Smoke-test it without launching CC:

   ```bash
   echo '{"tool_name":"Write","tool_input":{"file_path":"~/lab_vm/data/raw/p/x.fastq.gz"}}' \
     | python -m wigamig.hooks.raw_guard
   # -> {"decision": "deny", "reason": "raw data is read-only ..."}
   ```

5. Optional: set `WIGAMIG_LAB_VM_ROOT` if your simulated lab VM is somewhere
   other than `~/lab_vm/data`. The hook always also blocks the production path
   `/data/lab_vm/raw/` regardless of env.

## Seeding the smoke-test fixtures

```bash
# 1. Seed lab-mgmt + projects + fake data (idempotent).
python scripts/seed_tutorial.py

# 2. Confirm the projects exist locally.
WIGAMIG_USER=allie wigamig project list

# 3. Inspect the clinical project.
wigamig project describe dcis_sc_tutorial

# 4. List experiments.
wigamig experiment list --project dcis_sc_tutorial

# 5. Run an ingest (prompts before copying).
wigamig experiment ingest dcis_sc_tutorial 1_sample_qc \
    ~/lab_vm/staging/fake_instrument_export/dcis_sequencing
```

After the ingest the raw dir under `$WIGAMIG_LAB_VM_ROOT/raw/dcis_sc_tutorial/1_sample_qc/`
will be `chmod a-w`, and `exp/1_sample_qc/notebook.md` will have its `raw_data`,
`instrument_outputs`, and `checksums` fields populated.
