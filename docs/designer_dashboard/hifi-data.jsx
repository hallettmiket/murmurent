/* Mock data for the hi-fi Command Bridge. Mirrors the shape returned by
   wigamig.core.dashboard.DashboardSnapshot so swapping in the real backend
   is a 1-to-1 substitution. */

const DATA = {
  today: { iso: "2026-05-08", pretty: "Friday, May 8, 2026", weekday: "Fri", week: 19 },
  member: {
    handle: "allie", name: "Allie Tran", role: "PhD candidate · year 3",
    lab: "hallett",
    contact: {
      email: "allie@example.edu", orcid: "0000-0002-1111-2222",
      github: "allie-fake",
    },
    location: {
      office: "SSC-2418",
      address: "1 Example Ave", city: "London, ON N6A 3K7, Canada",
      department: "Schulich School of Dentristy and Medicine · Department of Biochemistry",
    },
  },
  pi: {
    handle: "the_pi", name: "Mike Hallett", role: "Principal Investigator",
    lab: "hallett",
    contact: {
      email: "michael.hallett@example.edu", orcid: "0000-0001-6738-6786",
      bluesky: "@hallettmiket.bsky.social", github: "hallettmiket",
      osf: "osf.io/jz64u",
    },
    location: {
      office: "MSB-360", dry_lab: "MSB-309A", wet_labs: "M359A & M433",
      address: "1 Example Ave", city: "London, ON N6A 3K7, Canada",
      department: "Schulich School of Dentristy and Medicine · Department of Biochemistry",
    },
  },

  attention: [
    { sev: "red",   kind: "SEA",  id: "#214", text: "Align NovaSeq run 17 against GRCh38",      project: "dcis_imaging_genomics", age: "62d overdue", actions: [["complete","tiger"], ["reassign",""], ["open",""]] },
    { sev: "red",   kind: "CERT", id: "TCPS_2", text: "TCPS_2 expired — clinical access blocked", project: "—",                     age: "26d ago",     actions: [["renew now","primary"], ["guide",""]] },
    { sev: "amber", kind: "SEA",  id: "#231", text: "Lit scan: IDC vs DCIS biomarkers (TNBC focus)", project: "dcis_imaging_genomics", age: "5d",        actions: [["claim","primary"], ["decline",""]] },
    { sev: "amber", kind: "EXP",  id: "exp/4_segment_qc", text: "Analysis stalled 18d after run complete", project: "imaging_pheno", age: "18d", actions: [["resume","primary"], ["open",""]] },
    { sev: "amber", kind: "INV",  id: "Tris-HCl 1M", text: "Low — 2 bottles left",                project: "—",                     age: "—",          actions: [["order","primary"]] },
    { sev: "ok",    kind: "SEA",  id: "#240", text: "Methods note ready for Adversary review",   project: "method_bench_24",       age: "2d",         actions: [["send","tiger"], ["open",""]] },
  ],

  stats: {
    attention: { red: 2, amber: 4, ok: 1 },
    seas: { closedThisWeek: 10, deltaPct: 28, in: 3, out: 2 },
    compliance: { expired: 2, expiring: 1, missing: 1 },
    inventory: { expired: 1, low: 2, expiring30: 1 },
    notebook: { entriesThisWeek: 5, lastWritten: "yesterday" },
  },

  spark: [3, 5, 4, 6, 4, 7, 5, 8, 6, 9, 7, 10],
  sparkLabels: ["w8","w9","w10","w11","w12","w13","w14","w15","w16","w17","w18","w19"],

  projects: [
    { name: "dcis_imaging_genomics", sens: "clinical", lead: "@the_pi", choreo: "drug_discovery_litl", members: 7, openSeas: 4, lastActivity: "2h ago" },
    { name: "cohort_v3",             sens: "clinical", lead: "@cassie",  choreo: "clinical_cohort",     members: 5, openSeas: 6, lastActivity: "1h ago" },
    { name: "imaging_pheno",         sens: "standard", lead: "@allie",   choreo: "imaging_phenotyping", members: 4, openSeas: 2, lastActivity: "yesterday" },
    { name: "method_bench_24",       sens: "standard", lead: "@bob",     choreo: "method_benchmarking", members: 3, openSeas: 1, lastActivity: "3d ago" },
  ],

  peers: [
    { handle: "bob",     name: "Bob Yamazaki",   role: "postdoc",     tcps: "ok",       shared: 2,
      projects: ["dcis_imaging_genomics","method_bench_24"], open_seas: 3, experiments: 2 },
    { handle: "cassie",  name: "Cassie Okello",  role: "PhD year 1",  tcps: "expiring", shared: 2,
      projects: ["dcis_imaging_genomics","cohort_v3"], open_seas: 5, experiments: 1 },
    { handle: "diego",   name: "Diego Ferreira", role: "MSc",         tcps: "missing",  shared: 1,
      projects: ["imaging_pheno"], open_seas: 1, experiments: 1 },
    { handle: "ezra",    name: "Ezra Wynn",      role: "research asst.", tcps: "ok",    shared: 1,
      projects: ["method_bench_24"], open_seas: 0, experiments: 1 },
    { handle: "fenwick", name: "Fenwick Liu",    role: "postdoc",     tcps: "ok",       shared: 1,
      projects: ["dcis_imaging_genomics"], open_seas: 2, experiments: 0 },
  ],

  agents: [
    { name: "oracle",       description: "Cross-project institutional memory; surfaces prior findings.",
      freeze: "frozen",   model: "opus",   required_tools: ["Read","Write","Glob","Grep","Bash"] },
    { name: "bookworm",     description: "Literature scout. Pulls papers from PubMed, bioRxiv, Zotero.",
      freeze: "frozen",   model: "sonnet", required_tools: ["Read","Write","WebFetch","Glob"] },
    { name: "blacksmith",   description: "Computational workhorse. Loads data, trains classifiers, builds dashboards.",
      freeze: "personal", model: "opus",   required_tools: ["Read","Write","Bash","Glob","Grep"] },
    { name: "artist",       description: "Visualization specialist; figures, plots, presentations.",
      freeze: "personal", model: "sonnet", required_tools: ["Read","Write","Bash","Glob"] },
    { name: "adversary",    description: "Scientific skeptic. Audits methodology, demands cross-validation.",
      freeze: "frozen",   model: "opus",   required_tools: ["Read","Write","Bash","Glob","Grep"] },
    { name: "conscience",   description: "Equity, diversity, inclusion, decolonization watchdog.",
      freeze: "frozen",   model: "sonnet", required_tools: ["Read","Write","Bash","Glob","Grep"] },
  ],

  oracle_recent: [
    { title: "GRCh38.p14 fixes the chrM contig issue for run 17",
      excerpt: "The chrM artefact we hit in February with GRCh38.p13 is patched in p14. For DCIS run 17 we are aligning against p14, not p13.",
      author: "@allie",  date: "2026-05-08", project: "dcis_imaging_genomics",
      path: "oracle/2026-05-08_dcis_chrm_p14.md" },
    { title: "Drift correction belongs in run_all, not in QC",
      excerpt: "Drift correction is a per-run preprocessing step, not a QC gate. Moving the drift step into run_all.py upstream of the QC pass.",
      author: "@bob",    date: "2026-05-07", project: "method_bench_24",
      path: "oracle/2026-05-07_methods_drift_correction.md" },
  ],

  seas: [
    { id: 214, dir: "in",  state: "claimed",   kind: "experiment", who: "@the_pi", project: "dcis_imaging_genomics", desc: "Align NovaSeq run 17 against GRCh38; QC report by Friday.", age: "62d" },
    { id: 231, dir: "in",  state: "requested", kind: "skill",      who: "@cassie",  project: "dcis_imaging_genomics", desc: "Pull recent IDC vs DCIS biomarker literature, TNBC focus.",  age: "5d"  },
    { id: 207, dir: "in",  state: "examined",  kind: "analysis",   who: "@bob",     project: "method_bench_24",       desc: "Re-examine drift correction on benchmark dataset 3.",        age: "21d" },
    { id: 240, dir: "out", state: "complete",  kind: "experiment", who: "@bob",     project: "method_bench_24",       desc: "Methods note draft attached; ready for Adversary review.",   age: "2d"  },
    { id: 219, dir: "out", state: "claimed",   kind: "skill",      who: "@fenwick", project: "dcis_imaging_genomics", desc: "Slide deck for joint group meeting next Thursday.",         age: "9d"  },
  ],

  experiments: [
    { project: "dcis",    folder: "2_align_grch38",  status: "running",  analysis: "not_started", performer: "@allie", date: "2026-04-30" },
    { project: "dcis",    folder: "1_ingest_run17",  status: "complete", analysis: "examined",    performer: "@bob",   date: "2026-04-22" },
    { project: "imaging", folder: "4_segment_qc",    status: "complete", analysis: "stalled 18d", performer: "@diego", date: "2026-04-20" },
    { project: "method",  folder: "3_drift",         status: "planned",  analysis: "—",           performer: "@ezra",  date: "—"          },
  ],

  notifs: [
    { time: "08:14",     text: "@bob completed SEA #240 — ready for review" },
    { time: "yesterday", text: "@cassie opened SEA #231 (literature scan)" },
    { time: "yesterday", text: "Inventory: T4 ligase expired" },
    { time: "2d ago",    text: "@fenwick joined dcis_imaging_genomics" },
    { time: "3d ago",    text: "exp/2_align_grch38 launched on lab-VM" },
  ],

  // Compliance heatmap rows. cells are aligned to `members` array.
  heatmap: {
    members: ["@the_pi", "@allie", "@cassie", "@bob", "@fenwick", "@diego", "@ezra"],
    rows: [
      { project: "dcis_imaging_genomics", sens: "clinical",  cells: ["ok", "exp", "amb", "ok", "mis", "na", "na"] },
      { project: "cohort_v3",             sens: "clinical",  cells: ["ok", "exp", "amb", "na", "na", "na", "na"] },
      { project: "imaging_pheno",         sens: "standard",  cells: ["na", "ok", "na", "na", "na", "mis", "na"] },
      { project: "method_bench_24",       sens: "standard",  cells: ["na", "na", "na", "ok", "na", "na", "ok"] },
    ],
  },

  inventory: {
    expired:  [{ name: "T4 ligase (NEB)",  expiry: "2026-04-22", qty: "0/4" }],
    low:      [{ name: "Tris-HCl 1M",       expiry: "2026-09-01", qty: "2/8" },
               { name: "10x PBS",            expiry: "2027-02",    qty: "1/6" }],
    expiring: [{ name: "RNeasy mini kit",   expiry: "2026-06-04", qty: "3"   }],
    stock:    { reagents: [42, 50], kits: [6, 12] },
  },

  // Lab notebook — Obsidian "daily notes" in <repo>/lab-notebook/YYYY-MM-DD.md
  notebook: {
    folder: "lab-notebook/",
    days: [
      { iso: "2026-05-08", weekday: "Fri", word_count: 312, has_entry: true,  is_today: true  },
      { iso: "2026-05-07", weekday: "Thu", word_count: 415, has_entry: true                    },
      { iso: "2026-05-06", weekday: "Wed", word_count: 0,   has_entry: false                   },
      { iso: "2026-05-05", weekday: "Tue", word_count: 188, has_entry: true                    },
      { iso: "2026-05-04", weekday: "Mon", word_count: 524, has_entry: true                    },
      { iso: "2026-05-01", weekday: "Fri", word_count: 222, has_entry: true                    },
      { iso: "2026-04-30", weekday: "Thu", word_count: 367, has_entry: true                    },
    ],
    today: {
      iso: "2026-05-08",
      title: "8 May 2026",
      tags: ["#dcis", "#run17", "#methods"],
      links_seas: [214, 231],
      links_exp:  ["exp/2_align_grch38"],
      content: [
        { kind: "h4",  text: "Plan for today" },
        { kind: "task", done: true,  text: "Stand-up at 09:00 — flag SEA #214 with @the_pi" },
        { kind: "task", done: false, text: "Re-run alignment with GRCh38.p14 chrM patched" },
        { kind: "task", done: false, text: "Draft response to TCPS_2 renewal email" },
        { kind: "task", done: false, text: "Pull TNBC biomarker refs (Bookworm) for SEA #231" },

        { kind: "h4",  text: "Notes" },
        { kind: "p",   text: "Run 17 fastqs look fine — Q30 above 92% across the lane (per @bob's exam in [[exp/1_ingest_run17]] yesterday). The chrM contig is the same one that bit us in February; patch ships in GRCh38.p14 so I'll redo alignment against that build, not p13." },
        { kind: "code",text: "$ bcftools view --regions chrM run17.vcf.gz | head\n$ samtools view -b run17.bam chrM > run17.chrM.bam" },

        { kind: "blockquote", text: "From @the_pi (Slack, 07:42): \"please get me a QC report by Friday — even a draft is fine, I just need numbers for the IRB update.\"" },

        { kind: "h4",  text: "Decisions" },
        { kind: "p",   text: "Going with GRCh38.p14 over T2T-CHM13 for run 17 — switching reference mid-cohort would invalidate cross-sample comparison. Document in [[CHANGELOG]] for the project repo." },

        { kind: "h4",  text: "Open questions" },
        { kind: "list", items: [
          "Does TCPS_2 renewal need to clear before I can keep working on run 17 fastqs (clinical-sensitivity)? Ask @cassie.",
          "Diego's segmentation QC stalled — is he blocked on me or on the ITK-SNAP build?",
        ] },
      ],
    },
    yesterday_excerpt: {
      iso: "2026-05-07",
      title: "7 May 2026 · DCIS run 17 · ingest done",
      excerpt: "Run 17 fastqs landed on the lab-VM. @bob ran the standard QC pass and everything passed gates except the chrM-on-p13 issue we hit before. Logged exp/1_ingest_run17 as examined. Tomorrow: redo alignment.",
    },
  },
};

/* Phase 1 + 3 — live data from GET /api/dashboard.
 *
 * 1. Set window.DATA to the inline mock synchronously so first paint never
 *    blocks on the network.
 * 2. Fire the initial fetch.
 * 3. Expose window.__wigamigFetchData(persona) so the persona toggle can
 *    refetch with ?persona=pi or ?persona=member without a page reload.
 *
 * Both paths Object.assign the response onto the *same* window.DATA object so
 * module-level `const D = window.DATA` references still see the new fields,
 * then call window.__wigamigRerender() to repaint the React tree.
 *
 * Override the user via ?user=<handle> on the dashboard URL.
 */
window.DATA = DATA;

window.__wigamigFetchData = function (persona) {
  const params = new URLSearchParams(window.location.search);
  const userParam = params.get("user");
  const qs = new URLSearchParams();
  if (userParam) qs.set("user", userParam);
  if (persona) qs.set("persona", persona);
  const url = "/api/dashboard" + (qs.toString() ? "?" + qs.toString() : "");

  return fetch(url, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  })
    .then((r) => {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then((real) => {
      Object.assign(window.DATA, real);
      window.__wigamigDataLive = true;
      if (typeof window.__wigamigRerender === "function") {
        window.__wigamigRerender();
      }
      return real;
    })
    .catch((err) => {
      console.warn("[wigamig] /api/dashboard failed; rendering mock data", err);
      window.__wigamigDataLive = false;
      throw err;
    });
};

// Initial load — let the server pick the default persona ("member").
window.__wigamigFetchData();
