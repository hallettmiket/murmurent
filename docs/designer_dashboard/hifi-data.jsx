/* Bootstrap data for the hi-fi Command Bridge.
 *
 * This is a STRUCTURAL SKELETON ONLY — every key the React tree reads is
 * present, but with EMPTY / blank values. It exists so the first paint has a
 * well-shaped object to render against before GET /api/dashboard resolves. It
 * intentionally contains NO people, NO lab name, NO projects: a brand-new
 * install has exactly one member (you) and nothing else, and the live backend
 * fills in the real values on fetch.
 *
 * Do NOT put demo personas (fake members, a sample lab, invented SEAs) here.
 * On any prior version this fixture shipped a fake "hallett lab" full of made-up
 * people, and because the fetch layer Object.assign()es the real response on top
 * of it, any field the backend omitted — or ANY failed/refused fetch — left that
 * fake data on screen. The skeleton below cannot leak a fake identity because
 * there is no fake identity to leak.
 */

const EMPTY_CONTACT = { email: "", orcid: "", github: "", bluesky: "", osf: "" };
const EMPTY_LOCATION = { office: "", address: "", city: "", department: "" };

const DATA = {
  today: { iso: "", pretty: "", weekday: "", week: 0 },

  member: { handle: "", name: "", role: "", lab: "",
            contact: { ...EMPTY_CONTACT }, location: { ...EMPTY_LOCATION } },
  pi:     { handle: "", name: "", role: "", lab: "",
            contact: { ...EMPTY_CONTACT }, location: { ...EMPTY_LOCATION } },

  member_settings: {
    obsidian_vault_path: "", obsidian_vault_name: "",
    notebook_subfolder: "", oracle_subfolder: "",
    email: "", orcid: "", bluesky: "", github: "", osf: null, website: "",
    office: "", dry_lab: "", wet_labs: "", address: "", city: "", department: "",
  },

  lab_settings: {
    name: "", display_name: "", pi_handle: "", website: "",
    lab_base: "", github_org: "", git_repos_subpath: "repos", admins: [],
    notebook_large_files_path: null, lab_oracle_vault: "",
  },

  machine_settings: {
    wigamig_base: "", obsidian_vault_path: "", obsidian_vault_name: "",
    notebook_subfolder: "", oracle_subfolder: "",
  },

  attention: [],

  stats: {
    attention: { red: 0, amber: 0, ok: 0 },
    seas: { closed_this_week: 0, delta_pct: 0, in: 0, out: 0 },
    compliance: { expired: 0, expiring: 0, missing: 0 },
    inventory: { expired: 0, low: 0, expiring30: 0 },
    notebook: { entries_this_week: 0, last_written: "" },
  },

  spark: [],
  spark_labels: [],

  projects: [],
  peers: [],
  agents: [],

  oracle_recent: [],
  personal_oracle: { folder: "oracle/", entry_count: 0, recent: [] },
  lab_oracle_folder: "",

  seas: [],
  experiments: [],
  notifs: [],

  heatmap: { members: [], rows: [] },

  inventory: {
    expired: [], low: [], expiring: [],
    stock: { reagents: [0, 0], kits: [0, 0] },
  },

  installations: [],

  notebook: {
    folder: "lab-notebook/",
    days: [],
    today: { iso: "", title: "", tags: [], links_seas: [], links_exp: [], content: [] },
    yesterday_excerpt: null,
  },
};

/* Live data from GET /api/dashboard.
 *
 * 1. Set window.DATA to the empty skeleton synchronously so first paint has a
 *    well-shaped object (no network wait, no fake data).
 * 2. Fire the initial fetch; Object.assign the real response onto the SAME
 *    window.DATA object so module-level `const D = window.DATA` refs see it.
 * 3. Expose window.__murmurentFetchData(persona) so the persona toggle can
 *    refetch with ?persona=pi|member without a page reload.
 *
 * FAIL-CLOSED: if the fetch is refused (403 — you signed in as a netname this
 * machine/centre does not recognise) we send you to /login instead of leaving
 * the skeleton (or, historically, fake data) on screen. Any other failure marks
 * the data non-live and rethrows; it never substitutes invented content.
 *
 * Override the user via ?user=<handle> on the dashboard URL.
 */
window.DATA = DATA;

window.__murmurentFetchData = function (persona) {
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
      if (r.status === 401 || r.status === 403) {
        // Not an authorised identity for this machine/centre. Do NOT render a
        // stale/empty dashboard as if signed in — send them back to login.
        const err = new Error("HTTP " + r.status);
        err.__authFailure = true;
        throw err;
      }
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
      window.__wigamigDataLive = false;
      if (err && err.__authFailure) {
        console.warn("[murmurent] /api/dashboard refused this identity; returning to login");
        window.location.href = "/";   // login page is served at "/", not "/login"
        return;
      }
      console.warn("[murmurent] /api/dashboard failed; dashboard is not live", err);
      throw err;
    });
};

// Initial load — let the server pick the default persona ("member").
window.__murmurentFetchData();
