/* Hi-fi app — Command Bridge layout, Western brand applied. */

const { useState, useEffect, useMemo, useReducer } = React;
const D = window.DATA;

/* ───────── shared atoms ───────── */
function Pill({ tone="", children }) { return <span className={"pill "+tone}>{children}</span>; }
function K({ children }) { return <kbd className="kbd">{children}</kbd>; }

// Member-name renderer: appends "(<ROLE>)" when the member holds a leadership
// role, e.g. "Mike Hallett (PI)". The handle/Western netname is not shown here
// because it's an implementation detail of how members are looked up.
function _displayMemberName(m) {
  if (!m) return "";
  const role = (m && m.role) || "";
  const tag = role && role.toLowerCase() === "lead" ? " (PI)"
            : role && role.toLowerCase() === "pi"   ? " (PI)"
            : "";
  return (m.name || m.handle || "") + tag;
}

// Render role with canonical labels. "lead" is the lab-mgmt frontmatter value
// for the principal investigator; surface it as "PI" in a research lab and
// "Leader" in a core (per docs/cores_plan.md §3, the same role wears
// different labels depending on the entity kind). Reads
// ``window.DATA.lab_settings.kind`` (default "lab"); when called outside
// the dashboard data context, falls back to "PI" for back-compat.
function _displayRole(role) {
  if (!role) return "";
  const r = String(role).toLowerCase();
  if (r === "lead" || r === "pi") {
    const kind = ((window.DATA && window.DATA.lab_settings && window.DATA.lab_settings.kind) || "lab").toLowerCase();
    return kind === "core" ? "Leader" : "PI";
  }
  return role;
}

// Short label for the persona-pill badge ("PI VIEW" vs "LEADER VIEW").
function _personaLabel(persona) {
  if (persona !== "pi") return "MEMBER VIEW";
  const kind = ((window.DATA && window.DATA.lab_settings && window.DATA.lab_settings.kind) || "lab").toLowerCase();
  return kind === "core" ? "LEADER VIEW" : "PI VIEW";
}

// Render the lab field. lab-mgmt stores a slug ("hallett"); the UI shows the
// human form ("Hallett lab"). Capitalise the slug and append " lab" unless the
// value already ends in "lab" (case-insensitive).
function _displayLab(lab) {
  if (!lab) return "";
  const s = String(lab).trim();
  const isAlreadyLab = /lab$/i.test(s);
  const cap = s.charAt(0).toUpperCase() + s.slice(1);
  return isAlreadyLab ? cap : cap + " lab";
}

// Join a directory root with a project name. Used by the Installations
// panel so users see the actual per-project subdir (e.g. ~/lab_vm/raw/candi)
// instead of the bare root (~/lab_vm/raw) that's stored in the manifest.
// Idempotent if the root already ends with /<project>.
function _joinPath(root, project) {
  if (!root) return root || "";
  if (!project) return root;
  const trimmed = root.replace(/\/+$/, "");
  const tail = "/" + project;
  if (trimmed.endsWith(tail)) return trimmed;
  return trimmed + tail;
}

/* Phase 4: POST /api/sea/{project}/{id}/{action}, refetch on success.
 * Caller is the signed-in user (passed via ?user= if set on the URL,
 * otherwise the server resolves from $MURMURENT_USER). */
async function postSeaAction(project, id, action, body = {}) {
  const params = new URLSearchParams(window.location.search);
  const userParam = params.get("user");
  const url = "/api/sea/" + encodeURIComponent(project)
    + "/" + encodeURIComponent(id) + "/" + encodeURIComponent(action)
    + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
  const res = await fetch(url, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

function SeaActionButton({ sea, action, label, tone, needsDelivery }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr]   = useState(null);
  const onClick = async (e) => {
    e.preventDefault();
    let body = {};
    if (needsDelivery) {
      const d = window.prompt(
        "Delivery path or note (e.g. findings/qc_report.md):",
        sea.delivery || ""
      );
      if (!d || !d.trim()) return;
      body.delivery = d.trim();
    }
    setBusy(true); setErr(null);
    try {
      await postSeaAction(sea.project, sea.id, action, body);
      // Refresh the dashboard so the row picks up the new state.
      if (typeof window.__murmurentFetchData === "function") {
        await window.__murmurentFetchData(window.DATA.persona);
      }
    } catch (ex) {
      setErr(String(ex.message || ex));
      console.warn("[murmurent] sea action failed", ex);
    } finally {
      setBusy(false);
    }
  };
  return (
    <span style={{display:"inline-flex", flexDirection:"column", alignItems:"flex-end", gap:2}}>
      <button
        className={"btn sm " + (tone || "")}
        disabled={busy}
        onClick={onClick}
        title={err || ""}
      >
        {busy ? "…" : label}
      </button>
      {err && (
        <span style={{fontSize:10, color:"var(--red)", maxWidth:160, textAlign:"right"}}>
          {err}
        </span>
      )}
    </span>
  );
}

function SeaActionMore({ sea }) {
  const [open, setOpen] = useState(false);
  const persona = window.DATA.persona || "member";
  const isPI = persona === "pi";
  const onDecline = async () => {
    const reason = window.prompt("Decline reason:");
    if (!reason || !reason.trim()) return;
    setOpen(false);
    try {
      await postSeaAction(sea.project, sea.id, "decline", { reason: reason.trim() });
      if (typeof window.__murmurentFetchData === "function") {
        await window.__murmurentFetchData(window.DATA.persona);
      }
    } catch (ex) {
      alert("Decline failed: " + (ex.message || ex));
    }
  };

  // Archive = soft-delete (orthogonal to the decline/conclude lifecycle).
  // PI-only; writes a decommission report and hides the SEA from queues.
  const onArchive = async () => {
    if (!window.confirm(
      `Archive SEA #${sea.id} in project "${sea.project}"?\n\n` +
      "murmurent will:\n" +
      "  • flip the SEA's archived flag in its markdown file\n" +
      "  • write a decommission report\n\n" +
      "The SEA file is preserved; you can unarchive later. Not the same\n" +
      "as decline — archive is for SEAs that should no longer appear in\n" +
      "active queues regardless of their workflow state."
    )) return;
    setOpen(false);
    try {
      const params = new URLSearchParams(window.location.search);
      const userParam = params.get("user");
      const url = "/api/sea/" + encodeURIComponent(sea.project)
                + "/" + sea.id + "/archive"
                + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
      const r = await fetch(url, { method: "POST", headers: { Accept: "application/json" } });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail || ("HTTP " + r.status));
      if (typeof window.__murmurentFetchData === "function") {
        await window.__murmurentFetchData(window.DATA.persona);
      }
    } catch (ex) {
      alert("Archive failed: " + (ex.message || ex));
    }
  };

  return (
    <span style={{position:"relative"}}>
      <button className="btn sm ghost" onClick={() => setOpen(o => !o)}>⋯</button>
      {open && (
        <div style={{
          position:"absolute", right:0, top:"100%", marginTop:4,
          background:"var(--card)", border:"1px solid var(--rule-strong)",
          borderRadius:2, boxShadow:"0 4px 12px rgba(0,0,0,0.08)",
          padding:4, zIndex:10, minWidth:140,
        }}>
          <button className="btn sm danger" style={{width:"100%", textAlign:"left"}} onClick={onDecline}>
            decline…
          </button>
          {isPI && (
            <button className="btn sm" style={{width:"100%", textAlign:"left", color:"var(--red)"}}
                    onClick={onArchive}>
              archive (PI)
            </button>
          )}
          <button className="btn sm ghost" style={{width:"100%", textAlign:"left"}} onClick={() => setOpen(false)}>
            cancel
          </button>
        </div>
      )}
    </span>
  );
}
function Sparkline({ data, w=180, h=36 }) {
  const max = Math.max(...data), min = Math.min(...data);
  const pts = data.map((v, i) => `${(i/(data.length-1))*w},${h - ((v-min)/(max-min||1))*(h-4) - 2}`).join(" ");
  const last = data.length-1;
  const lastY = h - ((data[last]-min)/(max-min||1))*(h-4) - 2;
  return (
    <svg className="spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`}>
      <polyline points={pts} fill="none" stroke="var(--purple)" strokeWidth="1.6" />
      <circle cx={w} cy={lastY} r="3" fill="var(--tiger)" />
    </svg>
  );
}

/* ───────── header ───────── */
function TopBar() {
  const m = window.DATA.member || {};
  const ls = window.DATA.lab_settings || {};
  // Institution-agnostic: show THIS install's lab, never a hardcoded one.
  const labLabel = ls.display_name || ls.name || m.lab || "";
  const kindLabel = (ls.kind === "core") ? "core" : "lab";
  return (
    <div className="topbar">
      <span className="uwo" style={{fontWeight:600}}>{labLabel}</span>
      <a href="http://mikehallett.science/murmurent/" target="_blank" rel="noopener"
         title="Murmurent documentation — getting started, projects, identity, CLI reference"
         style={{marginLeft:14, fontFamily:"var(--mono)", fontSize:12,
                 color:"var(--purple)", textDecoration:"none",
                 borderBottom:"1px dotted var(--purple)"}}>
        📖 docs
      </a>
      <span className="who">
        signed in as <code>@{m.handle}</code> · {kindLabel}: <code>{m.lab || ls.name}</code>
      </span>
    </div>
  );
}

function CmdBar({ query, setQuery }) {
  // The persona arrives via ?persona= from the /login landing page; the
  // role badge below the search is informational (it reflects the lens
  // the user picked at sign-in).
  const persona = window.DATA.persona || "member";
  // A PI (or a designated settings-admin) can edit the lab's parameters. This
  // top-bar button is a copy of the footer "⚙ lab" control so the PI can reach
  // Lab settings without scrolling — setting the lab parameters is a first job.
  const _m = window.DATA.member || {};
  const _ls = window.DATA.lab_settings || {};
  const _myHandle = (_m.handle || "").toLowerCase();
  const canEditLab = persona === "pi"
    || (_ls.admins || []).map(h => h.toLowerCase()).includes(_myHandle);
  const [showLabTop, setShowLabTop] = useState(false);
  return (
    <div className="cmdbar">
      {showLabTop && <LabSettingsModal onClose={() => setShowLabTop(false)} />}
      <div className="home">murmurent <small>v1.0.0</small></div>
      <div className="search">
        <span className="mono muted" style={{fontSize:12}}>›</span>
        <input
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="search SEAs, experiments, projects, people, notebook…"
        />
        <K>⌘K</K>
      </div>
      {canEditLab && (
        <button
          type="button"
          onClick={() => setShowLabTop(true)}
          title="Lab settings — set your group's parameters (PI / admin)"
          style={{
            marginLeft: 10, fontFamily: "var(--mono)", fontSize: 11,
            letterSpacing: 1, textTransform: "uppercase",
            color: "var(--paper)", background: "var(--purple)",
            border: "1px solid var(--purple)", borderRadius: 2,
            padding: "3px 10px", cursor: "pointer", fontWeight: 600,
          }}>
          ⚙ Lab settings
        </button>
      )}
      <div className="persona-badge" title={
        persona === "pi"
          ? "You are the lab PI per lab.md (see <lab-mgmt>/lab.md)."
          : "You are a lab member per lab.md."
      }>
        <span className={"role-pill "+(persona==="pi"?"pi":"member")}>
          {_personaLabel(persona)}
        </span>
      </div>
      {/* /security link — shown for the PI (implicit) and any lab member
          with ``lab_sudo: true``. Members without the grant see no link,
          so the route remains discoverable only after the PI grants it. */}
      {(window.DATA.member && window.DATA.member.lab_sudo) && (
        <a
          href={`/security?user=${encodeURIComponent(window.DATA.member.handle || "")}`}
          title="Open the per-lab security dashboard (/security)"
          target="_blank" rel="noopener"
          style={{
            marginLeft: 10, fontFamily: "var(--mono)", fontSize: 11,
            letterSpacing: 1, textTransform: "uppercase",
            color: "var(--tiger)", textDecoration: "none",
            border: "1px solid var(--tiger)", borderRadius: 2,
            padding: "3px 8px",
          }}>
          ⚿ security ↗
        </a>
      )}
      <a
        href="/"
        className="switch-role"
        title="Switch user or role — returns to the sign-in page"
        style={{
          marginLeft: 12, fontFamily: "var(--mono)", fontSize: 11,
          letterSpacing: 1, textTransform: "uppercase",
          color: "var(--purple)", textDecoration: "none",
          border: "1px solid var(--rule-strong)", borderRadius: 2,
          padding: "3px 8px",
        }}>
        ↺ switch
      </a>
    </div>
  );
}

/* ───────── workspace launcher row + initialization wizard ─────────
   Three modes share this row:
     open workspace  — pick project + agents → POST /api/workspace/launch
     initialize      — multi-step wizard to onboard a member on a machine
     installations   — inline table of all provisioned environments       */

async function postWorkspaceLaunch(body) {
  const params = new URLSearchParams(window.location.search);
  const userParam = params.get("user");
  const url = "/api/workspace/launch" + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

/* Infrastructure checklist items for the initialization wizard. */
const INFRA_ITEMS = [
  { id: "git",         label: "git",             note: "version control (required)" },
  { id: "vscode",      label: "VS Code",          note: "IDE with Claude Code extension" },
  { id: "github_cli",  label: "GitHub CLI (gh)",  note: "repo cloning & auth" },
  { id: "claude_code", label: "Claude Code (CC)", note: "AI runtime — needs API key" },
  { id: "obsidian",    label: "Obsidian",          note: "lab-notebook vault" },
];

/* ── RepoInventoryPanel: cross-machine + GitHub repo audit.

   Loads /api/inventory/repos (cached) on mount; the dashboard's
   startup hook runs a fresh scan weekly. Refresh button forces a live
   re-scan (one ``gh repo list`` + one SSH ``find .git`` per registered
   host). Per-row "Install on <machine>" opens the existing
   InstallModal with project + machine pre-filled so the user gets
   every safeguard the install wizard already has. */
function RepoInventoryPanel({ span = "c-12" }) {
  const [report, setReport] = useState(null);
  const [busy, setBusy] = useState(true);
  const [err, setErr] = useState(null);
  const [showAllGithub, setShowAllGithub] = useState(false);
  const [adoptCtx,   setAdoptCtx]   = useState(null);  // {name, path, origin}
  // Hosts the user has registered. Sourced once on mount so the table
  // columns are stable across refreshes. The inventory report also
  // returns hosts_scanned; we use the registered list (which includes
  // hosts that errored on this scan) so columns don't disappear.
  const [knownHosts, setKnownHosts] = useState([]);

  const load = async (refresh) => {
    setBusy(true); setErr(null);
    try {
      const url = refresh
        ? "/api/inventory/repos/refresh"
        : "/api/inventory/repos";
      const r = await fetch(url, { method: refresh ? "POST" : "GET" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      setReport(await r.json());
    } catch (ex) {
      setErr(String(ex.message || ex));
    } finally { setBusy(false); }
  };

  useEffect(() => {
    load(false);
    fetch("/api/hosts", { headers: { Accept: "application/json" } })
      .then(r => r.ok ? r.json() : { hosts: [] })
      .then(j => setKnownHosts((j.hosts || []).map(h => h.name)))
      .catch(() => setKnownHosts(["local"]));
  }, []);

  // Stats line for the panel header.
  const stats = report
    ? (() => {
        const rows = report.rows || [];
        const cloned = rows.filter(r => r.clones && r.clones.length > 0).length;
        const ghOnly = rows.filter(r => r.github && (!r.clones || r.clones.length === 0)).length;
        const local = rows.filter(r => r.local_only).length;
        return { total: rows.length, cloned, ghOnly, local };
      })()
    : null;

  // Display order: show rows with at least one clone first, then any
  // GitHub-only rows (only when the user toggles them in — usually a
  // long list).
  const visibleRows = (() => {
    if (!report) return [];
    const rows = report.rows || [];
    if (showAllGithub) return rows;
    return rows.filter(r => r.clones && r.clones.length > 0);
  })();

  return (
    <div className={"card " + span}>
      <header className="card-header" style={{display:"flex", alignItems:"center", justifyContent:"space-between", flexWrap:"wrap", gap:8}}>
        <h3>Repos</h3>
        <div style={{display:"flex", alignItems:"center", gap:10, flexWrap:"wrap"}}>
          {stats && (
            <span className="mono muted" style={{fontSize:11, letterSpacing:0.5}}>
              {stats.cloned} cloned · {stats.ghOnly} GitHub-only · {stats.local} local-only · {stats.total} total
            </span>
          )}
          {report && report.generated_at && (
            <span className="mono muted" style={{fontSize:10.5}}>
              scanned {report.generated_at.slice(0, 16).replace("T", " ")}
              {report.from_cache ? " (cached)" : ""}
            </span>
          )}
          <button className="btn sm" disabled={busy} onClick={() => load(true)}>
            {busy ? "…" : "Refresh"}
          </button>
          <label style={{fontSize:11, display:"inline-flex", alignItems:"center", gap:4}}>
            <input type="checkbox" checked={showAllGithub}
                   onChange={e => setShowAllGithub(e.target.checked)} />
            include {stats ? stats.ghOnly : "?"} GitHub-only rows
          </label>
        </div>
      </header>
      <div className="body" style={{padding:0}}>
        <div style={{
          padding:"10px 14px", fontSize:11.5, lineHeight:1.55,
          background:"var(--paper-2)", borderBottom:"1px solid var(--rule)",
          color:"var(--ink-2)",
        }}>
          <strong style={{fontFamily:"var(--mono)", color:"var(--purple-deep)"}}>
            clone · adopt
          </strong>{" — each host cell shows what's there now:"}
          <ul style={{margin:"4px 0 0 18px", padding:0}}>
            <li>
              <span className="mono" style={{color:"var(--muted)"}}>—</span>{" "}
              <em>nothing here.</em> Repo isn't on this host and has no GitHub origin to clone from.
            </li>
            <li>
              <span className="mono">• clone</span> + <span className="mono">↑ adopt</span> — repo is on
              this host but never made murmurent-ready. <strong>Adopt</strong> writes CHARTER + registry
              + bootstraps <code>.claude/agents/</code>. The modal asks for lead, members, and sensitivity.
            </li>
            <li>
              <span className="mono" style={{color:"var(--green)"}}>✓ murmurent</span> — fully
              murmurent-ready. See it in <em>Projects</em>.
            </li>
          </ul>
        </div>
        {err && (
          <div style={{padding:"10px 14px", color:"var(--red)", fontSize:12}}>
            {err}
          </div>
        )}
        {report && report.errors && report.errors.length > 0 && (
          <div style={{padding:"8px 14px", fontSize:11, color:"var(--tiger)"}}>
            <strong>warnings:</strong> {report.errors.join(" · ")}
          </div>
        )}
        {!busy && visibleRows.length === 0 && !err && (
          <div style={{padding:"14px 16px", color:"var(--muted)", fontSize:12, fontFamily:"var(--mono)"}}>
            No cloned repos found. Click Refresh to scan, or toggle
            "include GitHub-only rows" to see the {stats ? stats.ghOnly : "—"} repos on
            GitHub that aren't cloned anywhere.
          </div>
        )}
        {visibleRows.length > 0 && (
          <table className="dt">
            <thead><tr>
              <th>repo</th>
              <th style={{width:90}}>github</th>
              {knownHosts.map(h => (
                <th key={h} style={{width:120, textAlign:"left"}}>{h}</th>
              ))}
            </tr></thead>
            <tbody>
              {visibleRows.map((r, i) => (
                <RepoInventoryRow
                  key={r.key + ":" + i}
                  row={r}
                  knownHosts={knownHosts}
                  onAdopt={(ctx) => setAdoptCtx(ctx)}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>
      {adoptCtx && (
        <AdoptCloneModal
          clone={adoptCtx}
          onClose={(adopted) => {
            setAdoptCtx(null);
            if (adopted) load(true);
          }}
        />
      )}
    </div>
  );
}

function RepoInventoryRow({ row, knownHosts, onAdopt }) {
  const gh = row.github;
  const cloneByHost = {};
  for (const c of (row.clones || [])) cloneByHost[c.host] = c;

  // GitHub cell: green link if visible, dash otherwise.
  const ghCell = gh ? (
    <a href={`https://github.com/${gh.full_name}`} target="_blank" rel="noopener"
       className="mono" style={{fontSize:11}}>
      ✓ {gh.visibility[0]}
    </a>
  ) : (
    <span className="muted" style={{fontSize:11}}>—</span>
  );

  // Per-host cell. Four states:
  //   ✓ wig — cloned + wigamig-initialized (CHARTER + .claude/agents/)
  //   • clone + ↑ adopt — cloned but missing CHARTER.md or .claude/agents/.
  //     Adopt works for both local and SSH hosts: local writes CHARTER
  //     on the filesystem; SSH writes CHARTER + bootstraps over a
  //     single batched SSH session.
  //   + install — not cloned; clickable if a GitHub origin exists
  //   — — not applicable (no github origin to clone from)
  const hostCell = (host) => {
    const c = cloneByHost[host];
    if (c) {
      const wig = c.is_murmurent_installed;
      if (wig) {
        return (
          <span title={c.path} style={{
            fontSize:11, color:"var(--green)", fontFamily:"var(--mono)",
          }}>
            ✓ murmurent
          </span>
        );
      }
      // Cloned but not initialized — offer adopt regardless of host.
      // The endpoint branches local vs SSH; the modal passes `host`
      // through unchanged.
      return (
        <span style={{display:"inline-flex", alignItems:"center", gap:5}}>
          <span title={c.path} style={{
            fontSize:11, color:"var(--muted)", fontFamily:"var(--mono)",
          }}>
            • clone
          </span>
          {onAdopt && (
            <button className="btn sm" style={{fontSize:10.5, padding:"1px 5px"}}
                    title={host === "local"
                      ? "Promote this clone to a murmurent project"
                      : `Promote this clone on ${host} to a murmurent project (over SSH)`}
                    onClick={() => onAdopt({
                      name: row.name,
                      path: c.path,
                      origin: c.origin_url || "",
                      host: host,
                    })}>
              ↑ adopt
            </button>
          )}
        </span>
      );
    }
    return <span className="muted" style={{fontSize:11}}>—</span>;
  };

  return (
    <tr>
      <td style={{fontSize:12}}>
        <strong>{row.name}</strong>
        {row.local_only && (
          <span className="muted" style={{fontSize:10, marginLeft:6}}>
            (local-only — no GitHub origin)
          </span>
        )}
        {gh && gh.archived && (
          <span className="muted" style={{fontSize:10, marginLeft:6}}>(archived)</span>
        )}
      </td>
      <td>{ghCell}</td>
      {knownHosts.map(h => <td key={h}>{hostCell(h)}</td>)}
    </tr>
  );
}

/* ── AdoptCloneModal: promote a plain git clone to a murmurent project.
   Pops from the Repo Inventory's "↑ adopt" button on • clone rows
   for the local host. POSTs /api/inventory/adopt which writes
   CHARTER.md + runs the layer-2 CC bootstrap. Returns probes which
   we render inline so the user sees what landed and what didn't. */
function AdoptCloneModal({ clone, onClose }) {
  // Pre-fill from the row + the logged-in member so the common case
  // (lead = me, members = [me], sensitivity = standard) is one click.
  const myHandle = window.DATA.member?.handle
    ? "@" + window.DATA.member.handle
    : "@" + (window.DATA.persona === "pi" ? "pi" : "you");
  // Default agent pick mirrors InstallModal: all non-disabled agents,
  // minus `receptionist` for non-PI users (PI-only role).
  const [pickedAgents, setPickedAgents] = useState(() => {
    const all = (window.DATA.agents || []).filter(a => !a.disabled).map(a => a.name);
    const p = window.DATA.persona || "member";
    return p === "pi" ? all : all.filter(n => n !== "receptionist");
  });
  const toggleAgent = (name) => setPickedAgents(p =>
    p.includes(name) ? p.filter(n => n !== name) : [...p, name]
  );
  const [form, setForm] = useState({
    project:        clone.name || "",
    lead:           myHandle,
    members_text:   myHandle,
    sensitivity:    "standard",
    choreography:   "",
    description:    "",
    reb_number:     "",
    reb_expires:    "",
    data_residency: "",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr]   = useState(null);
  const [probes, setProbes] = useState(null);
  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr(null); setProbes(null);
    try {
      const members = form.members_text
        .split(/[\s,]+/).map(s => s.trim()).filter(Boolean);
      const agents = pickedAgents;
      const payload = {
        clone_path:  clone.path,
        project:     form.project.trim(),
        lead:        form.lead.trim(),
        members,
        sensitivity: form.sensitivity,
        description: form.description,
        agents,
        host:        clone.host || "local",
      };
      if (form.choreography) payload.choreography = form.choreography;
      if (form.sensitivity === "clinical") {
        payload.reb_number     = form.reb_number;
        payload.reb_expires    = form.reb_expires;
        payload.data_residency = form.data_residency;
      }
      const r = await fetch("/api/inventory/adopt", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(body.detail || ("HTTP " + r.status));
      setProbes(body.probes || []);
      // Refresh the whole dashboard snapshot (Projects, Installations,
      // peers, etc.) since adopt now lands rows in multiple panels.
      // The Repos panel re-fetches separately via onClose(true) below.
      if (typeof window.__murmurentFetchData === "function") {
        try { await window.__murmurentFetchData(window.DATA.persona); } catch (_) {}
      }
      // Auto-close on success after a beat so the user sees what landed.
      setTimeout(() => onClose(true), 1400);
    } catch (ex) {
      setErr(String(ex.message || ex));
    } finally { setBusy(false); }
  };

  const inp = {padding:"5px 8px", border:"1px solid var(--rule-strong)",
               borderRadius:2, fontFamily:"var(--mono)", fontSize:12,
               width:"100%", boxSizing:"border-box"};
  const lbl = {fontFamily:"var(--mono)", fontSize:10, letterSpacing:1,
               textTransform:"uppercase", color:"var(--muted)",
               marginTop:8, marginBottom:2};

  return (
    <div onClick={() => onClose(false)} style={{
      position:"fixed", inset:0, background:"rgba(32,20,54,0.55)",
      display:"flex", alignItems:"flex-start", justifyContent:"center",
      zIndex:200, padding:"40px 20px", overflowY:"auto",
    }}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} style={{
        background:"var(--card)", border:"1px solid var(--rule-strong)",
        borderRadius:2, padding:18, width:"min(640px, 96vw)",
        display:"flex", flexDirection:"column", gap:2,
      }}>
        <div className="row" style={{justifyContent:"space-between", alignItems:"baseline"}}>
          <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:18,
                      color:"var(--purple-deep)"}}>
            Adopt clone as murmurent project
          </h2>
          <button type="button" className="btn sm ghost"
                  onClick={() => onClose(false)}>✕ close</button>
        </div>
        <p className="muted" style={{fontSize:12, margin:"4px 0 6px"}}>
          {clone.host && clone.host !== "local" ? (
            <>
              Writes <code>CHARTER.md</code> + bootstraps <code>.claude/agents/</code> on
              {" "}<strong>{clone.host}</strong> over a single SSH session, at
              {" "}<code className="mono">{clone.path}</code>. After this, the
              Repo Inventory will show <strong style={{color:"var(--green)"}}>✓ murmurent</strong> for
              this clone on {clone.host}, and a row appears in Projects + Installations.
            </>
          ) : (
            <>
              Writes <code>CHARTER.md</code> at <code className="mono">{clone.path}</code>
              {" "}and bootstraps <code>.claude/agents/</code>. After this, the
              Repo Inventory will show <strong style={{color:"var(--green)"}}>✓ murmurent</strong> for
              this clone.
            </>
          )}
        </p>

        <div className="row" style={{gap:10}}>
          <div style={{flex:1}}>
            <div style={lbl}>project name</div>
            <input style={inp} value={form.project} onChange={set("project")} required />
          </div>
          <div style={{flex:1}}>
            <div style={lbl}>lead (handle)</div>
            <input style={inp} value={form.lead} onChange={set("lead")} required
                   placeholder="@the_pi" />
          </div>
        </div>

        <div style={lbl}>members (space- or comma-separated handles)</div>
        <input style={inp} value={form.members_text} onChange={set("members_text")}
               placeholder="@the_pi @alice" required />

        <div className="row" style={{gap:10}}>
          <div style={{flex:1}}>
            <div style={lbl}>sensitivity</div>
            <select style={inp} value={form.sensitivity} onChange={set("sensitivity")}>
              <option value="standard">standard</option>
              <option value="restricted">restricted</option>
              <option value="clinical">clinical</option>
            </select>
          </div>
          <div style={{flex:1}}>
            <div style={lbl}>choreography (optional)</div>
            <select style={inp} value={form.choreography} onChange={set("choreography")}>
              <option value="">— none —</option>
              <option value="drug_discovery_litl">drug_discovery_litl</option>
              <option value="clinical_cohort">clinical_cohort</option>
              <option value="method_benchmarking">method_benchmarking</option>
              <option value="imaging_phenotyping">imaging_phenotyping</option>
            </select>
          </div>
        </div>

        {form.sensitivity === "clinical" && (
          <div className="row" style={{gap:10}}>
            <div style={{flex:1}}>
              <div style={lbl}>reb_number</div>
              <input style={inp} value={form.reb_number} onChange={set("reb_number")} required />
            </div>
            <div style={{flex:1}}>
              <div style={lbl}>reb_expires (YYYY-MM-DD)</div>
              <input style={inp} value={form.reb_expires} onChange={set("reb_expires")} required />
            </div>
            <div style={{flex:1}}>
              <div style={lbl}>data_residency</div>
              <input style={inp} value={form.data_residency} onChange={set("data_residency")} required />
            </div>
          </div>
        )}

        <div style={lbl}>description (one line for the CHARTER body)</div>
        <input style={inp} value={form.description} onChange={set("description")}
               placeholder="Personal hockey analytics." />

        <div style={lbl}>
          murmurent agents to symlink — defaults to your install-wizard pick;
          click pills to deselect
        </div>
        <div style={{display:"flex", flexWrap:"wrap", gap:6}}>
          {(window.DATA.agents || []).filter(a => !a.disabled).map(a => (
            <button key={a.name} type="button" onClick={() => toggleAgent(a.name)}
              className="mono" style={{
                fontSize:11, padding:"4px 10px", border:"1px solid var(--rule-strong)",
                borderRadius:2, cursor:"pointer",
                background: pickedAgents.includes(a.name) ? "var(--purple)" : "var(--paper-2)",
                color: pickedAgents.includes(a.name) ? "#fff" : "var(--ink-2)",
              }}>
              {a.name}
            </button>
          ))}
        </div>

        {probes && (
          <div style={{marginTop:10, fontSize:11, fontFamily:"var(--mono)",
                       border:"1px solid var(--rule)", borderRadius:2, padding:"6px 8px"}}>
            {probes.map((p, i) => (
              <div key={i} style={{
                color: p.status === "ok"   ? "var(--green)"
                     : p.status === "warn" ? "var(--tiger)"
                     :                       "var(--red)",
              }}>
                {p.status === "ok" ? "✓" : p.status === "warn" ? "!" : "✗"} {p.name}: {p.detail}
              </div>
            ))}
          </div>
        )}

        <div className="row" style={{justifyContent:"flex-end", gap:6, marginTop:10, alignItems:"baseline"}}>
          {err && <span style={{color:"var(--red)", fontSize:11, marginRight:"auto"}}>{err}</span>}
          <button type="button" className="btn sm ghost"
                  onClick={() => onClose(false)} disabled={busy}>cancel</button>
          <button type="submit" className="btn sm primary" disabled={busy}>
            {busy ? "adopting…" : "adopt"}
          </button>
        </div>
      </form>
    </div>
  );
}

/* ── InstallationsBox: persistent panel — always visible.
   Members see only their own rows; PI sees all.
   Each row has an "open workspace" button that launches with that
   installation's project, machine context, and saved agent set.         */
function InstallationsBox({ span = "c-12" }) {
  const allInstallations = window.DATA.installations || [];
  const persona    = window.DATA.persona || "member";
  const myHandle   = "@" + (window.DATA.member?.handle || "");
  const rows       = persona === "pi"
    ? allInstallations
    : allInstallations.filter(i => i.member === myHandle);

  const [openRow,      setOpenRow]      = useState(null);
  const [launchingIdx, setLaunchingIdx] = useState(null);
  const [rowMsg,       setRowMsg]       = useState({});
  const [showInstall,  setShowInstall]  = useState(false);
  // Cleanup-list popup shown after a successful soft-delete. ``null``
  // means closed; a populated object means "show the modal with these
  // items so the user knows what to remove by hand".
  const [cleanup,      setCleanup]      = useState(null);

  const cols = (persona === "pi" ? 2 : 1) + 3; // member? + project + machine + status + launch

  const launchRow = async (inst, i) => {
    setLaunchingIdx(i);
    setRowMsg(m => ({ ...m, [i]: null }));
    try {
      const r = await postWorkspaceLaunch({
        project: inst.project,
        agents:  inst.agents || [],
      });
      // Remote project: backend returns vscode_url (no agents field).
      // Local project: backend returns agents = list of panes opened.
      const msg = r.vscode_url
        ? `opened VSCode Remote-SSH on ${r.host}`
        : `opened ${(r.agents || []).length} pane(s)`;
      setRowMsg(m => ({ ...m, [i]: msg }));
      setTimeout(() => setRowMsg(m => ({ ...m, [i]: null })), 3000);
    } catch (ex) {
      setRowMsg(m => ({ ...m, [i]: String(ex.message || ex) }));
    } finally {
      setLaunchingIdx(null);
    }
  };

  // Soft-delete an installation: murmurent removes ~/.murmurent/
  // installations/<project>.yaml and writes a cleanup report. It
  // intentionally does NOT touch any data on the target machine —
  // raw/, refined/, notebook/ stay. After the API returns we pop the
  // cleanup-list modal so the user sees exactly which paths they need
  // to delete themselves (if anything).
  const removeRow = async (inst) => {
    const ok = window.confirm(
      `Disconnect the "${inst.project}" installation on ` +
      (inst.machine_type === "lab_server"
        ? `${inst.username}@${inst.hostname}`
        : `laptop (${inst.username})`) + "?\n\n" +
      "murmurent will remove the row from this panel and write a cleanup\n" +
      "report. It will NOT delete any data on the target machine; the\n" +
      "next popup lists what you can delete yourself."
    );
    if (!ok) return;
    try {
      const params = new URLSearchParams(window.location.search);
      const userParam = params.get("user");
      const url = "/api/installations/" + encodeURIComponent(inst.project)
                + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
      const r = await fetch(url, { method: "DELETE" });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail || ("HTTP " + r.status));
      setCleanup({
        project: inst.project,
        report:  j.report,
        items:   j.cleanup_items || [],
      });
      if (typeof window.__murmurentFetchData === "function") {
        await window.__murmurentFetchData(window.DATA.persona);
      }
    } catch (ex) {
      window.alert("Disconnect failed: " + (ex.message || ex));
    }
  };

  return (
    <div className={"card " + span}>
      <header className="card-header" style={{display:"flex", alignItems:"center", justifyContent:"space-between"}}>
        <h3>Installations</h3>
        <div style={{display:"flex", alignItems:"center", gap:10}}>
          <span className="mono muted" style={{fontSize:10, letterSpacing:1.2, textTransform:"uppercase"}}>
            {persona === "pi" ? "all members" : "your environments"}
          </span>
          <button className="btn sm" onClick={() => setShowInstall(true)}>＋ install</button>
        </div>
      </header>
      <div className="body" style={{padding:0}}>
        {rows.length === 0 ? (
          <div style={{padding:"14px 16px", color:"var(--muted)", fontSize:12, fontFamily:"var(--mono)"}}>
            No installations yet.{" "}
            <button type="button" onClick={() => setShowInstall(true)}
              style={{background:"none", border:0, padding:0, cursor:"pointer",
                      color:"var(--purple)", fontSize:12, textDecoration:"underline"}}>
              Install now
            </button>{" "}to provision this machine for a project.
          </div>
        ) : (
          <table className="dt">
            <thead><tr>
              {persona === "pi" && <th>member</th>}
              <th>project</th>
              <th>machine</th>
              <th style={{width:72}}>status</th>
              <th style={{width:120}}></th>
            </tr></thead>
            <tbody>
              {rows.map((inst, i) => (
                <React.Fragment key={i}>
                  <tr>
                    {persona === "pi" && (
                      <td className="mono" style={{fontSize:12}}>{inst.member}</td>
                    )}
                    <td title="click to expand details" style={{
                          fontSize:12, cursor:"pointer",
                          textDecoration: openRow === i ? "none" : "underline",
                          textDecorationColor: "var(--rule-strong)",
                          textDecorationStyle: "dotted",
                          textUnderlineOffset: "3px",
                        }}
                        onClick={() => setOpenRow(openRow === i ? null : i)}>
                      <span style={{
                        display:"inline-block", width:12, color:"var(--muted)",
                        transition:"transform 0.15s",
                        transform: openRow === i ? "rotate(90deg)" : "none",
                      }}>▸</span>
                      {" "}{inst.project}
                    </td>
                    <td className="mono" title="click to expand details" style={{
                          fontSize:11, cursor:"pointer",
                          textDecoration: openRow === i ? "none" : "underline",
                          textDecorationColor: "var(--rule-strong)",
                          textDecorationStyle: "dotted",
                          textUnderlineOffset: "3px",
                        }}
                        onClick={() => setOpenRow(openRow === i ? null : i)}>
                      {inst.machine_type === "lab_server"
                        ? `${inst.username}@${inst.hostname}`
                        : `laptop (${inst.username})`}
                    </td>
                    <td>
                      <Pill tone={inst.status === "active" ? "green" : inst.status === "issues" ? "red" : ""}>
                        {inst.status}
                      </Pill>
                    </td>
                    <td style={{textAlign:"right", paddingRight:10}}>
                      {rowMsg[i] ? (
                        <span style={{fontSize:10, color:/open/i.test(rowMsg[i]) ? "var(--muted)" : "var(--red)"}}>
                          {rowMsg[i]}
                        </span>
                      ) : (
                        <button className="btn sm primary"
                          disabled={launchingIdx !== null}
                          onClick={() => launchRow(inst, i)}>
                          {launchingIdx === i ? "…" : "open workspace"}
                        </button>
                      )}
                    </td>
                  </tr>
                  {openRow === i && (
                    <tr>
                      <td colSpan={cols} style={{
                        background:"var(--paper-2)", padding:"10px 14px",
                        fontSize:11, fontFamily:"var(--mono)",
                        borderBottom:"1px solid var(--rule)",
                      }}>
                        <div style={{display:"grid", gridTemplateColumns:"repeat(2,1fr)", gap:"4px 24px"}}>
                          <div><span className="muted" style={{display:"inline-block",width:90}}>access</span>
                            <Pill tone={inst.access === "ssh" ? "purple" : "green"}>{inst.access}</Pill>
                          </div>
                          <div><span className="muted" style={{display:"inline-block",width:90}}>checked</span>{inst.last_checked}</div>
                          <div><span className="muted" style={{display:"inline-block",width:90}}>lab_base</span>{inst.lab_base}</div>
                          <div><span className="muted" style={{display:"inline-block",width:90}}>raw/</span>{_joinPath(inst.raw_path, inst.project)}</div>
                          <div><span className="muted" style={{display:"inline-block",width:90}}>refined/</span>{_joinPath(inst.refined_path, inst.project)}</div>
                          <div><span className="muted" style={{display:"inline-block",width:90}}>notebook/</span>{inst.notebook_path}</div>
                          <div><span className="muted" style={{display:"inline-block",width:90}}>components</span>{(inst.components||[]).join(", ")}</div>
                          <div><span className="muted" style={{display:"inline-block",width:90}}>agents</span>{(inst.agents||[]).join(", ")}</div>
                          {inst.issues?.length > 0 && (
                            <div style={{gridColumn:"span 2", color:"var(--red)", marginTop:4}}>
                              <span style={{display:"inline-block",width:90}}>issues</span>{inst.issues.join("; ")}
                            </div>
                          )}
                        </div>
                        <div style={{marginTop:8, paddingTop:6, borderTop:"1px dashed var(--rule)",
                                     display:"flex", justifyContent:"flex-end"}}>
                          <button
                            type="button"
                            onClick={() => removeRow(inst)}
                            title="Disconnect this installation. Writes a manual-cleanup report; does NOT delete files on the target machine."
                            style={{
                              background:"transparent", border:"1px solid var(--rule-strong)",
                              borderRadius:2, padding:"2px 8px", cursor:"pointer",
                              fontSize:11, color:"var(--red)", fontFamily:"var(--mono)",
                            }}>
                            × disconnect from murmurent
                          </button>
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {showInstall && (
        <InstallModal onClose={() => setShowInstall(false)} />
      )}
      {cleanup && (
        <InstallCleanupModal cleanup={cleanup} onClose={() => setCleanup(null)} />
      )}
    </div>
  );
}

/* InstallCleanupModal — shown immediately after a soft-delete. Lists
   the paths murmurent deliberately did NOT touch (raw/, refined/,
   notebook/, sshfs mount, etc) so the user can clean them up by hand
   if they want. The installation row in the table is already gone by
   the time this opens. Each item has a "copy" button so the user can
   paste the path into a terminal. */
function InstallCleanupModal({ cleanup, onClose }) {
  const items = cleanup.items || [];
  const copy = (text) => {
    try {
      navigator.clipboard.writeText(text);
    } catch (_) {
      // Older browsers / no permission — fall back to selecting the
      // path so the user can ⌘C manually.
      window.prompt("Copy path:", text);
    }
  };
  const sevColor = (s) =>
    s === "private" ? "var(--red)"   :
    s === "info"    ? "var(--muted)" : "var(--tiger)";
  return (
    <div onClick={onClose} style={{
      position:"fixed", inset:0, background:"rgba(32,20,54,0.55)",
      display:"flex", alignItems:"flex-start", justifyContent:"center",
      zIndex:200, padding:"40px 20px", overflowY:"auto",
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background:"var(--card)", border:"1px solid var(--rule-strong)",
        borderRadius:2, padding:18, width:"min(640px, 96vw)",
      }}>
        <div className="row" style={{justifyContent:"space-between", alignItems:"baseline"}}>
          <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:18, color:"var(--purple-deep)"}}>
            <span style={{color:"var(--green)", marginRight:6}}>✓</span>
            Installation <code>{cleanup.project}</code> disconnected
          </h2>
          <button type="button" className="btn sm ghost" onClick={onClose}>✕ close</button>
        </div>
        <p className="muted" style={{fontSize:12, margin:"6px 0 12px", lineHeight:1.55}}>
          The row is gone from <strong>Installations</strong>. murmurent did
          <strong> not </strong> delete any data on the target machine — the
          paths below stay until you remove them yourself. A full report
          was written to <code className="mono" style={{fontSize:11}}>
            {cleanup.report || "~/.murmurent/decommissions/"}
          </code>.
        </p>
        {items.length === 0 ? (
          <div className="muted" style={{fontSize:12, padding:"12px 0"}}>
            Nothing to clean up — this installation had no on-disk data
            registered with it.
          </div>
        ) : (
          <div style={{border:"1px solid var(--rule)", borderRadius:2}}>
            {items.map((it, i) => (
              <div key={i} style={{
                padding:"10px 12px",
                borderTop: i === 0 ? "0" : "1px solid var(--rule)",
                display:"flex", flexDirection:"column", gap:3,
              }}>
                <div style={{display:"flex", gap:8, alignItems:"baseline"}}>
                  <span style={{
                    fontSize:9.5, letterSpacing:1, textTransform:"uppercase",
                    fontFamily:"var(--mono)", color:sevColor(it.severity),
                    width:60,
                  }}>
                    {it.severity || "review"}
                  </span>
                  <code className="mono" style={{
                    fontSize:12, color:"var(--ink)", wordBreak:"break-all", flex:1,
                  }}>
                    {it.path}
                  </code>
                  <button type="button" className="btn sm ghost"
                          title="Copy to clipboard"
                          onClick={() => copy(it.path)}>
                    copy
                  </button>
                </div>
                <div className="muted" style={{fontSize:11.5, marginLeft:68, lineHeight:1.45}}>
                  {it.note}
                </div>
              </div>
            ))}
          </div>
        )}
        <div className="row" style={{justifyContent:"flex-end", marginTop:14}}>
          <button type="button" className="btn sm primary" onClick={onClose}>got it</button>
        </div>
      </div>
    </div>
  );
}

/* ── InstallModal: machine × project picker — derives install paths from the
   selected machine's wigamig_base and the selected project's metadata
   (including sensitivity → which git remote to clone from). The user only
   has to pick the machine and project; everything else is derived. ── */
function InstallModal({ initialProject, initialMachine, initialRepoUrl, onClose }) {
  const who = "@" + ((window.DATA.member || {}).handle || "");
  const projects = window.DATA.projects || [];
  const ls       = window.DATA.lab_settings   || {};
  const ms       = window.DATA.machine_settings || {};

  /* Machines available to install onto. Includes "this machine" (the host
     running the dashboard) plus every registered SSH host. Loaded async. */
  const [machines, setMachines] = useState([]);
  const [thisMachine, setThisMachine] = useState({ short_hostname: "", local_user: "" });
  const [selectedMachine, setSelectedMachine] = useState(initialMachine || "this");
  const [project, setProject] = useState(initialProject || projects[0]?.name || "");

  /* "New project" mode: the user clicked + install on a Repos-panel row
     whose repo has never been adopted anywhere. Project name comes from
     the GitHub repo name; install does clone + adopt + install in one
     server round-trip. The project dropdown is suppressed because the
     project doesn't exist in lab_mgmt yet. */
  const isNewProject = !!(initialProject && !projects.some(p => p.name === initialProject));

  /* Default infra + agent set so the wizard can submit immediately. The user
     can untick things in the advanced section. */
  const [infra, setInfra] = useState(INFRA_ITEMS.map(x => x.id));
  const [pickedAgents, setPickedAgents] = useState(() => {
    const all = (window.DATA.agents || []).filter(a => !a.disabled).map(a => a.name);
    const p = window.DATA.persona || "member";
    return p === "pi" ? all : all.filter(n => n !== "receptionist");
  });
  const [showAdvanced, setShowAdvanced] = useState(false);

  const [busy, setBusy] = useState(false);
  const [err, setErr]   = useState(null);
  const [done, setDone] = useState(false);

  /* Load hosts + this-machine info on mount. */
  useEffect(() => {
    fetch("/api/environment/this_machine")
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setThisMachine(d); })
      .catch(() => {});
    fetch("/api/hosts")
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d && Array.isArray(d.hosts)) setMachines(d.hosts); })
      .catch(() => {});
  }, []);

  /* Resolve the selected machine to its parameters. "this" is the local
     dashboard host (whose paths come from machine_settings). Anything else
     is keyed by host name in the registered hosts list. */
  const machineConfig = useMemo(() => {
    if (selectedMachine === "this") {
      return {
        kind: "laptop",
        name: thisMachine.short_hostname || "this machine",
        hostname: null,
        username: thisMachine.local_user || "",
        wigamig_base: ms.wigamig_base || "~/wigamig",
        obsidian_vault: ms.obsidian_vault_path || "",
        is_remote: false,
      };
    }
    const h = machines.find(m => m.name === selectedMachine);
    if (!h) return null;
    return {
      kind: "lab_server",
      name: h.name,
      hostname: h.ssh_host || h.name,
      username: h.remote_user || "",
      wigamig_base: h.wigamig_base || h.lab_vm_root || "~/wigamig",
      obsidian_vault: h.vault_root || "",
      is_remote: !!h.is_remote,
    };
  }, [selectedMachine, machines, ms, thisMachine]);

  /* Project metadata — used to pick the right git remote and to surface
     "sensitive" / "public" in the review. */
  const projectMeta = useMemo(
    () => projects.find(p => p.name === project) || {},
    [project, projects]
  );
  /* ProjectRow.sens is Literal["clinical","restricted","standard"]. We
     treat clinical + restricted as "sensitive → push to lab-base bare repo
     remote"; standard means GitHub is the origin. */
  const sens = (projectMeta.sens || "standard").toLowerCase();
  const isSensitive = sens === "clinical" || sens === "restricted";

  /* Where the project clone will come from. Sensitive → bare repo under
     lab_base/repos on the lab server. Non-sensitive → public GitHub under
     the lab's github_org. */
  const subpath = (ls.git_repos_subpath || "repos").replace(/^\/+|\/+$/g, "");
  /* repo_kind="local" forces the bare-repo remote regardless of sens; this
     handles projects that are already configured with a non-GitHub origin. */
  const forceLocalRepo = projectMeta.repo_kind === "local";
  const cloneRemote = (isSensitive || forceLocalRepo)
    ? _underLabBase(ls.lab_base, subpath + "/" + project + ".git")
    : (projectMeta.remote_url
        || `https://github.com/${ls.github_org || "hallettmiket"}/${project}`);

  const wb       = machineConfig ? machineConfig.wigamig_base : "";
  const rawPath      = _joinUnder(wb, "raw/" + project);
  const refinedPath  = _joinUnder(wb, "refined/" + project);
  const notebookPath = _joinUnder(wb, "lab_notebooks");
  // Working clones live in ~/repos/<project> on each machine (generic_cc
  // convention) — *not* under wigamig_base. Derived for display only;
  // the server resolves $HOME on the actual host.
  const repoPath     = "~/repos/" + project;

  const toggleInfra  = (id)   => setInfra(f       => f.includes(id)   ? f.filter(x => x !== id)   : [...f, id]);
  const toggleAgent  = (name) => setPickedAgents(a => a.includes(name) ? a.filter(x => x !== name) : [...a, name]);

  const canProvision = !!(project && machineConfig && wb);

  const [probes, setProbes] = useState(null);
  const [overall, setOverall] = useState(null);

  const provision = async () => {
    if (!machineConfig) return;
    setBusy(true); setErr(null); setProbes(null); setOverall(null);
    try {
      const res = await fetch("/api/workspace/initialize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          member: who, project,
          machine_type: machineConfig.kind,
          hostname: machineConfig.hostname,
          username: machineConfig.username,
          has_direct_access: !machineConfig.is_remote,
          lab_base: wb,
          raw_path: _joinUnder(wb, "raw"),
          refined_path: _joinUnder(wb, "refined"),
          notebook_path: notebookPath,
          ssh_remote: machineConfig.is_remote ? machineConfig.hostname : null,
          mount_point: null,
          infra_components: infra, agents: pickedAgents,
          // Repos-panel "+ install" on a never-adopted repo: the server
          // git-clones from this URL before projectizing. Ignored for
          // already-registered projects (the server falls back to its
          // CHARTER-derived URL).
          repo_url: initialRepoUrl || null,
          clone_if_missing: isNewProject,
        }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || ("HTTP " + res.status));
      }
      const body = await res.json();
      setProbes(body.probes || []);
      setOverall(body.overall || "ok");
      if (typeof window.__murmurentFetchData === "function") {
        try { await window.__murmurentFetchData(window.DATA.persona); } catch (_) {}
      }
      // Server returns ok=false when a required probe failed; in that
      // case keep the wizard open so the user can see what to fix.
      if (body.ok === false) {
        setErr(
          "Preflight blocked the install — fix the red rows below " +
          "(or talk to whoever owns the host) and click provision again."
        );
      } else {
        setDone(true);
      }
    } catch (ex) { setErr(String(ex.message || ex)); }
    finally { setBusy(false); }
  };

  const SEL = { style:{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2,
    fontFamily:"var(--mono)", fontSize:12, width:"100%"} };
  const LBL = { style:{fontSize:10.5, letterSpacing:1, textTransform:"uppercase",
    fontFamily:"var(--mono)", color:"var(--muted)", marginBottom:3, display:"block"} };
  const derivedStyle = {
    padding:"5px 8px", border:"1px dashed var(--rule)",
    borderRadius:2, fontFamily:"var(--mono)", fontSize:12,
    background:"var(--paper-2)", color:"var(--ink-2)",
  };

  return (
    <div onClick={onClose} style={{
      position:"fixed", inset:0, background:"rgba(32,20,54,0.55)",
      display:"flex", alignItems:"center", justifyContent:"center", zIndex:100,
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        background:"var(--card)", border:"1px solid var(--rule-strong)",
        borderRadius:2, width:"min(640px, 95vw)",
        display:"flex", flexDirection:"column", maxHeight:"92vh",
      }}>

        <div style={{background:"var(--paper-2)", borderBottom:"1px solid var(--rule)", padding:"12px 16px"}}>
          <div style={{display:"flex", justifyContent:"space-between", alignItems:"center"}}>
            <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:17, color:"var(--purple-deep)"}}>
              Install project on machine
            </h2>
            <button type="button" onClick={onClose}
                    style={{background:"none", border:0, cursor:"pointer", color:"var(--muted)", fontSize:20, lineHeight:1}}>
              ×
            </button>
          </div>
        </div>

        <div style={{padding:"16px", overflowY:"auto", flex:1, display:"flex", flexDirection:"column", gap:12}}>
          {probes && probes.length > 0 && (
            <div style={{
              padding:"10px 12px", borderRadius:2,
              background:"var(--paper-2)", border:"1px solid var(--rule)",
            }}>
              <div style={{fontSize:11, marginBottom:6, color:"var(--muted)"}}>
                preflight: <strong style={{
                  color: overall === "ok" ? "var(--green)" :
                         overall === "warn" ? "var(--tiger)" : "var(--red)",
                }}>{overall}</strong>
              </div>
              {probes.map((p, i) => (
                <div key={p.name + i} style={{
                  fontSize:12, fontFamily:"var(--mono)",
                  display:"flex", gap:8, alignItems:"baseline", marginTop:2,
                }}>
                  <span style={{
                    color: p.status === "ok" ? "var(--green)" :
                           p.status === "warn" ? "var(--tiger)" : "var(--red)",
                    width:14,
                  }}>
                    {p.status === "ok" ? "✓" : p.status === "warn" ? "!" : "✗"}
                  </span>
                  <span style={{width:140, color:"var(--muted)"}}>{p.name}</span>
                  <span style={{flex:1, color:"var(--ink)"}}>{p.detail}</span>
                </div>
              ))}
            </div>
          )}
          {done ? (
            <div style={{textAlign:"center", padding:"28px 0"}}>
              <div style={{fontSize:30, marginBottom:8, color:"var(--green)"}}>✓</div>
              <div style={{fontFamily:"var(--serif)", fontSize:16, color:"var(--purple-deep)", marginBottom:6}}>
                Provisioning checklist generated
              </div>
              <p className="muted" style={{fontSize:12, maxWidth:380, margin:"0 auto"}}>
                The new installation will appear in the Installations panel below.
              </p>
            </div>
          ) : (
            <>
              <p className="muted" style={{fontSize:12, margin:0}}>
                Pick a machine and a project — both already configured. The
                machine's <code>wigamig_base</code> dictates where data will
                land; the project's sensitivity dictates which git remote to
                clone from.
              </p>

              <div>
                <label {...LBL}>Machine</label>
                <select value={selectedMachine}
                        onChange={e => setSelectedMachine(e.target.value)}
                        style={SEL.style}>
                  <option value="this">
                    this machine{thisMachine.short_hostname ? ` (${thisMachine.short_hostname})` : ""}
                  </option>
                  {machines.filter(m => m.name !== "local").map(m => (
                    <option key={m.name} value={m.name}>
                      {m.name}{m.ssh_host && m.ssh_host !== m.name ? ` · ${m.ssh_host}` : ""}
                    </option>
                  ))}
                </select>
                <div style={{fontSize:11, color:"var(--muted)", marginTop:3}}>
                  Manage machines in <strong>Member Profile → ⚙ machines</strong>.
                </div>
              </div>

              <div>
                <label {...LBL}>Project</label>
                {isNewProject ? (
                  <>
                    <div style={derivedStyle}>
                      <strong>{project}</strong> <span className="muted">(new — will be cloned & adopted)</span>
                    </div>
                    <div style={{fontSize:11, color:"var(--muted)", marginTop:3}}>
                      one-shot clone + adopt + install: CHARTER, lab_mgmt registry,
                      installation manifest, and <code>.claude/agents/</code> all
                      land in one round-trip. You become the lead; sensitivity
                      defaults to <code>standard</code> (edit CHARTER.md after).
                    </div>
                  </>
                ) : (
                  <>
                    <select value={project} onChange={e => setProject(e.target.value)} style={SEL.style}>
                      {projects.map(p => <option key={p.name} value={p.name}>{p.name}</option>)}
                    </select>
                    {projectMeta && projectMeta.name && (
                      <div style={{fontSize:11, color:"var(--muted)", marginTop:3}}>
                        sensitivity: <Pill tone={isSensitive ? "red" : "green"}>{sens}</Pill>
                        {projectMeta.repo_kind === "local" && (
                          <> · repo is local (forced sensitive)</>
                        )}
                      </div>
                    )}
                  </>
                )}
              </div>

              {/* Derived install plan */}
              <div style={{borderTop:"1px solid var(--rule)", paddingTop:10}}>
                <h4 style={{margin:0, fontFamily:"var(--mono)", fontSize:10, letterSpacing:1.5,
                            textTransform:"uppercase", color:"var(--purple-deep)"}}>
                  Install plan (derived)
                </h4>
                <div style={{marginTop:6}}>
                  <label {...LBL}>git remote (clone from)</label>
                  <div style={derivedStyle}>{cloneRemote}</div>
                  <label {...LBL}>raw data</label>
                  <div style={derivedStyle}>{rawPath}</div>
                  <label {...LBL}>refined data</label>
                  <div style={derivedStyle}>{refinedPath}</div>
                  <label {...LBL}>lab notebook</label>
                  <div style={derivedStyle}>{notebookPath}</div>
                  <label {...LBL}>repo working clone</label>
                  <div style={derivedStyle}>{repoPath}</div>
                </div>
              </div>

              <div>
                <button type="button" className="btn sm ghost"
                        onClick={() => setShowAdvanced(v => !v)}>
                  {showAdvanced ? "▼ hide advanced" : "▶ infrastructure & agents (advanced)"}
                </button>
              </div>

              {showAdvanced && (
                <>
                  <div>
                    <label {...LBL}>Infrastructure components</label>
                    <div style={{display:"flex", flexDirection:"column", gap:5}}>
                      {INFRA_ITEMS.map(item => (
                        <label key={item.id} style={{
                          display:"flex", alignItems:"center", gap:10, cursor:"pointer",
                          padding:"7px 10px", border:"1px solid var(--rule)", borderRadius:2,
                          background: infra.includes(item.id) ? "rgba(79,38,131,0.06)" : "var(--paper-2)",
                        }}>
                          <input type="checkbox" checked={infra.includes(item.id)}
                                 onChange={() => toggleInfra(item.id)} />
                          <span style={{fontFamily:"var(--mono)", fontSize:12, minWidth:140}}>{item.label}</span>
                          <span style={{fontSize:11, color:"var(--muted)"}}>{item.note}</span>
                        </label>
                      ))}
                    </div>
                  </div>
                  <div>
                    <label {...LBL}>Murmurent agents to deploy</label>
                    <div style={{display:"flex", flexWrap:"wrap", gap:6}}>
                      {(window.DATA.agents || []).filter(a => !a.disabled).map(a => (
                        <button key={a.name} type="button" onClick={() => toggleAgent(a.name)}
                          className="mono" style={{
                            fontSize:11, padding:"4px 10px", border:"1px solid var(--rule-strong)",
                            borderRadius:2, cursor:"pointer",
                            background: pickedAgents.includes(a.name) ? "var(--purple)" : "var(--paper-2)",
                            color: pickedAgents.includes(a.name) ? "#fff" : "var(--ink-2)",
                          }}>
                          {a.name}
                        </button>
                      ))}
                    </div>
                  </div>
                </>
              )}
            </>
          )}
        </div>

        {!done ? (
          <div style={{
            padding:"10px 16px", borderTop:"1px solid var(--rule)",
            display:"flex", justifyContent:"space-between", alignItems:"center",
            background:"var(--paper-2)",
          }}>
            <span style={{fontSize:11, color:err ? "var(--red)" : "var(--muted)"}}>
              {err || (canProvision ? "ready" : "pick a machine and project")}
            </span>
            <div style={{display:"flex", gap:8}}>
              <button className="btn sm ghost" onClick={onClose}>cancel</button>
              <button className="btn sm primary" disabled={busy || !canProvision} onClick={provision}>
                {busy ? "provisioning…" : "provision"}
              </button>
            </div>
          </div>
        ) : (
          <div style={{
            padding:"10px 16px", borderTop:"1px solid var(--rule)",
            display:"flex", justifyContent:"flex-end", background:"var(--paper-2)",
          }}>
            <button className="btn sm primary" onClick={onClose}>done</button>
          </div>
        )}
      </div>
    </div>
  );
}

/* ───────── stat strip ───────── */
function Strip({ persona }) {
  const s = D.stats.seas, c = D.stats.compliance, inv = D.stats.inventory, nb = D.stats.notebook;
  return (
    <div className="strip">
      <div className="stat">
        <div className="lab">SEAs · this week</div>
        <div className="row">
          <div className="big num">{s.closed_this_week}<span className="delta up num">▲ {s.delta_pct}%</span></div>
        </div>
        <div className="sub">closed · {s.in} in-tray, {s.out} out-tray open</div>
      </div>

      <div className="stat tiger">
        <div className="lab">compliance</div>
        <div className="row">
          <div className="big num">{c.expired}</div>
          <div className="muted mono" style={{fontSize:11}}>expired</div>
        </div>
        <div className="sub">{c.expiring} expiring soon · {c.missing} missing</div>
      </div>

      <div className="stat">
        <div className="lab">inventory</div>
        <div className="row">
          <div className="big num">{inv.expired}</div>
          <div className="muted mono" style={{fontSize:11}}>expired · {inv.low} low</div>
        </div>
        <div className="sub">{inv.expiring30} expiring &lt; 30d</div>
      </div>

      <div className="stat green">
        <div className="lab">notebook</div>
        <div className="row">
          <div className="big num">{nb.entries_this_week}<span className="mono muted" style={{fontSize:11,fontWeight:400,marginLeft:4}}>/5</span></div>
          <div className="muted mono" style={{fontSize:11}}>entries</div>
        </div>
        <div className="sub">last written {nb.last_written}</div>
      </div>
    </div>
  );
}

/* (Attention "What needs you today" panel removed — its red/amber items
   are already surfaced by Compliance, Inventory, and the SEAs in-tray.) */

/* SEA detail modal: GET /api/sea/{project}/{id} -> body + frontmatter. */
function SeaDetailModal({ project, id, onClose }) {
  const [data, setData] = useState(null);
  const [err, setErr]   = useState(null);
  useEffect(() => {
    fetch("/api/sea/" + encodeURIComponent(project) + "/" + encodeURIComponent(id))
      .then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(setData)
      .catch(ex => setErr(String(ex.message || ex)));
  }, [project, id]);
  return (
    <div onClick={onClose} style={{
      position:"fixed", inset:0, background:"rgba(32,20,54,0.55)",
      display:"flex", alignItems:"center", justifyContent:"center", zIndex:100,
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        background:"var(--card)", border:"1px solid var(--rule-strong)",
        borderRadius:2, padding:0, width:"min(720px, 92vw)", maxHeight:"86vh",
        display:"flex", flexDirection:"column",
      }}>
        <div style={{
          padding:"12px 18px", borderBottom:"1px solid var(--rule)",
          display:"flex", justifyContent:"space-between", alignItems:"baseline",
        }}>
          <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:18, color:"var(--purple-deep)"}}>
            SEA #{id} · {project}
          </h2>
          <button className="btn sm ghost" onClick={onClose}>✕ close</button>
        </div>
        <div style={{padding:"14px 18px", overflowY:"auto", flex:1}}>
          {err && <div style={{color:"var(--red)"}}>{err}</div>}
          {!data && !err && <div className="muted">Loading…</div>}
          {data && (
            <>
              <div className="mono muted" style={{fontSize:11, marginBottom:10}}>
                {data.from} → {data.to} · kind <strong>{data.kind}</strong> · state <strong>{data.state}</strong>
                {data.delivery && <span> · delivery <code>{data.delivery}</code></span>}
              </div>
              <p style={{fontSize:14, lineHeight:1.5}}>{data.description}</p>
              <pre style={{
                fontSize:12, fontFamily:"var(--mono)", whiteSpace:"pre-wrap",
                background:"var(--paper-2)", padding:12, borderRadius:2,
                border:"1px solid var(--rule)", overflowX:"auto",
              }}>{data.body || "(no body)"}</pre>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/* New SEA form modal: POST /api/sea/{project}/new */
function NewSeaModal({ projects, onClose }) {
  const [project, setProject]         = useState(projects[0]?.name || "");
  const [toTarget, setToTarget]       = useState("");
  const [kind, setKind]               = useState("analysis");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr]   = useState(null);
  const submit = async (e) => {
    e.preventDefault();
    if (!toTarget.trim() || !description.trim()) {
      setErr("to: and description are required"); return;
    }
    setBusy(true); setErr(null);
    try {
      const params = new URLSearchParams(window.location.search);
      const userParam = params.get("user");
      const url = "/api/sea/" + encodeURIComponent(project) + "/new"
        + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ to_target: toTarget.trim(), kind, description: description.trim() }),
      });
      if (!res.ok) {
        let detail = "HTTP " + res.status;
        try { detail = (await res.json()).detail || detail; } catch (_) {}
        throw new Error(detail);
      }
      if (typeof window.__murmurentFetchData === "function") {
        await window.__murmurentFetchData(window.DATA.persona);
      }
      onClose();
    } catch (ex) {
      setErr(String(ex.message || ex));
    } finally { setBusy(false); }
  };
  return (
    <div onClick={onClose} style={{
      position:"fixed", inset:0, background:"rgba(32,20,54,0.55)",
      display:"flex", alignItems:"center", justifyContent:"center", zIndex:100,
    }}>
      <form onSubmit={submit} onClick={e => e.stopPropagation()} style={{
        background:"var(--card)", border:"1px solid var(--rule-strong)",
        borderRadius:2, padding:18, width:"min(560px, 92vw)",
        display:"flex", flexDirection:"column", gap:10,
      }}>
        <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:18, color:"var(--purple-deep)"}}>
          New SEA
        </h2>
        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase"}}>project</label>
        <select value={project} onChange={e => setProject(e.target.value)}
                style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2, fontFamily:"var(--mono)"}}>
          {projects.map(p => <option key={p.name} value={p.name}>{p.name}</option>)}
        </select>
        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase"}}>to (recipient handle, e.g. @bob)</label>
        <input value={toTarget} onChange={e => setToTarget(e.target.value)} placeholder="@bob"
               style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2, fontFamily:"var(--mono)"}}/>
        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase"}}>kind</label>
        <select value={kind} onChange={e => setKind(e.target.value)}
                style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2, fontFamily:"var(--mono)"}}>
          <option value="skill">skill</option>
          <option value="experiment">experiment</option>
          <option value="analysis">analysis</option>
        </select>
        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase"}}>description</label>
        <textarea value={description} onChange={e => setDescription(e.target.value)}
                  rows={4} placeholder="One-paragraph statement of what you're asking for."
                  style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2, fontFamily:"var(--serif)", fontSize:14}}/>
        {err && <div style={{color:"var(--red)", fontSize:12}}>{err}</div>}
        <div className="row" style={{justifyContent:"flex-end", gap:6, marginTop:6}}>
          <button type="button" className="btn sm ghost" onClick={onClose}>cancel</button>
          <button type="submit" className="btn sm primary" disabled={busy}>
            {busy ? "…" : "file SEA"}
          </button>
        </div>
      </form>
    </div>
  );
}

/* ───────── SEAs panel ───────── */
function SeasPanel({ seas, span="c-7" }) {
  const [tab, setTab] = useState("in");
  const [showNew, setShowNew] = useState(false);
  const [openSea, setOpenSea] = useState(null);  // {project, id}
  const filtered = seas.filter(s => s.dir === tab);
  return (
    <div className={"panel "+span}>
      <header>
        <h2>All SEAs</h2>
        <div className="row" style={{gap:10}}>
          <span className="meta">internal · cross-group inbound visible to receptionist</span>
          <div className="persona">
            <button className={tab==="in"?"on":""}  onClick={()=>setTab("in")} style={{padding:"5px 10px",fontSize:12}}>incoming&nbsp;·&nbsp;{seas.filter(s=>s.dir==="in").length}</button>
            <button className={tab==="out"?"on":""} onClick={()=>setTab("out")} style={{padding:"5px 10px",fontSize:12}}>outgoing&nbsp;·&nbsp;{seas.filter(s=>s.dir==="out").length}</button>
          </div>
          <button className="btn sm" onClick={() => setShowNew(true)}>＋ new SEA</button>
        </div>
      </header>
      {showNew && (
        <NewSeaModal
          projects={window.DATA.projects || []}
          onClose={() => setShowNew(false)}
        />
      )}
      {openSea && (
        <SeaDetailModal
          project={openSea.project}
          id={openSea.id}
          onClose={() => setOpenSea(null)}
        />
      )}
      <div className="body" style={{padding:0}}>
        <table className="dt">
          <thead>
            <tr>
              <th style={{width:50}}>id</th>
              <th style={{width:110}}>state</th>
              <th style={{width:90}}>kind</th>
              <th>description</th>
              <th style={{width:140}}>project</th>
              <th style={{width:80}}>{tab==="in"?"from":"to"}</th>
              <th style={{width:60}} className="num">age</th>
              <th style={{width:130}}></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(s => (
              <tr key={s.id}>
                <td className="num">
                  <a
                    href="#"
                    onClick={e => { e.preventDefault(); setOpenSea({project: s.project, id: s.id}); }}
                  >#{s.id}</a>
                </td>
                <td><Pill tone={s.state==="complete"?"green":s.state==="claimed"?"purple":"outline"}>{s.state}</Pill></td>
                <td className="mono muted" style={{fontSize:12}}>{s.kind}</td>
                <td>{s.desc}</td>
                <td className="mono" style={{fontSize:12}}>{s.project}</td>
                <td className="mono" style={{fontSize:12}}>{s.who}</td>
                <td className="num muted">{s.age}</td>
                <td>
                  <div className="row" style={{justifyContent:"flex-end"}}>
                    {s.state==="requested" && <SeaActionButton sea={s} action="claim"    label="claim"    tone="primary" />}
                    {s.state==="claimed"   && <SeaActionButton sea={s} action="complete" label="complete" tone="tiger"   needsDelivery />}
                    {s.state==="complete"  && <SeaActionButton sea={s} action="examine"  label="accept"   tone="primary" />}
                    {s.state==="examined"  && <SeaActionButton sea={s} action="conclude" label="review"   tone=""        />}
                    <SeaActionMore sea={s} />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ───────── project detail rows + provision buttons ───────── */
/* ───────── project detail rows + provision buttons ───────── */
const REPO_ROLE_COLOUR = { code: "#1565c0", manuscript: "#8e2f6b",
                           data: "#2e7d32", infra: "#6a1b9a" };

// The project's repo set (code + manuscript + …) + a PI "add repo" affordance.
// This is where a project gains its manuscript repo alongside its code repo.
/* (7)/(8) ProjectMembersBlock — the project's certified membership, managed by
   its LEAD (or the PI). Adding a member issues their lead-signed project card
   (one click when their key is on the roster), DMs the bundle over the
   project's Slack workspace, and invites them to the private channel; removing
   revokes the card (CRL) + kicks them. The viewer's own verified standing
   (p.my_cert, from the card bundle on THEIR machine) shows as a 🔑 chip. */
function ProjectMembersBlock({ proj: p }) {
  const persona = window.DATA.persona || "member";
  const isPI = persona === "pi";
  const viewer = ((window.DATA.member || {}).handle || "").replace(/^@/, "").toLowerCase();
  const leadNorm = (p.lead || "").replace(/^@/, "").toLowerCase();
  const canManage = isPI || (viewer && viewer === leadNorm);
  const certMembers = p.cert_members || [];
  const uncertified = p.uncertified_members || [];
  const groupMembers = window.DATA.group_members || [];
  const [busy, setBusy] = React.useState(null);   // handle currently in flight
  const [err, setErr] = React.useState(null);
  const userParam = ((window.DATA.member || {}).handle || "").replace(/^@/, "");
  const q = userParam ? "?user=" + encodeURIComponent(userParam) : "";

  const refresh = async () => {
    if (typeof window.__murmurentFetchData === "function") {
      try { await window.__murmurentFetchData(window.DATA.persona); } catch (_) {}
    }
  };

  const addMember = async (handle, enrollment) => {
    if (!handle) return;
    setBusy(handle); setErr(null);
    try {
      const r = await fetch("/api/project/" + encodeURIComponent(p.name) + "/members" + q,
        { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ handle, enrollment: enrollment || null }) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error((typeof j.detail === "string" ? j.detail : null) || r.statusText);
      if (!j.ok && j.error === "no_recorded_key") {
        // PoP fallback: the member has no attested key on the roster (carded
        // before pubkey recording, or external). Paste their enrollment.
        const pasted = window.prompt(
          "@" + handle + " has no attested key on the roster.\n\n" +
          "Ask them to run:\n    murmurent enroll --project " + p.name + "\n" +
          "and send you the JSON. Paste it here:");
        if (pasted && pasted.trim()) {
          let obj = null;
          try { obj = JSON.parse(pasted); }
          catch (_) { throw new Error("that wasn't valid enrollment JSON"); }
          setBusy(null);
          return addMember(handle, obj);
        }
        return;
      }
      const dm = j.dm || {};
      window.alert("@" + handle + " added to " + p.name + ".\n" +
                   (dm.sent ? "Card DM'd via " + (dm.workspace || "Slack") + "."
                            : "DM failed (" + (dm.detail || "?") + ") — see the server log for the bundle."));
      await refresh();
    } catch (ex) { setErr(String(ex.message || ex)); }
    finally { setBusy(null); }
  };

  const removeMember = async (handle) => {
    const h = handle.replace(/^@/, "");
    const ok = window.confirm(
      "Remove @" + h + " from " + p.name + "?\n\n" +
      "Their project certificate is revoked (CRL), they are kicked from the " +
      "private Slack channel, and GitHub access is dropped.");
    if (!ok) return;
    setBusy(h); setErr(null);
    try {
      const r = await fetch("/api/project/" + encodeURIComponent(p.name) +
                            "/members/" + encodeURIComponent(h) + q,
        { method: "DELETE", headers: { Accept: "application/json" } });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error((typeof j.detail === "string" ? j.detail : null) || r.statusText);
      await refresh();
    } catch (ex) { setErr(String(ex.message || ex)); }
    finally { setBusy(null); }
  };

  const issueCerts = async () => {
    setBusy("__batch__"); setErr(null);
    try {
      const r = await fetch("/api/project/" + encodeURIComponent(p.name) + "/issue-certs" + q,
        { method: "POST", headers: { Accept: "application/json" } });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error((typeof j.detail === "string" ? j.detail : null) || r.statusText);
      window.alert("Issued " + ((j.issued || []).length) + " certificate(s)" +
                   ((j.failed || []).length ? "; " + j.failed.length + " failed (" +
                    j.failed.map(f => f.handle + ": " + (f.detail || f.error || "?")).join("; ") + ")" : "."));
      await refresh();
    } catch (ex) { setErr(String(ex.message || ex)); }
    finally { setBusy(null); }
  };

  const inProject = new Set(
    [...certMembers, ...uncertified].map(m => m.replace(/^@/, "").toLowerCase()));
  const addable = groupMembers.filter(
    m => !inProject.has(String(m).replace(/^@/, "").toLowerCase()));

  const chip = (label, color, bg, title) => (
    <span title={title} style={{fontFamily:"var(--mono)", fontSize:10, letterSpacing:0.5,
          padding:"1px 5px", borderRadius:2, color, background:bg, marginLeft:4}}>
      {label}
    </span>
  );

  return (
    <div style={{marginBottom:8, paddingBottom:8, borderBottom:"1px solid var(--rule)"}}>
      <div style={{display:"flex", alignItems:"center", gap:8, flexWrap:"wrap"}}>
        <span style={{fontFamily:"var(--mono)", fontSize:10, letterSpacing:1,
              textTransform:"uppercase", color:"var(--muted)"}}>members</span>
        {p.my_cert && p.my_cert !== "none" && chip(
          "🔑 you: " + p.my_cert, "var(--green)", "rgba(58,138,95,0.10)",
          "Your machine holds a verified " + p.my_cert + " certificate for this project.")}
        {certMembers.map(m => {
          const h = m.replace(/^@/, "");
          return (
            <span key={m} className="mono"
                  style={{fontSize:11, padding:"2px 6px", borderRadius:2,
                          background:"rgba(79,38,131,0.08)", color:"var(--purple)",
                          display:"inline-flex", alignItems:"center", gap:4}}>
              🔑 @{h}{h.toLowerCase() === leadNorm ? " · lead" : ""}
              {canManage && h.toLowerCase() !== leadNorm && (
                <button type="button" disabled={busy === h}
                        onClick={() => removeMember(h)}
                        title={"Remove @" + h + ": revoke cert + kick from channel"}
                        style={{background:"none", border:0, cursor:"pointer",
                                color:"var(--red)", fontSize:13, padding:0, lineHeight:1}}>
                  {busy === h ? "…" : "×"}
                </button>
              )}
            </span>
          );
        })}
        {uncertified.map(m => {
          const h = m.replace(/^@/, "");
          return (
            <span key={m} className="mono"
                  style={{fontSize:11, padding:"2px 6px", borderRadius:2,
                          border:"1px dashed var(--rule-strong)", color:"var(--muted)",
                          display:"inline-flex", alignItems:"center", gap:4}}
                  title="On the member list but holds NO project certificate yet.">
              @{h} · no cert
              {canManage && (
                <button type="button" className="btn sm" disabled={busy === h}
                        onClick={() => addMember(h)}
                        style={{fontSize:10, padding:"0 5px"}}>
                  {busy === h ? "…" : "issue"}
                </button>
              )}
            </span>
          );
        })}
        {certMembers.length === 0 && uncertified.length === 0 && (
          <span className="muted" style={{fontSize:11}}>no certified members yet</span>
        )}
        {canManage && uncertified.length > 1 && (
          <button type="button" className="btn sm" disabled={busy === "__batch__"}
                  onClick={issueCerts} title="Issue certificates to every uncertified member with a roster key, DM the bundles, and invite them to the channel.">
            {busy === "__batch__" ? "…" : "issue all (" + uncertified.length + ")"}
          </button>
        )}
        {canManage && (
          <select value="" disabled={!!busy}
                  onChange={e => addMember(e.target.value.replace(/^@/, ""))}
                  style={{fontSize:11, padding:"2px 4px", fontFamily:"var(--mono)",
                          border:"1px solid var(--rule-strong)", borderRadius:2}}>
            <option value="">＋ add member…</option>
            {addable.map(h => <option key={h} value={h}>{h}</option>)}
          </select>
        )}
        {!canManage && (
          <span className="muted" style={{fontSize:10}}
                title="Only the project lead (or the PI) controls who joins.">
            membership controlled by {p.lead || "the lead"}
          </span>
        )}
        {err && <span style={{color:"var(--red)", fontSize:11}}>{err}</span>}
      </div>
    </div>
  );
}

function ProjectReposBlock({ proj: p, isPI, userParam }) {
  const repos = p.repos || [];
  const [show, setShow] = React.useState(false);
  const [f, setF] = React.useState({ repo_name: "", role: "manuscript", path: "",
                                     overleaf: true });
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState(null);
  const submit = async () => {
    setBusy(true); setErr(null);
    try {
      const q = userParam ? "?user=" + encodeURIComponent(userParam.replace(/^@/, "")) : "";
      const r = await fetch("/api/project/" + encodeURIComponent(p.name) + "/repos" + q,
        { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(f) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error((typeof j.detail === "string" ? j.detail : null) || r.statusText);
      setShow(false); setF({ repo_name: "", role: "manuscript", path: "", overleaf: true });
      if (typeof window.__murmurentFetchData === "function") {
        try { await window.__murmurentFetchData(window.DATA.persona); } catch (_) {}
      }
    } catch (ex) { setErr(String(ex.message || ex)); } finally { setBusy(false); }
  };
  return (
    <div style={{marginBottom:8, paddingBottom:8, borderBottom:"1px solid var(--rule)"}}>
      <div style={{display:"flex", alignItems:"center", gap:8, flexWrap:"wrap"}}>
        <span style={{fontFamily:"var(--mono)", fontSize:10, letterSpacing:1,
              textTransform:"uppercase", color:"var(--muted)"}}>repos</span>
        {repos.map((r, i) => (
          <span key={i} title={(r.host && r.host !== "local" ? r.host + ":" : "") + (r.path || "")}
                style={{fontFamily:"var(--mono)", fontSize:11, padding:"1px 7px",
                borderRadius:3, color:"#fff", background:REPO_ROLE_COLOUR[r.role] || "#555"}}>
            {r.role}: {r.name}{r.overleaf ? " · OL" : ""}
          </span>
        ))}
        {repos.length === 0 && <span className="muted" style={{fontSize:11}}>none assigned</span>}
        {isPI && !show && (
          <button className="btn sm" onClick={() => setShow(true)}>+ add repo</button>
        )}
      </div>
      {(() => {
        // (5) A project is a set of repos + a set of machines. Show the
        // machine set the project spans (falls back to the single host).
        const machines = (p.machines && p.machines.length) ? p.machines : [p.host || "local"];
        return (
          <div style={{display:"flex", alignItems:"center", gap:8, flexWrap:"wrap", marginTop:6}}>
            <span style={{fontFamily:"var(--mono)", fontSize:10, letterSpacing:1,
                  textTransform:"uppercase", color:"var(--muted)"}}>machines</span>
            {machines.map((m, i) => (
              <span key={i}
                    style={{fontFamily:"var(--mono)", fontSize:11, padding:"1px 7px",
                    borderRadius:3, border:"1px solid var(--rule-strong)",
                    color: m === "local" ? "var(--ink-2)" : "var(--purple)"}}>
                {m === "local" ? "local" : "🌐 " + m}{i === 0 && machines.length > 1 ? " · primary" : ""}
              </span>
            ))}
          </div>
        );
      })()}
      {isPI && show && (
        <div style={{marginTop:6, display:"flex", gap:6, flexWrap:"wrap", alignItems:"center"}}>
          <input placeholder="repo name (e.g. X_manuscript)" value={f.repo_name}
                 onChange={e => setF({...f, repo_name: e.target.value})}
                 style={{fontSize:12, padding:"2px 6px", width:180}} />
          <select value={f.role} onChange={e => setF({...f, role: e.target.value,
                  overleaf: e.target.value === "manuscript"})}
                  style={{fontSize:12, padding:"2px 4px"}}>
            <option value="code">code</option>
            <option value="manuscript">manuscript</option>
            <option value="data">data</option>
            <option value="infra">infra</option>
          </select>
          <input placeholder="path (~/repos/…)" value={f.path}
                 onChange={e => setF({...f, path: e.target.value})}
                 style={{fontSize:12, padding:"2px 6px", width:200}} />
          <label style={{fontSize:11, display:"flex", alignItems:"center", gap:3}}>
            <input type="checkbox" checked={f.overleaf}
                   onChange={e => setF({...f, overleaf: e.target.checked})} /> Overleaf
          </label>
          <button className="btn sm" disabled={busy || !f.repo_name} onClick={submit}>
            {busy ? "…" : "add"}
          </button>
          <button className="btn sm" onClick={() => { setShow(false); setErr(null); }}>cancel</button>
          {err && <span style={{color:"var(--red)", fontSize:11}}>{err}</span>}
        </div>
      )}
    </div>
  );
}

function ProjectDetailRows({ proj: p }) {
  const persona = window.DATA.persona || "member";
  const isPI = persona === "pi";
  const userParam = (window.DATA.member || {}).handle || "";
  const [busy, setBusy] = React.useState({});
  const [errs, setErrs] = React.useState({});
  const [done, setDone] = React.useState({});

  // recoverable flag: true → show "Link existing channel" escape hatch.
  // Set when the slack-create endpoint returns 409 + recoverable=true
  // because the bot can't enumerate channels to find an existing one.
  const [recoverable, setRecoverable] = React.useState({});
  // Optional Slack channel-name override the PI can type in before
  // pressing "Create Slack channel". Empty → server uses the murmurent
  // default (proj-<slug>) or the slack_channel_name already stored in
  // CHARTER. The placeholder shows whichever default would be used.
  const [slackChannelDraft, setSlackChannelDraft] = React.useState("");

  const provision = async (resource, extraQuery) => {
    setBusy(b => ({...b, [resource]: true}));
    setErrs(e => ({...e, [resource]: null}));
    setRecoverable(r => ({...r, [resource]: false}));
    try {
      const params = new URLSearchParams();
      if (userParam) params.set("user", userParam);
      if (extraQuery) {
        for (const [k, v] of Object.entries(extraQuery)) {
          if (v) params.set(k, v);
        }
      }
      const q = params.toString() ? "?" + params.toString() : "";
      const r = await fetch("/api/project/" + encodeURIComponent(p.name) + "/provision/" + resource + q,
        {method: "POST"});
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        // 409 + recoverable: surface a more useful message and unlock
        // the Link-existing-channel affordance below.
        if (typeof d.detail === "object" && d.detail && d.detail.recoverable) {
          setRecoverable(rec => ({...rec, [resource]: true}));
          throw new Error(d.detail.message || d.detail.hint || "recoverable error");
        }
        throw new Error((typeof d.detail === "string" ? d.detail : null) || r.statusText);
      }
      setDone(d => ({...d, [resource]: true}));
      if (typeof window.__murmurentFetchData === "function") {
        try { await window.__murmurentFetchData(window.DATA.persona); } catch (_) {}
      }
    } catch (ex) {
      setErrs(e => ({...e, [resource]: String(ex.message || ex)}));
    } finally {
      setBusy(b => ({...b, [resource]: false}));
    }
  };

  // Manual link path: PI pastes the channel ID. Used when the bot
  // lacks `channels:read` and can't auto-discover the existing channel.
  const linkSlackChannel = async () => {
    const cid = (window.prompt(
      "Paste the Slack channel ID for #proj-" +
      p.name.toLowerCase().replace(/_/g, "-") + ":\n\n" +
      "Find it in Slack: click the channel name → 'View channel details' " +
      "→ scroll to the bottom (Channel ID: Cxxxxxxxx)."
    ) || "").trim();
    if (!cid) return;
    setBusy(b => ({...b, slack: true}));
    setErrs(e => ({...e, slack: null}));
    try {
      const q = userParam ? "?user=" + encodeURIComponent(userParam) : "";
      const r = await fetch(
        "/api/project/" + encodeURIComponent(p.name) + "/link_slack_channel" + q,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ channel_id: cid }),
        },
      );
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || r.statusText);
      setRecoverable(rec => ({...rec, slack: false}));
      setDone(dn => ({...dn, slack: true}));
      if (typeof window.__murmurentFetchData === "function") {
        try { await window.__murmurentFetchData(window.DATA.persona); } catch (_) {}
      }
    } catch (ex) {
      setErrs(e => ({...e, slack: String(ex.message || ex)}));
    } finally {
      setBusy(b => ({...b, slack: false}));
    }
  };

  const lbl = {display:"inline-block", width:70, color:"var(--muted)"};
  const row = {marginBottom:4, display:"flex", alignItems:"center", gap:8};

  const repoKind = p.repo_kind || "github";
  const remoteUrl = p.remote_url || null;
  const remoteLabel = repoKind === "local" ? "local repo" : "github";
  const remoteRendered = repoKind === "local"
    ? (remoteUrl
        ? <span className="mono" style={{fontSize:12}}>{remoteUrl}</span>
        : <span style={{color:"var(--muted)"}}>not created</span>)
    : (p.github_pushed
        ? <a href={"https://github.com/" + p.github_repo} target="_blank" rel="noopener">{p.github_repo}</a>
        : <span style={{color:"var(--muted)"}}>not created</span>);
  const remoteCreated = repoKind === "local" ? !!remoteUrl : !!p.github_pushed;
  const createLabel = repoKind === "local" ? "Create local bare repo" : "Create GitHub repo";
  const retryLabel = repoKind === "local" ? "Retry local setup" : "Retry GitHub setup";

  return (
    <div>
      <ProjectMembersBlock proj={p} />
      <ProjectReposBlock proj={p} isPI={isPI} userParam={userParam} />
      {/* Remote — project identity (github OR local bare repo) */}
      <div style={row}>
        <span style={lbl}>{remoteLabel}</span>
        {remoteRendered}
        {isPI && !remoteCreated && !done.github && (
          <button className="btn sm" disabled={busy.github}
            onClick={() => provision("github")}>
            {busy.github ? "…" : (errs.github ? retryLabel : createLabel)}
          </button>
        )}
        {done.github && <Pill tone="green">done</Pill>}
        {errs.github && <span style={{color:"var(--red)", fontSize:11}}>{errs.github}</span>}
      </div>

      {/* Host — remote install pointer (Item 3 R3). */}
      {p.host && p.host !== "local" && (
        <div style={row}>
          <span style={lbl}>host</span>
          <span className="mono" style={{fontSize:12}}>
            {p.host}{p.remote_ssh_host && p.remote_ssh_host !== p.host
              ? " (ssh " + p.remote_ssh_host + ")"
              : ""}:{p.remote_path}
          </span>
          {p.remote_ssh_host && p.remote_path && (
            <a
              href={"vscode://vscode-remote/ssh-remote+" + p.remote_ssh_host + p.remote_path}
              className="btn sm"
              title="Open the project in VSCode Remote-SSH"
              style={{textDecoration:"none"}}>
              Open in VSCode Remote
            </a>
          )}
        </div>
      )}

      {/* Slack — project identity */}
      <div style={row}>
        <span style={lbl}>slack</span>
        {p.slack_channel_id ? (
          p.slack_url ? (
            <a href={p.slack_url} target="_blank" rel="noopener">#{p.slack_channel}</a>
          ) : (
            <span>#{p.slack_channel}</span>
          )
        ) : (
          <span style={{color:"var(--muted)"}}>no channel</span>
        )}
        {isPI && !p.slack_channel_id && !done.slack && (
          <input
            type="text"
            value={slackChannelDraft}
            onChange={e => setSlackChannelDraft(e.target.value)}
            placeholder={
              "proj-" + p.name.toLowerCase().replace(/_/g, "-") +
              "   (default — leave blank to use)"
            }
            style={{
              padding:"3px 6px", border:"1px solid var(--rule)",
              borderRadius:2, fontFamily:"var(--mono)", fontSize:11,
              minWidth: 280,
            }}
            title="Override the wigamig-conventional proj-<project> name. Leave blank to use the default."
          />
        )}
        {isPI && !p.slack_channel_id && !done.slack && (
          <button className="btn sm" disabled={busy.slack}
            onClick={() => provision("slack", { channel_name: slackChannelDraft.trim() })}>
            {busy.slack ? "…" : (errs.slack ? "Retry Slack setup" : "Create Slack channel")}
          </button>
        )}
        {isPI && !p.slack_channel_id && !done.slack && (
          <button className="btn sm" disabled={busy.slack}
            title="If the channel already exists in Slack, paste its channel ID here instead of creating a new one."
            onClick={linkSlackChannel}>
            Link existing channel…
          </button>
        )}
        {isPI && p.slack_channel_id && (
          <SlackSyncButton project={p.name} userParam={userParam} />
        )}
        {done.slack && <Pill tone="green">done — refresh to see channel</Pill>}
        {errs.slack && (
          <span style={{color:"var(--red)", fontSize:11,
                        maxWidth:520, lineHeight:1.4}}>
            {errs.slack}
          </span>
        )}
      </div>
    </div>
  );
}

/* Slack-sync button (item #11) — invite every project member to the
   project's Slack channel. Idempotent. After clicking, shows a compact
   summary: invited / already-in / unresolved. */
function SlackSyncButton({ project, userParam }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState(null);
  const run = async () => {
    setBusy(true); setErr(null); setResult(null);
    try {
      const q = userParam ? "?user=" + encodeURIComponent(userParam) : "";
      const r = await fetch(
        "/api/project/" + encodeURIComponent(project) + "/sync_slack_members" + q,
        { method: "POST", headers: { Accept: "application/json" } },
      );
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail || ("HTTP " + r.status));
      setResult(j);
    } catch (ex) {
      setErr(String(ex.message || ex));
    } finally {
      setBusy(false);
    }
  };
  return (
    <span style={{display:"inline-flex", alignItems:"center", gap:6, marginLeft:6}}>
      <button className="btn sm" disabled={busy}
        title="Add every project member to the channel (idempotent)"
        onClick={run}>
        {busy ? "…" : "sync members"}
      </button>
      {result && (
        <span style={{fontSize:11, color:"var(--muted)"}}>
          {result.invited && result.invited.length > 0 && (
            <> invited <strong style={{color:"var(--green)"}}>{result.invited.length}</strong></>
          )}
          {result.already_in && result.already_in.length > 0 && (
            <> · already in <strong>{result.already_in.length}</strong></>
          )}
          {result.unresolved && result.unresolved.length > 0 && (
            <> · <span style={{color:"var(--red)"}}
                 title={result.unresolved.map(u => u.handle + ': ' + u.reason).join('\n')}>
              {result.unresolved.length} unresolved
            </span></>
          )}
          {result.error && (
            <span style={{color:"var(--red)"}}> · {result.error}</span>
          )}
        </span>
      )}
      {err && <span style={{color:"var(--red)", fontSize:11}}>{err}</span>}
    </span>
  );
}

/* ───────── projects panel ───────── */
function ProjectsPanel({ projects, span="c-5" }) {
  const [openProj, setOpenProj] = useState(null);
  const [showNewProj, setShowNewProj] = useState(false);
  const [busyDecom, setBusyDecom] = useState(null);  // project name currently being deleted
  const persona = window.DATA.persona || "member";
  const isPI = persona === "pi";
  // Pending project-create requests — shown as an approval queue for the PI.
  const pendingCreate = (window.DATA.requests_pending || []).filter(
    r => r.kind === "project-create"
  );

  // (9) Unified delete: revoke every project certificate (CRL), archive the
  // private Slack channel, flip registry + CHARTER to archived, write the
  // decommission report. The project disappears from the dashboard entirely;
  // recovery is CLI-only.
  const deleteProj = async (name) => {
    const ok = window.confirm(
      `Delete project "${name}"?\n\n` +
      "murmurent will:\n" +
      "  • revoke every member's project certificate (CRL)\n" +
      "  • archive the project's private Slack channel\n" +
      "  • drop GitHub collaborator access\n" +
      "  • archive the record + write a decommission report\n\n" +
      "NO data files are deleted (working clone, lab-base raw/refined stay " +
      "put). The project disappears from this dashboard; recovery is " +
      "CLI-only:\n    murmurent project-unarchive --project " + name + "\n" +
      "(revoked certificates stay revoked — re-issue after unarchive)."
    );
    if (!ok) return;
    setBusyDecom(name);
    try {
      const r = await fetch(
        "/api/project/" + encodeURIComponent(name) + "/delete",
        { method: "POST", headers: { Accept: "application/json" } },
      );
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail || ("HTTP " + r.status));
      window.alert("Project '" + name + "' deleted.\n\n" +
                   (j.revoked || 0) + " certificate(s) revoked." +
                   (j.report ? "\nReport: " + j.report : ""));
      if (typeof window.__murmurentFetchData === "function") {
        await window.__murmurentFetchData(window.DATA.persona);
      }
    } catch (ex) {
      window.alert("Delete failed: " + (ex.message || ex));
    } finally {
      setBusyDecom(null);
    }
  };

  // Provision a cert-project's Slack channel + GitHub repo, membership = certs.
  const provisionProj = async (name) => {
    setBusyDecom(name);
    try {
      const r = await fetch(
        "/api/project/" + encodeURIComponent(name) + "/provision",
        { method: "POST", headers: { Accept: "application/json" } },
      );
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail || ("HTTP " + r.status));
      const s = j.slack || {}, g = j.github || {};
      const slackMsg = s.ok
        ? "Slack: channel " + (s.created ? "created" : "reused") +
          " (" + (s.channel_id || "?") + "), invited " + ((s.invited || []).length)
        : "Slack: " + (s.error || "skipped");
      const ghMsg = g.ok
        ? "GitHub: " + g.repo + ", " +
          ((g.collaborators || []).filter(c => c.status === "ok").length) + " collaborator(s)"
        : "GitHub: " + (g.error || "skipped");
      window.alert("Provisioned '" + name + "'.\n\n" + slackMsg + "\n" + ghMsg);
      if (typeof window.__murmurentFetchData === "function") {
        await window.__murmurentFetchData(window.DATA.persona);
      }
    } catch (ex) {
      window.alert("Provision failed: " + (ex.message || ex));
    } finally {
      setBusyDecom(null);
    }
  };

  // Reconcile channel/repo membership back to the certified members.
  const reconcileProj = async (name) => {
    setBusyDecom(name);
    try {
      const r = await fetch(
        "/api/project/" + encodeURIComponent(name) + "/reconcile",
        { method: "POST", headers: { Accept: "application/json" } },
      );
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail || ("HTTP " + r.status));
      const s = j.slack || {}, g = j.github || {};
      const line = (label, o, add, rm) => o && o.ok
        ? label + ": " + (o.in_sync ? "in sync" :
            "+" + ((o[add] || []).length) + " -" + ((o[rm] || []).length))
        : label + ": " + ((o && o.error) || "n/a");
      window.alert("Reconciled '" + name + "'.\n\n" +
                   line("Slack", s, "invited", "kicked") + "\n" +
                   line("GitHub", g, "added", "removed"));
      if (typeof window.__murmurentFetchData === "function") {
        await window.__murmurentFetchData(window.DATA.persona);
      }
    } catch (ex) {
      window.alert("Reconcile failed: " + (ex.message || ex));
    } finally {
      setBusyDecom(null);
    }
  };

  return (
    <div className={"panel "+span}>
      <header>
        <h2>Projects</h2>
        <div className="row" style={{gap:6}}>
          <span className="meta">
            {projects.length} active · {projects.reduce((a,p)=>a+p.open_seas,0)} open SEAs
            {pendingCreate.length > 0 && (
              <span> · <strong style={{color:"var(--tiger-deep)"}}>
                {pendingCreate.length} pending
              </strong></span>
            )}
          </span>
          <button className="btn sm" onClick={() => setShowNewProj(true)}>＋ new project</button>
        </div>
      </header>
      {showNewProj && <NewProjectModal onClose={() => setShowNewProj(false)} />}
      {isPI && pendingCreate.length > 0 && (
        <div style={{borderBottom:"2px solid var(--rule)"}}>
          <div className="mono muted" style={{fontSize:11, padding:"6px 14px 2px", textTransform:"uppercase", letterSpacing:"0.05em"}}>
            Pending approval
          </div>
          {pendingCreate.map(r => (
            <RequestActionRow key={r.id} req={r} isPI={true} />
          ))}
        </div>
      )}
      <div className="body" style={{padding:0}}>
        <table className="dt">
          <thead><tr>
            <th>project</th><th style={{width:70}}>sens.</th><th style={{width:90}}>lead</th>
            <th style={{width:60}} className="num">team</th><th style={{width:90}} className="num">open SEAs</th><th style={{width:80}}>activity</th>
            {isPI && <th style={{width:60}}></th>}
          </tr></thead>
          <tbody>
            {projects.map(p => (
              <React.Fragment key={p.name}>
                <tr style={{cursor:"pointer"}} onClick={() => setOpenProj(openProj === p.name ? null : p.name)}>
                  <td>
                    <div style={{fontWeight:500, display:"inline-flex", alignItems:"center", gap:6}}>
                      {p.name}
                      {p.is_cert && (
                        <span
                          title={"Cert-scoped project — membership is certified via "
                                 + "project cards"
                                 + ((p.cert_members && p.cert_members.length)
                                    ? ": " + p.cert_members.join(", ") : ".")}
                          style={{
                            fontFamily:"var(--mono)", fontSize:10, letterSpacing:0.5,
                            padding:"1px 5px", borderRadius:2,
                            color:"var(--blue, #3a5f8a)", background:"rgba(58,95,138,0.10)",
                            border:"1px solid rgba(58,95,138,0.30)",
                          }}>
                          🔑 cert
                        </span>
                      )}
                      {p.host && p.host !== "local" && (
                        <span
                          title={"This project's working tree lives on " + p.host +
                                 (p.remote_path ? " at " + p.remote_path : "") +
                                 ". Local ~/repos/" + p.name + "/ is a pointer placeholder."}
                          style={{
                            fontFamily:"var(--mono)", fontSize:10, letterSpacing:0.5,
                            padding:"1px 5px", borderRadius:2,
                            color:"var(--green)", background:"rgba(79,107,58,0.10)",
                            border:"1px solid rgba(79,107,58,0.30)",
                          }}>
                          🌐 {p.host}
                        </span>
                      )}
                    </div>
                    <div className="mono muted" style={{fontSize:11}}>{p.choreo}</div>
                  </td>
                  <td><Pill tone={p.sens==="clinical"?"red":""}>{p.sens}</Pill></td>
                  <td className="mono" style={{fontSize:12, paddingLeft:14}}>{p.lead}</td>
                  <td className="num">{p.members}</td>
                  <td className="num"><strong>{p.open_seas}</strong></td>
                  <td className="muted" style={{fontSize:12}}>{p.last_activity}</td>
                  {isPI && (
                    <td style={{textAlign:"right", whiteSpace:"nowrap"}} onClick={(e) => e.stopPropagation()}>
                      {p.is_cert && (
                        <>
                          <button
                            type="button"
                            title="Provision this cert-project's Slack channel + GitHub repo; sync membership to the certified members."
                            disabled={busyDecom === p.name}
                            onClick={() => provisionProj(p.name)}
                            style={{
                              background:"transparent", border:"1px solid var(--rule-strong)",
                              borderRadius:2, padding:"1px 6px", cursor:"pointer",
                              fontSize:11, color:"var(--ink)", fontFamily:"var(--mono)", marginRight:4,
                            }}>
                            provision
                          </button>
                          <button
                            type="button"
                            title="Reconcile the channel + repo membership back to the certified members."
                            disabled={busyDecom === p.name}
                            onClick={() => reconcileProj(p.name)}
                            style={{
                              background:"transparent", border:"1px solid var(--rule-strong)",
                              borderRadius:2, padding:"1px 6px", cursor:"pointer",
                              fontSize:11, color:"var(--ink)", fontFamily:"var(--mono)", marginRight:4,
                            }}>
                            reconcile
                          </button>
                        </>
                      )}
                      <button
                        type="button"
                        title="Delete this project: revoke all certificates, archive the Slack channel + record, hide from the dashboard. No data files deleted; recovery is CLI-only."
                        disabled={busyDecom === p.name}
                        onClick={() => deleteProj(p.name)}
                        style={{
                          background:"transparent", border:"1px solid var(--rule-strong)",
                          borderRadius:2, padding:"1px 6px", cursor:"pointer",
                          fontSize:11, color:"var(--red)", fontFamily:"var(--mono)",
                        }}>
                        {busyDecom === p.name ? "…" : "delete"}
                      </button>
                    </td>
                  )}
                </tr>
                {openProj === p.name && (
                  <tr>
                    <td colSpan={isPI ? 7 : 6} style={{
                      background:"var(--paper-2)",
                      padding:"10px 12px",
                      fontSize:12, fontFamily:"var(--mono)",
                      borderBottom:"1px solid var(--rule)",
                      wordBreak:"break-all",
                      overflowWrap:"anywhere",
                    }}>
                      <ProjectDetailRows proj={p} />
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
        {/* (9) Deleted projects are hidden entirely — no Decommissioned
            section. Recovery is CLI-only: murmurent project-unarchive. */}
      </div>
    </div>
  );
}

/* ───────── Western training compliance panel ─────────
   Each member × each required cert grid. Status colours match the
   Compliance heatmap (ok / amb / exp / mis) plus a "n/a" cell for
   optional certs and "✓" for one-time certs already completed. */
function TrainingCompliancePanel({ data, span="c-12" }) {
  const persona = window.DATA.persona || "member";
  const isPI = persona === "pi";
  const me = (window.DATA.member || {}).handle;
  const required = (data && data.required) || [];
  const allMembers = (data && data.members) || [];
  // Members see only their own row; PI sees everyone.
  const members = isPI ? allMembers : allMembers.filter(m => m.handle === me);
  if (required.length === 0) {
    return (
      <div className={"panel "+span}>
        <header><h2>Compliance · Western training</h2></header>
        <div className="body" style={{padding:14, fontSize:13, color:"var(--muted)"}}>
          No compliance config. Seed <code>&lt;lab-mgmt&gt;/compliance.md</code> with the
          Western required-training catalog.
        </div>
      </div>
    );
  }

  const cellSym = {
    ok: "✓", expiring: "~", expired: "!", missing: "?", "n/a": "·", one_time: "✓",
  };
  const cellClass = {
    ok: "ok", expiring: "amb", expired: "exp", missing: "mis",
    "n/a": "na", one_time: "ok",
  };

  // Roll-up summary across members for the meta header.
  const counts = {expired:0, expiring:0, missing:0};
  for (const m of members) for (const c of m.certs) {
    if (c.status === "expired") counts.expired++;
    else if (c.status === "expiring") counts.expiring++;
    else if (c.status === "missing") counts.missing++;
  }

  return (
    <div className={"panel "+span}>
      <header>
        <h2>Compliance · Western training</h2>
        <span className="meta">
          {counts.expired} expired · {counts.expiring} expiring · {counts.missing} missing
        </span>
      </header>
      <div className="body" style={{overflowX:"auto"}}>
        <table className="heat" style={{minWidth:"max-content"}}>
          <thead>
            <tr>
              <th style={{textAlign:"left", minWidth:160}}>member</th>
              {required.map(s => (
                <th key={s.code}
                    title={s.name + " (" + s.code + ")"
                      + (s.cadence_years ? " · renew every " + s.cadence_years + "y" : " · one-time")}>
                  {s.short}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {members.map(m => (
              <tr key={m.handle} style={{opacity: m.member_status === "inactive" ? 0.4 : 1}}>
                <td style={{textAlign:"left"}}>
                  <div>{m.name}</div>
                  <div className="mono muted" style={{fontSize:10}}>
                    @{m.handle} · {m.role}
                  </div>
                </td>
                {m.certs.map(cell => (
                  <td key={cell.code}>
                    <span
                      className={"cell " + (cellClass[cell.status] || "na")}
                      title={cell.code + ": " + cell.status
                             + (cell.expires ? " (expires " + cell.expires + ")" : "")}>
                      {cellSym[cell.status] || "·"}
                    </span>
                  </td>
                ))}
              </tr>
            ))}
            {members.length === 0 && (
              <tr><td colSpan={required.length + 1} className="muted"
                      style={{padding:14, textAlign:"left"}}>
                No members declared yet.
              </td></tr>
            )}
          </tbody>
        </table>
        <div className="row" style={{marginTop:10, fontSize:11, color:"var(--muted)", flexWrap:"wrap"}}>
          <span><span className="cell ok">✓</span> compliant / completed</span>
          <span><span className="cell amb">~</span> expiring</span>
          <span><span className="cell exp">!</span> expired</span>
          <span><span className="cell mis">?</span> missing</span>
          <span><span className="cell na">·</span> n/a</span>
          <span style={{marginLeft:"auto", fontStyle:"italic"}}>
            sourced from <code>&lt;lab-mgmt&gt;/compliance.md</code>
          </span>
        </div>
      </div>
    </div>
  );
}

/* ───────── compliance heatmap ───────── */
function Heatmap({ data, persona, span="c-7" }) {
  const cellLabel = { ok:"✓", exp:"!", amb:"~", mis:"?", na:"·" };
  return (
    <div className={"panel "+span}>
      <header>
        <h2>Compliance · access matrix</h2>
        <span className="meta">{persona==="pi" ? "lab-wide" : "your projects"}</span>
      </header>
      <div className="body">
        <table className="heat">
          <thead>
            <tr>
              <th>project</th>
              {data.members.map(m => <th key={m}>{m.replace("@","")}</th>)}
            </tr>
          </thead>
          <tbody>
            {data.rows.map(r => (
              <tr key={r.project}>
                <td>
                  <div>{r.project}</div>
                  <div className="mono muted" style={{fontSize:10}}>{r.sens}</div>
                </td>
                {r.cells.map((c, i) => (
                  <td key={i}>
                    <span className={"cell "+c} title={`${data.members[i]} · ${c}`}>{cellLabel[c]}</span>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <div className="row" style={{marginTop:10, fontSize:11, color:"var(--muted)"}}>
          <span><span className="cell ok">✓</span> compliant</span>
          <span><span className="cell amb">~</span> expiring</span>
          <span><span className="cell exp">!</span> expired</span>
          <span><span className="cell mis">?</span> missing</span>
          <span><span className="cell na">·</span> n/a</span>
        </div>
      </div>
    </div>
  );
}

/* ───────── lab members panel ───────── */
async function postMemberAdd(body) {
  const params = new URLSearchParams(window.location.search);
  const userParam = params.get("user");
  const url = "/api/members" + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}
async function postMemberStatus(handle, action) {
  const params = new URLSearchParams(window.location.search);
  const userParam = params.get("user");
  const url = "/api/members/" + encodeURIComponent(handle) + "/" + encodeURIComponent(action)
    + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
  const res = await fetch(url, { method: "POST", headers: { Accept: "application/json" } });
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

async function getMembersAudit() {
  const params = new URLSearchParams(window.location.search);
  const userParam = params.get("user");
  const url = "/api/members/audit" + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}
async function postAuditNotify() {
  const params = new URLSearchParams(window.location.search);
  const userParam = params.get("user");
  const url = "/api/members/audit/notify" + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
  const res = await fetch(url, { method: "POST", headers: { Accept: "application/json" } });
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

// Roster freshness + refresh: the roster lives in each member's read-only
// lab_mgmt clone; "update" = git pull --ff-only server-side, then refetch.
async function getRosterInfo() {
  const res = await fetch("/api/members/roster-info", { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}
async function postRosterRefresh() {
  const res = await fetch("/api/members/refresh", { method: "POST", headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}
// Colour + label for a member's certificate standing (from PeerRow.cert).
const CERT_TONE = { valid:"green", uncertified:"red", revoked:"red", expired:"amber", mismatch:"amber" };
const CERT_LABEL = { valid:"✓ id", uncertified:"no cert", revoked:"revoked", expired:"expired", mismatch:"mismatch" };

async function postIssueCard(body) {
  const params = new URLSearchParams(window.location.search);
  const userParam = params.get("user");
  const url = "/api/members/issue-card" + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

// Adding a member = ISSUING them a certificate. The PI pastes the enrollment
// request the person sent (from `murmurent enroll`) — their public key + a
// signature proving they hold the private key. The server verifies that proof,
// signs a member card, records it, and returns a bundle to send back. There is
// deliberately no "just type a name" path: a member on the roster always holds
// a certificate.
function AddMemberModal({ onClose }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [result, setResult] = useState(null);

  // Parse the pasted enrollment so the PI can confirm WHO they're certifying
  // before issuing. Never throws — bad/partial JSON just yields no preview.
  let parsed = null, parseErr = null;
  const trimmed = text.trim();
  if (trimmed) {
    try {
      const obj = JSON.parse(trimmed);
      const p = obj && obj.payload;
      if (p && p.pubkey && p.handle) parsed = p;
      else parseErr = "This JSON isn't an enrollment request (no payload.pubkey/handle).";
    } catch (_) { parseErr = "Not valid JSON yet — paste the whole enrollment request."; }
  }

  const issue = async () => {
    if (!parsed) { setErr("Paste a valid enrollment request first."); return; }
    setBusy(true); setErr(null);
    try {
      const r = await postIssueCard({ enrollment: JSON.parse(trimmed), dm: true });
      setResult(r);
      if (typeof window.__murmurentFetchData === "function") {
        try { await window.__murmurentFetchData(window.DATA.persona); } catch (_) {}
      }
    } catch (ex) { setErr(String(ex.message || ex)); }
    finally { setBusy(false); }
  };

  const lbl = {fontFamily:"var(--mono)", fontSize:11, letterSpacing:1,
               textTransform:"uppercase", color:"var(--muted)", marginTop:8};
  const bundleText = result ? JSON.stringify(result.bundle, null, 2) : "";

  return (
    <div onClick={onClose} style={{
      position:"fixed", inset:0, background:"rgba(32,20,54,0.55)",
      display:"flex", alignItems:"flex-start", justifyContent:"center", zIndex:100,
      padding:"40px 20px", overflowY:"auto",
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        background:"var(--card)", border:"1px solid var(--rule-strong)",
        borderRadius:2, padding:18, width:"min(560px, 94vw)",
        display:"flex", flexDirection:"column", gap:8,
      }}>
        <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:18, color:"var(--purple-deep)"}}>
          Add member — issue certificate
        </h2>

        {!result && <>
          <p className="muted" style={{fontSize:12, margin:0, lineHeight:1.5}}>
            Paste the enrollment request the person sent you (they generate it with
            <code> murmurent enroll --group &lt;lab&gt;</code>). It carries their public
            key and a proof they hold the matching private key. Issuing verifies
            that proof and puts them on the roster <em>with a certificate</em>.
          </p>
          <label style={lbl}>enrollment request (JSON)</label>
          <textarea value={text} onChange={e => setText(e.target.value)}
            placeholder='{ "payload": { "handle": "jdoe", "pubkey": "…", … }, "signature": "…" }'
            spellCheck={false}
            style={{minHeight:120, padding:"8px 9px", border:"1px solid var(--rule-strong)",
                    borderRadius:2, fontFamily:"var(--mono)", fontSize:11.5, resize:"vertical"}}/>
          {parseErr && trimmed &&
            <div className="muted" style={{fontSize:11.5, color:"var(--tiger-deep)"}}>{parseErr}</div>}
          {parsed && (
            <div style={{border:"1px solid var(--rule)", borderRadius:2, background:"var(--paper-2)",
                         padding:"8px 10px", fontSize:12.5, lineHeight:1.6}}>
              <div style={{fontWeight:600, marginBottom:2}}>You are certifying:</div>
              <div><span className="muted">handle</span> <code className="mono">@{parsed.handle}</code></div>
              {parsed.email  && <div><span className="muted">email</span> <code className="mono">{parsed.email}</code></div>}
              {parsed.github && <div><span className="muted">github</span> <code className="mono">@{String(parsed.github).replace(/^@/,"")}</code></div>}
              {parsed.slack  && <div><span className="muted">slack</span> <code className="mono">@{String(parsed.slack).replace(/^@/,"")}</code> <span className="muted" style={{fontSize:11}}>(card DM'd here)</span></div>}
              {parsed.group  && <div><span className="muted">group</span> <code className="mono">{parsed.group}</code></div>}
              <div><span className="muted">key</span> <code className="mono" style={{fontSize:10}}>{String(parsed.pubkey).slice(0,44)}…</code></div>
            </div>
          )}
          {err && <div style={{color:"var(--red)", fontSize:12}}>{err}</div>}
          <div className="row" style={{justifyContent:"flex-end", gap:6, marginTop:6}}>
            <button type="button" className="btn sm ghost" onClick={onClose}>cancel</button>
            <button type="button" className="btn sm primary" disabled={busy || !parsed} onClick={issue}>
              {busy ? "issuing…" : "verify & issue card"}
            </button>
          </div>
        </>}

        {result && <>
          <div style={{border:"1px solid var(--green)", borderRadius:2, background:"rgba(46,125,50,0.07)",
                       padding:"8px 10px", fontSize:13}}>
            ✓ Issued a certificate to <code className="mono">@{result.handle}</code> in
            <code className="mono"> {result.group}</code>. They're now on the roster, carded.
            <div className="mono muted" style={{fontSize:10, marginTop:3}}>fingerprint {String(result.fingerprint).slice(0,24)}…</div>
          </div>
          <div className="muted" style={{fontSize:12, lineHeight:1.5}}>
            {result.dm && result.dm.sent
              ? <>The card bundle was <strong>DM'd to them on Slack</strong>. They import it with the command below.</>
              : <>Send them this bundle (Slack DM couldn't be sent{result.dm && result.dm.detail ? `: ${result.dm.detail}` : ""}). They save it as <code>bundle.json</code> and run:</>}
          </div>
          <code className="mono" style={{display:"block", fontSize:11, background:"var(--paper-2)",
                border:"1px solid var(--rule)", borderRadius:2, padding:"6px 8px", overflowX:"auto"}}>
            {result.import_hint}
          </code>
          <label style={lbl}>card bundle (send to the member)</label>
          <textarea readOnly value={bundleText} spellCheck={false}
            onFocus={e => e.target.select()}
            style={{minHeight:110, padding:"8px 9px", border:"1px solid var(--rule-strong)",
                    borderRadius:2, fontFamily:"var(--mono)", fontSize:10.5, resize:"vertical"}}/>
          <div className="row" style={{justifyContent:"flex-end", gap:6, marginTop:6}}>
            <button type="button" className="btn sm ghost"
              onClick={() => { try { navigator.clipboard.writeText(bundleText); } catch (_) {} }}>
              copy bundle
            </button>
            <button type="button" className="btn sm primary" onClick={onClose}>done</button>
          </div>
        </>}
      </div>
    </div>
  );
}

function LabMembersPanel({ peers, span="c-6" }) {
  const tcpsTone = { ok:"green", expiring:"amber", missing:"red" };
  const persona = window.DATA.persona || "member";
  const isPI = persona === "pi";
  const myHandle = ((window.DATA.member || {}).handle || "").toLowerCase();
  const [showAdd, setShowAdd] = useState(false);
  const [busyHandle, setBusyHandle] = useState(null);
  const [audit, setAudit] = useState(null);     // {flagged:[...], counts, ...}
  const [auditBusy, setAuditBusy] = useState(false);
  // Roster freshness (lab_mgmt clone): {is_git, ok, detail, as_of}.
  const [roster, setRoster] = useState(null);
  const [rosterBusy, setRosterBusy] = useState(false);

  useEffect(() => {
    getRosterInfo().then(setRoster).catch(() => {});
  }, []);

  const onRosterUpdate = async () => {
    setRosterBusy(true);
    try {
      const r = await postRosterRefresh();
      setRoster(r);
      if (r.is_git && !r.ok) {
        alert("Roster pull failed: " + (r.detail || "unknown error") +
              "\n\nShowing the cached roster from " + (r.as_of ? r.as_of.slice(0, 10) : "an unknown date") + ".");
      }
      await refresh();  // re-snapshot so new/removed members appear
    } catch (ex) { alert(ex.message || ex); }
    finally { setRosterBusy(false); }
  };

  const runAudit = async () => {
    setAuditBusy(true);
    try { setAudit(await getMembersAudit()); }
    catch (ex) { alert("Audit failed: " + (ex.message || ex)); }
    finally { setAuditBusy(false); }
  };
  const notifyAudit = async () => {
    setAuditBusy(true);
    try {
      const r = await postAuditNotify();
      alert(r.notified ? "DM'd you the flagged list on Slack."
                       : "Couldn't DM (" + (r.detail || "no Slack") + ").");
    } catch (ex) { alert(ex.message || ex); }
    finally { setAuditBusy(false); }
  };

  const refresh = async () => {
    if (typeof window.__murmurentFetchData === "function") {
      try { await window.__murmurentFetchData(window.DATA.persona); } catch (_) {}
    }
  };
  const onToggle = async (peer) => {
    const action = peer.status === "active" ? "deactivate" : "activate";
    if (action === "deactivate" && !window.confirm(
      `Deactivate @${peer.handle}?\n\n` +
      "murmurent will:\n" +
      "  • flip the member's status to inactive in members/" + peer.handle + ".md\n" +
      "  • write a decommission report listing the member's project\n" +
      "    memberships, age key, and slack pointer for review\n\n" +
      "murmurent will NOT remove them from any project MEMBERS file, rotate\n" +
      "their key, or kick them from Slack — review the report and decide.\n\n" +
      "You can reactivate at any time."
    )) return;
    setBusyHandle(peer.handle);
    try {
      const result = await postMemberStatus(peer.handle, action);
      if (action === "deactivate" && result && result.report) {
        window.alert("Member @" + peer.handle + " deactivated.\n\nReport: " + result.report);
      }
      await refresh();
    } catch (ex) { alert(ex.message || ex); }
    finally { setBusyHandle(null); }
  };

  const activeCount = peers.filter(p => p.status === "active").length;
  const inactiveCount = peers.length - activeCount;
  return (
    <div className={"panel "+span}>
      <header>
        <h2>Lab members</h2>
        <div className="row" style={{gap:6}}>
          <span className="meta">
            {`${activeCount} active${inactiveCount ? " · " + inactiveCount + " inactive" : ""}`}
            {roster && roster.as_of && (
              <span title={"roster from " + (roster.path || "lab_mgmt") + ", last commit " + roster.as_of}>
                {" · as of " + roster.as_of.slice(0, 10)}
              </span>
            )}
          </span>
          <button className="btn sm" disabled={rosterBusy} onClick={onRosterUpdate}
                  title="Pull the lab_mgmt roster the PI last pushed, then refresh this panel">
            {rosterBusy ? "…" : "update"}
          </button>
          {isPI && (
            <button className="btn sm" disabled={auditBusy} onClick={runAudit}
                    title="Check every member holds a valid identity certificate">
              {auditBusy ? "…" : "audit"}
            </button>
          )}
          {isPI && (
            <button className="btn sm primary" onClick={() => setShowAdd(true)}>＋ add</button>
          )}
        </div>
      </header>
      {showAdd && <AddMemberModal onClose={() => setShowAdd(false)} />}
      {isPI && audit && (
        <div style={{margin:"0 14px 8px", padding:"8px 10px", borderRadius:2, fontSize:12.5, lineHeight:1.5,
             border:"1px solid " + (audit.counts.flagged ? "var(--red)" : "var(--green)"),
             background: audit.counts.flagged ? "rgba(194,57,43,0.06)" : "rgba(46,125,50,0.07)"}}>
          {audit.counts.flagged === 0
            ? <><strong>✓ All {audit.counts.total} members hold a valid certificate.</strong></>
            : <>
                <strong style={{color:"var(--red)"}}>{audit.counts.flagged} member(s) without a valid certificate:</strong>
                <ul style={{margin:"4px 0 6px 18px", padding:0}}>
                  {audit.flagged.map(f => (
                    <li key={f.handle}><code className="mono">@{f.handle}</code> — {f.detail}</li>
                  ))}
                </ul>
                <div className="muted" style={{fontSize:11.5}}>
                  Nobody was removed. Deactivate any that shouldn't have access using the
                  button on their row below.
                </div>
                <div className="row" style={{gap:6, marginTop:6}}>
                  <button className="btn sm ghost" disabled={auditBusy} onClick={notifyAudit}>DM me this list</button>
                  <button className="btn sm ghost" onClick={() => setAudit(null)}>dismiss</button>
                </div>
              </>}
          {audit.counts.flagged === 0 &&
            <button className="btn sm ghost" style={{marginLeft:8}} onClick={() => setAudit(null)}>dismiss</button>}
        </div>
      )}
      <div className="body" style={{padding:"6px 0"}}>
        {peers.map(p => (
          <div key={p.handle} style={{
            padding:"9px 14px", borderBottom:"1px solid var(--rule)",
            opacity: p.status === "inactive" ? 0.55 : 1,
            background: p.status === "inactive" ? "var(--paper-2)" : "transparent",
          }}>
            <div style={{display:"flex", justifyContent:"space-between", alignItems:"baseline", gap:8}}>
              <div>
                <span style={{fontWeight:500}}>{p.name}</span>
                <span className="mono muted" style={{fontSize:11, marginLeft:6}}>
                  @{p.handle} · {p.role}
                  {p.slack && <> · slack <span style={{color:"var(--purple)"}}>@{p.slack}</span></>}
                </span>
              </div>
              <div className="row" style={{gap:6}}>
                {p.status === "inactive" && <Pill tone="red">inactive</Pill>}
                {isPI && p.cert && (
                  <Pill tone={CERT_TONE[p.cert] || "amber"}
                        title={p.cert === "valid" ? "holds a valid identity certificate"
                               : "certificate issue — run audit for detail"}>
                    {CERT_LABEL[p.cert] || p.cert}
                  </Pill>
                )}
                <Pill tone={tcpsTone[p.tcps]}>tcps {p.tcps}</Pill>
              </div>
            </div>
            {(p.projects && p.projects.length > 0) && (
              <div className="row" style={{gap:4, marginTop:5, flexWrap:"wrap"}}>
                {p.projects.map(name => (
                  <span key={name} className="mono"
                        style={{fontSize:10, color:"var(--purple)",
                                background:"rgba(79,38,131,0.07)",
                                padding:"1px 6px", borderRadius:2}}>
                    {name}
                  </span>
                ))}
              </div>
            )}
            <div style={{display:"flex", justifyContent:"space-between", alignItems:"center", marginTop:5}}>
              <div className="mono muted" style={{fontSize:11, display:"flex", gap:14}}>
                <span><strong style={{color:"var(--ink-2)"}}>{p.open_seas}</strong> open SEAs</span>
                <span><strong style={{color:"var(--ink-2)"}}>{p.experiments}</strong> experiments</span>
              </div>
              {p.handle.toLowerCase() === myHandle && (
                <span className="mono muted" style={{fontSize:11}}>
                  {isPI ? "you (PI)" : "you"}
                </span>
              )}
              {isPI && p.handle.toLowerCase() !== myHandle && (
                <button
                  className="btn sm"
                  disabled={busyHandle === p.handle}
                  onClick={() => onToggle(p)}>
                  {busyHandle === p.handle
                    ? "…"
                    : (p.status === "active" ? "deactivate" : "reactivate")}
                </button>
              )}
            </div>
          </div>
        ))}
        {peers.length === 0 && (
          <div className="muted" style={{padding:"14px", fontSize:13}}>
            {isPI
              ? <>No members yet. Click <code>＋ add</code> to seed the lab roster.</>
              : <>No roster found on this machine. Your lab_mgmt clone may be
                 missing{roster && roster.path ? <> (expected at <code>{roster.path}</code>)</> : null} —
                 clone it per <code>docs/lab_mgmt.md</code>, then click <code>update</code>.</>}
          </div>
        )}
      </div>
    </div>
  );
}

/* ───────── security access panel (PI only) ─────────
   Grant / revoke the wigamig-level ``lab_sudo`` flag for lab members.
   Gates /security dashboard visibility. NOT the same as OS-level sudo
   on the lab server — that's a separate sysadmin grant. See
   docs/security-dashboard.md#tier-2-setup for the full picture. */
async function postLabSudo(handle, grant) {
  const url = "/api/members/" + encodeURIComponent(handle) + "/lab_sudo";
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ grant }),
  });
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

function SecurityAccessPanel({ peers, span = "c-12" }) {
  // Compute lab_sudo set from the peers list. Peers carry ``lab_sudo``
  // (boolean) when present in member frontmatter. PI is implicitly
  // included regardless of flag — they're always authorised.
  const me = window.DATA.member || {};
  const pi = window.DATA.pi || {};
  const piHandle = pi.handle || "";
  const [busy, setBusy] = useState(null);
  const grantees = (peers || []).filter(p => p.lab_sudo);
  const candidates = (peers || []).filter(p => !p.lab_sudo && p.status === "active"
                                              && p.handle !== piHandle);
  const onToggle = async (peer, grant) => {
    if (!grant && !window.confirm(
      `Revoke lab_sudo for @${peer.handle}?\n\n` +
      "They will lose access to /security dashboard. Granted again later restores access."
    )) return;
    setBusy(peer.handle);
    try {
      await postLabSudo(peer.handle, grant);
      if (typeof window.__murmurentFetchData === "function") {
        try { await window.__murmurentFetchData(window.DATA.persona); } catch (_) {}
      }
    } catch (ex) { alert("lab_sudo update failed: " + (ex.message || ex)); }
    finally { setBusy(null); }
  };
  return (
    <div className={"panel " + span}>
      <header>
        <h2>Security dashboard access (lab_sudo)</h2>
        <div className="row" style={{gap:8}}>
          <a className="btn sm" href={`/security?user=${encodeURIComponent(me.handle || "")}`}
             target="_blank" rel="noopener">open /security ↗</a>
        </div>
      </header>
      <div className="body" style={{padding:"10px 14px", fontSize:12, lineHeight:1.55}}>
        <p className="muted" style={{margin:"0 0 10px 0"}}>
          Lab members with <code>lab_sudo: true</code> can open the per-lab
          security dashboard at <code>/security</code>. You (PI) always have
          access. This is the wigamig-level flag — OS-level sudo on the lab
          server is a separate sysadmin grant (see <code>docs/security-dashboard.md</code>).
        </p>

        <div style={{marginBottom:14}}>
          <div className="mono" style={{fontSize:11, color:"var(--muted)",
                                          letterSpacing:1, textTransform:"uppercase",
                                          marginBottom:6}}>
            currently granted ({grantees.length + 1 /* +PI */})
          </div>
          <div className="row" style={{gap:6, flexWrap:"wrap"}}>
            <span className="mono" style={{
              fontSize:11, padding:"2px 8px", border:"1px solid var(--purple)",
              borderRadius:2, color:"var(--purple)",
            }}>
              @{piHandle} <span className="muted">(PI · implicit)</span>
            </span>
            {grantees.map(p => (
              <span key={p.handle} className="mono" style={{
                fontSize:11, padding:"2px 8px", border:"1px solid var(--rule-strong)",
                borderRadius:2, display:"inline-flex", gap:6, alignItems:"center",
              }}>
                @{p.handle}
                <button className="btn xs" disabled={busy === p.handle}
                        onClick={() => onToggle(p, false)}
                        style={{fontSize:10, padding:"0 6px"}}>
                  {busy === p.handle ? "…" : "revoke"}
                </button>
              </span>
            ))}
            {grantees.length === 0 && (
              <span className="muted" style={{fontSize:11}}>
                no explicit grants — only you have access
              </span>
            )}
          </div>
        </div>

        <div>
          <div className="mono" style={{fontSize:11, color:"var(--muted)",
                                          letterSpacing:1, textTransform:"uppercase",
                                          marginBottom:6}}>
            grant access to a lab member
          </div>
          {candidates.length === 0 ? (
            <span className="muted" style={{fontSize:11}}>
              all active lab members already have lab_sudo.
            </span>
          ) : (
            <div className="row" style={{gap:6, flexWrap:"wrap"}}>
              {candidates.map(p => (
                <button key={p.handle} className="btn sm"
                        disabled={busy === p.handle}
                        onClick={() => onToggle(p, true)}>
                  {busy === p.handle ? "…" : "+ @" + p.handle}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ───────── agents panel ───────── */
async function postAgentAction(name, action, params = {}) {
  const qs = new URLSearchParams(params).toString();
  const url = "/api/agents/" + encodeURIComponent(name) + "/" + encodeURIComponent(action)
    + (qs ? "?" + qs : "");
  const res = await fetch(url, { method: "POST", headers: { Accept: "application/json" } });
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

function AgentToggleButton({ agent }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr]   = useState(null);
  const refresh = async () => {
    if (typeof window.__murmurentFetchData === "function") {
      try { await window.__murmurentFetchData(window.DATA.persona); } catch (_) {}
    }
  };
  const onToggle = async () => {
    setBusy(true); setErr(null);
    try {
      await postAgentAction(agent.name, agent.disabled ? "enable" : "disable");
      await refresh();
    } catch (ex) { setErr(String(ex.message || ex)); }
    finally { setBusy(false); }
  };
  const onModelChange = async (e) => {
    const newModel = e.target.value;
    if (!newModel || newModel === agent.model) return;
    setBusy(true); setErr(null);
    try {
      await postAgentAction(agent.name, "set_model", { model: newModel });
      await refresh();
    } catch (ex) { setErr(String(ex.message || ex)); }
    finally { setBusy(false); }
  };

  if (agent.freeze === "frozen") {
    return (
      <span className="mono muted" style={{fontSize:10, letterSpacing:1}}
            title="Frozen agents change via PR against agents/<name>.md">
        FROZEN
      </span>
    );
  }
  return (
    <span style={{display:"inline-flex", alignItems:"center", gap:6}}>
      <select
        value={agent.model || ""}
        onChange={onModelChange}
        disabled={busy}
        title="Pick the model this agent uses"
        style={{
          fontFamily:"var(--mono)", fontSize:11,
          padding:"2px 6px", border:"1px solid var(--rule-strong)",
          borderRadius:2, background:"#fff", color:"var(--ink)",
        }}>
        <option value="">model…</option>
        {/* Values are floating aliases (what gets written to the agent's
            model: frontmatter); the parenthetical is just the current tier
            version for display — keep in sync with VALID_MODELS in
            dashboard/server.py when models bump. */}
        <option value="opus">opus (4.8)</option>
        <option value="sonnet">sonnet (5)</option>
        <option value="haiku">haiku (4.5)</option>
      </select>
      <button className="btn sm" disabled={busy} onClick={onToggle}>
        {busy ? "…" : (agent.disabled ? "enable" : "disable")}
      </button>
      {err && <span style={{fontSize:10, color:"var(--red)"}}>{err}</span>}
    </span>
  );
}

function AgentsPanel({ agents, span="c-4" }) {
  const list = agents || [];
  // Render as a 2-column compact grid since this panel is now full-width.
  return (
    <div className={"panel "+span}>
      <header>
        <h2>Agents</h2>
        <span className="meta">
          {list.length} installed · {list.filter(a => a.disabled).length} disabled
        </span>
      </header>
      <div className="body" style={{padding:0}}>
        <div style={{display:"grid", gridTemplateColumns:"repeat(2, 1fr)"}}>
          {list.map(a => (
            <div key={a.name} style={{
              padding:"9px 14px", borderBottom:"1px solid var(--rule)",
              borderRight:"1px solid var(--rule)",
              opacity: a.disabled ? 0.55 : 1,
            }}>
              <div style={{display:"flex", justifyContent:"space-between", alignItems:"baseline", gap:8}}>
                <div>
                  <span style={{fontWeight:500, textTransform:"capitalize"}}>{a.name}</span>
                  {a.disabled && (
                    <span className="mono muted" style={{fontSize:10, marginLeft:8}}>
                      DISABLED
                    </span>
                  )}
                </div>
                <AgentToggleButton agent={a} />
              </div>
              <div className="muted" style={{fontSize:12, marginTop:3, lineHeight:1.4}}>
                {a.description}
              </div>
              <div className="mono muted" style={{fontSize:10, marginTop:4, letterSpacing:1}}>
                {a.model && <span>{a.model.toUpperCase()}</span>}
                {a.required_tools && a.required_tools.length > 0 && (
                  <span style={{marginLeft:10}}>
                    · {a.required_tools.length} tool{a.required_tools.length === 1 ? "" : "s"}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
        {list.length === 0 && (
          <div className="muted" style={{padding:"14px", fontSize:13}}>
            No agents installed. Run <code className="mono">murmurent agent list</code>.
          </div>
        )}
      </div>
    </div>
  );
}

/* ───────── join-requests panel ─────────
   PI lens: pending queue with approve/decline buttons.
   Member lens: viewer's own outgoing requests with status pill. */
async function postRequestAction(id, action, body = {}) {
  const params = new URLSearchParams(window.location.search);
  const userParam = params.get("user");
  const url = "/api/request/" + encodeURIComponent(id) + "/" + encodeURIComponent(action)
    + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
  const res = await fetch(url, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}
async function postCreateProjectRequest(payload) {
  const params = new URLSearchParams(window.location.search);
  const userParam = params.get("user");
  const url = "/api/request/create-project" + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
  const res = await fetch(url, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

function NewProjectModal({ onClose }) {
  const [name, setName] = useState("");
  const [selectedMembers, setSelectedMembers] = useState([]);  // chips
  const [otherInput, setOtherInput] = useState("");            // free-text
  const [sensitivity, setSensitivity] = useState("standard");
  const [justification, setJustification] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const groupMembers = window.DATA.group_members || [];
  // Phase 16: pick where the git repo lives. ``local`` is required for
  // clinical / industrial data that must not leave the lab VM.
  const [repoKind, setRepoKind] = useState("github");
  const ms = window.DATA.machine_settings || {};
  const ls = window.DATA.lab_settings || {};
  const defaultLocalRoot = (ms.lab_base && ls.git_repos_subpath)
    ? ms.lab_base.replace(/\/$/, "") + "/" + ls.git_repos_subpath
    : (ms.lab_base ? ms.lab_base.replace(/\/$/, "") + "/git_repos" : "");
  const [localRepoRoot, setLocalRepoRoot] = useState(defaultLocalRoot);
  // Slack channel name override. Empty = murmurent default of
  // ``proj-<project>``. The placeholder updates live as the user types
  // the project name so it's obvious what will be created if they
  // leave this blank. Validation is server-side (normalize_channel_name).
  const [slackChannelName, setSlackChannelName] = useState("");
  // (5) A project is a set of EXISTING repos + a set of machines. ``machines``
  // is the full host set the project lives on (populated from /api/hosts).
  // ``attachRepos`` is the project's repo set, picked from the clones the
  // user already has (folders come from the machine's Repo location dirs —
  // ~/repos etc.); project creation never scaffolds a new repo. Each option
  // carries the hosts it exists on so the picker shows where a repo lives.
  const [hosts, setHosts] = useState([{ name: "local", kind: "local", is_remote: false, description: "this laptop" }]);
  const [selectedMachines, setSelectedMachines] = useState(["local"]);
  const [repoOptions, setRepoOptions] = useState([]);
  const [attachRepos, setAttachRepos] = useState([]);
  useEffect(() => {
    let cancelled = false;
    fetch("/api/hosts", { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(r => r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status)))
      .then(j => { if (!cancelled && Array.isArray(j.hosts) && j.hosts.length) setHosts(j.hosts); })
      .catch(err => console.warn("[murmurent] /api/hosts failed; defaulting to local", err));
    fetch("/api/inventory/repos", { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(r => r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status)))
      .then(j => {
        if (cancelled) return;
        const opts = [];
        for (const row of (j.rows || [])) {
          const nm = (row && row.name) || "";
          const clones = (row && row.clones) || [];
          // Only repos that actually EXIST somewhere are selectable —
          // GitHub-only rows can't form a project (clone them first).
          if (!nm || clones.length === 0) continue;
          if (!opts.some(o => o.name === nm)) {
            opts.push({ name: nm, hosts: [...new Set(clones.map(c => c.host))] });
          }
        }
        setRepoOptions(opts);
      })
      .catch(err => console.warn("[murmurent] /api/inventory/repos failed", err));
    return () => { cancelled = true; };
  }, []);
  const toggleMachine = (nm) =>
    setSelectedMachines(sel => sel.includes(nm) ? sel.filter(m => m !== nm) : [...sel, nm]);
  const toggleRepo = (nm) =>
    setAttachRepos(sel => sel.includes(nm) ? sel.filter(r => r !== nm) : [...sel, nm]);

  const addFromDropdown = (handle) => {
    if (!handle) return;
    if (!selectedMembers.includes(handle)) {
      setSelectedMembers([...selectedMembers, handle]);
    }
  };
  const addFromInput = () => {
    const h = otherInput.trim();
    if (!h) return;
    const norm = h.startsWith("@") ? h : "@" + h;
    if (!selectedMembers.includes(norm)) {
      setSelectedMembers([...selectedMembers, norm]);
    }
    setOtherInput("");
  };
  const removeMember = (h) => setSelectedMembers(selectedMembers.filter(m => m !== h));

  // (10) Inter-group detection (client-side hint; the server check is
  // authoritative): any selected member not in this lab's roster is external.
  const normSet = new Set(groupMembers.map(m => String(m).replace(/^@/, "").toLowerCase()));
  const externalMembers = selectedMembers.filter(
    m => !normSet.has(String(m).replace(/^@/, "").toLowerCase()));
  const [slackWorkspace, setSlackWorkspace] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    if (!name.trim()) { setErr("project name is required"); return; }
    if (selectedMembers.length === 0) { setErr("add at least one member"); return; }
    if (selectedMachines.length === 0) { setErr("select at least one machine"); return; }
    if (attachRepos.length === 0) {
      setErr("select at least one repo — projects are built from repos you " +
             "already have (clone or create the repo first)");
      return;
    }
    if (externalMembers.length > 0 && !slackWorkspace.trim()) {
      setErr("members span multiple groups — name the agreed shared Slack workspace");
      return;
    }
    setBusy(true); setErr(null);
    try {
      await postCreateProjectRequest({
        project: name.trim(),
        proposed_members: selectedMembers,
        sensitivity,
        justification: justification.trim(),
        repo_kind: repoKind,
        local_repo_root: repoKind === "local" ? (localRepoRoot.trim() || null) : null,
        host: selectedMachines[0] || "local",
        machines: selectedMachines,
        attach_repos: attachRepos,
        slack_channel_name: slackChannelName.trim() || null,
        slack_workspace: slackWorkspace.trim() || null,
      });
      if (typeof window.__murmurentFetchData === "function") {
        await window.__murmurentFetchData(window.DATA.persona);
      }
      onClose();
    } catch (ex) { setErr(String(ex.message || ex)); }
    finally { setBusy(false); }
  };

  const availableMembers = groupMembers.filter(m => !selectedMembers.includes(m));

  return (
    <div onClick={onClose} style={{
      position:"fixed", inset:0, background:"rgba(32,20,54,0.55)",
      display:"flex", alignItems:"center", justifyContent:"center", zIndex:100,
    }}>
      <form onSubmit={submit} onClick={e => e.stopPropagation()} style={{
        background:"var(--card)", border:"1px solid var(--rule-strong)",
        borderRadius:2, padding:18, width:"min(560px, 92vw)",
        display:"flex", flexDirection:"column", gap:8,
      }}>
        <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:18, color:"var(--purple-deep)"}}>
          Propose new project
        </h2>
        <p className="muted" style={{fontSize:12, margin:0}}>
          PI approval required. On approval, murmurent scaffolds the project repo
          and adds the proposed members to MEMBERS.
        </p>
        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase", marginTop:6}}>name (snake_case)</label>
        <input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. dcis_imaging_genomics"
               style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2, fontFamily:"var(--mono)"}}/>

        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase"}}>slack channel (optional)</label>
        <input value={slackChannelName}
               onChange={e => setSlackChannelName(e.target.value)}
               placeholder={
                 (name.trim()
                   ? "proj-" + name.trim().toLowerCase().replace(/_/g, "-")
                   : "proj-<project>") + "   (default — leave blank to use)"
               }
               style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2, fontFamily:"var(--mono)"}}/>
        <div className="muted" style={{fontSize:11, marginTop:-2, lineHeight:1.5}}>
          Override only when the lab already has a channel that doesn't follow
          the <code>proj-&lt;project&gt;</code> convention. Lowercase, max 80
          chars, only letters / digits / <code>-</code> / <code>_</code>.
        </div>

        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase"}}>proposed members</label>
        {/* chips: already-selected handles */}
        {selectedMembers.length > 0 && (
          <div className="row" style={{flexWrap:"wrap", gap:4}}>
            {selectedMembers.map(h => (
              <span key={h} className="mono"
                    style={{fontSize:11, padding:"2px 6px",
                            background:"rgba(79,38,131,0.10)",
                            color:"var(--purple)", borderRadius:2,
                            display:"inline-flex", alignItems:"center", gap:4}}>
                {h}
                <button type="button" onClick={() => removeMember(h)}
                        style={{background:"none", border:0, cursor:"pointer",
                                color:"var(--purple)", fontSize:14, padding:0, lineHeight:1}}
                        title={"remove " + h}>×</button>
              </span>
            ))}
          </div>
        )}
        {/* dropdown: pick from known group members */}
        <div className="row" style={{gap:6}}>
          <select value="" onChange={e => addFromDropdown(e.target.value)}
                  disabled={availableMembers.length === 0}
                  style={{flex:1, padding:"6px 8px", border:"1px solid var(--rule-strong)",
                          borderRadius:2, fontFamily:"var(--mono)"}}>
            <option value="">
              {availableMembers.length === 0 ? "(all known members added)" : "+ add from group…"}
            </option>
            {availableMembers.map(h => (
              <option key={h} value={h}>{h}</option>
            ))}
          </select>
        </div>
        {/* free-text: handle not yet known */}
        <div className="row" style={{gap:6}}>
          <input value={otherInput} onChange={e => setOtherInput(e.target.value)}
                 onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); addFromInput(); }}}
                 placeholder="…or type an unknown @handle"
                 style={{flex:1, padding:"6px 8px", border:"1px solid var(--rule-strong)",
                         borderRadius:2, fontFamily:"var(--mono)"}}/>
          <button type="button" className="btn sm" onClick={addFromInput}>add</button>
        </div>

        {/* (10) Inter-group: members from outside this lab require an agreed
            shared Slack workspace — the project channel + certificate DMs go
            through it. Server-side validation is authoritative; creation
            HALTS if the workspace (or its bot token) is missing. */}
        {externalMembers.length > 0 && (
          <>
            <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase", color:"var(--tiger-deep)"}}>
              shared slack workspace (required — inter-group project)
            </label>
            <div className="muted" style={{fontSize:11, marginTop:-2, lineHeight:1.5}}>
              {externalMembers.join(", ")} {externalMembers.length === 1 ? "is" : "are"} not
              in this lab — the groups must decide on a Slack workspace. Enter the
              group id whose workspace hosts the project (bot token expected at
              <code> ~/.config/murmurent/groups/&lt;workspace&gt;/slack-token</code>).
            </div>
            <input value={slackWorkspace}
                   onChange={e => setSlackWorkspace(e.target.value)}
                   placeholder="e.g. mh  (or a dedicated shared workspace id)"
                   style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2, fontFamily:"var(--mono)"}}/>
          </>
        )}

        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase"}}>sensitivity</label>
        <select value={sensitivity} onChange={e => setSensitivity(e.target.value)}
                style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2, fontFamily:"var(--mono)"}}>
          <option value="standard">standard</option>
          <option value="restricted">restricted</option>
          <option value="clinical">clinical</option>
        </select>

        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase"}}>machines</label>
        <div className="muted" style={{fontSize:11, marginTop:-2, marginBottom:2, lineHeight:1.5}}>
          A project is a set of machines. Pick every host the project lives on;
          the first selected is the primary scaffold target.
        </div>
        <div style={{display:"flex", flexWrap:"wrap", gap:6}}>
          {hosts.map(h => {
            const on = selectedMachines.includes(h.name);
            const primary = on && selectedMachines[0] === h.name;
            return (
              <label key={h.name}
                     style={{display:"inline-flex", alignItems:"center", gap:5,
                             fontSize:12, padding:"3px 8px", cursor:"pointer",
                             border:"1px solid " + (on ? "var(--purple)" : "var(--rule-strong)"),
                             background: on ? "rgba(79,38,131,0.10)" : "transparent",
                             color: on ? "var(--purple)" : "var(--ink-2)", borderRadius:2}}>
                <input type="checkbox" checked={on} onChange={() => toggleMachine(h.name)} />
                <span className="mono">{h.name}</span>
                {h.is_remote
                  ? <span className="muted" style={{fontSize:10}}>({h.ssh_host || h.name})</span>
                  : <span className="muted" style={{fontSize:10}}>this laptop</span>}
                {primary && <span style={{fontSize:10, color:"var(--tiger)"}}>· primary</span>}
              </label>
            );
          })}
        </div>
        {selectedMachines.some(m => m !== "local") && (
          <div className="muted" style={{fontSize:11, marginTop:2}}>
            The full machine set is recorded on the project;
            <code> {selectedMachines[0]}</code> is the primary host.
          </div>
        )}

        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase", marginTop:6}}>repos (select at least one)</label>
        <div className="muted" style={{fontSize:11, marginTop:-2, marginBottom:2, lineHeight:1.5}}>
          A project is a set of repos you <strong>already have</strong> — pick
          them from your machines' repo folders (creating a project never
          creates a repo; clone or <code>git init</code> it first, then come
          back). Pair code with its manuscript repo, the way murmurent itself
          is code + manuscript.
        </div>
        {repoOptions.length === 0 ? (
          <div className="muted" style={{fontSize:11}}>
            No repos found on your machines — clone one into a Repo location
            dir (e.g. <code>~/repos</code>) first, then refresh the Repos panel.
          </div>
        ) : (
          <div style={{display:"flex", flexWrap:"wrap", gap:6, maxHeight:120, overflowY:"auto"}}>
            {repoOptions.map(opt => {
              const on = attachRepos.includes(opt.name);
              return (
                <label key={opt.name}
                       style={{display:"inline-flex", alignItems:"center", gap:5,
                               fontSize:12, padding:"3px 8px", cursor:"pointer",
                               border:"1px solid " + (on ? "var(--purple)" : "var(--rule-strong)"),
                               background: on ? "rgba(79,38,131,0.10)" : "transparent",
                               color: on ? "var(--purple)" : "var(--ink-2)", borderRadius:2}}>
                  <input type="checkbox" checked={on} onChange={() => toggleRepo(opt.name)} />
                  <span className="mono">{opt.name}</span>
                  <span className="muted" style={{fontSize:10}}>
                    ({(opt.hosts || []).join(", ") || "?"})
                  </span>
                </label>
              );
            })}
          </div>
        )}

        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase"}}>git provider</label>
        {(() => {
          // Phase 4: dropdown of the lab's declared providers (Phase 2).
          // Falls back to the github/local-bare radio shape when no
          // providers are declared — keeps pre-refactor labs working.
          const labProviders = (window.DATA.lab_settings || {}).git_providers || [];
          if (labProviders.length > 0) {
            return (
              <>
                <select value={repoKind}
                        onChange={(e) => setRepoKind(e.target.value)}
                        style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2,
                                fontFamily:"var(--mono)", width:"100%", boxSizing:"border-box", fontSize:12, marginTop:2}}>
                  {labProviders.map(p => (
                    <option key={p.id} value={p.id}>
                      {p.id} — {p.kind}{p.target ? " · " + p.target : ""}{p.label ? "  (" + p.label + ")" : ""}
                    </option>
                  ))}
                </select>
                <div className="muted" style={{fontSize:11, marginTop:3}}>
                  Picks from the lab's declared providers. Edit the list in
                  <strong> ⚙ lab → Git providers</strong>.
                </div>
              </>
            );
          }
          return (
            <div className="row" style={{gap:14, alignItems:"flex-start", marginTop:2}}>
              <label style={{display:"flex", alignItems:"center", gap:6, cursor:"pointer", fontSize:12}}>
                <input type="radio" name="repo_kind" value="github"
                       checked={repoKind === "github"}
                       onChange={() => setRepoKind("github")} />
                GitHub <span className="mono muted" style={{fontSize:11}}>(default — pushes to github.com/{ls.github_org || "hallettmiket"})</span>
              </label>
              <label style={{display:"flex", alignItems:"center", gap:6, cursor:"pointer", fontSize:12}}>
                <input type="radio" name="repo_kind" value="local"
                       checked={repoKind === "local"}
                       onChange={() => setRepoKind("local")} />
                Local bare repo <span className="mono muted" style={{fontSize:11}}>(stays on the lab VM)</span>
              </label>
            </div>
          );
        })()}
        {repoKind === "local" && (
          <div style={{marginTop:4}}>
            <input value={localRepoRoot}
                   onChange={e => setLocalRepoRoot(e.target.value)}
                   placeholder="/data/lab_vm/git_repos"
                   style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2, fontFamily:"var(--mono)", width:"100%", boxSizing:"border-box", fontSize:12}}/>
            <div className="muted" style={{fontSize:11, marginTop:3}}>
              The bare repo will be created at <code>{(localRepoRoot.replace(/\/$/, "") || "<path>")}/{name.trim() || "<project>"}.git</code> —
              required for clinical or industrial data that must not leave the lab VM.
              No GitHub remote is created.
            </div>
          </div>
        )}

        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase"}}>justification</label>
        <textarea value={justification} onChange={e => setJustification(e.target.value)}
                  rows={3} placeholder="Brief description of the project, scope, expected duration."
                  style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2, fontFamily:"var(--serif)", fontSize:14}}/>
        {err && <div style={{color:"var(--red)", fontSize:12}}>{err}</div>}
        <div className="row" style={{justifyContent:"flex-end", gap:6, marginTop:6}}>
          <button type="button" className="btn sm ghost" onClick={onClose}>cancel</button>
          <button type="submit" className="btn sm primary" disabled={busy}>
            {busy ? "…" : "submit for approval"}
          </button>
        </div>
      </form>
    </div>
  );
}

function RequestActionRow({ req, isPI }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr]   = useState(null);
  // Approve runs slack channel create + gh repo create + git push +
  // collaborator sync. The server returns one Probe per step; we
  // surface them inline so the PI sees what actually happened.
  const [probes, setProbes] = useState(null);
  const [overall, setOverall] = useState(null);
  const refresh = async () => {
    if (typeof window.__murmurentFetchData === "function") {
      try { await window.__murmurentFetchData(window.DATA.persona); } catch (_) {}
    }
  };
  const onApprove = async () => {
    setBusy(true); setErr(null); setProbes(null); setOverall(null);
    try {
      const out = await postRequestAction(req.id, "approve");
      if (out.probes) { setProbes(out.probes); setOverall(out.overall || "ok"); }
      await refresh();
    }
    catch (ex) { setErr(String(ex.message || ex)); }
    finally { setBusy(false); }
  };
  const onDecline = async () => {
    const reason = window.prompt("Decline reason:");
    if (!reason || !reason.trim()) return;
    setBusy(true); setErr(null);
    try { await postRequestAction(req.id, "decline", { reason: reason.trim() }); await refresh(); }
    catch (ex) { setErr(String(ex.message || ex)); }
    finally { setBusy(false); }
  };
  const isCreate = req.kind === "project-create";
  return (
    <div style={{padding:"9px 14px", borderBottom:"1px solid var(--rule)"}}>
      <div style={{display:"flex", justifyContent:"space-between", alignItems:"baseline", gap:8}}>
        <div>
          <Pill tone={isCreate ? "tiger" : "purple"}>
            {isCreate ? "new project" : "join"}
          </Pill>
          <span style={{fontWeight:500, marginLeft:8}}>{req.requester}</span>
          <span className="muted" style={{marginLeft:6}}>→</span>
          <span className="mono" style={{marginLeft:6, fontSize:12}}>{req.project}</span>
        </div>
        <span className="mono muted" style={{fontSize:10}}>{req.created_at || ""}</span>
      </div>
      {isCreate && req.proposed_members && (
        <div className="mono muted" style={{fontSize:11, marginTop:4}}>
          members: {req.proposed_members.join(", ")} · sens: {req.proposed_sensitivity || "standard"}
        </div>
      )}
      {isCreate && (req.machines && req.machines.length > 0) && (
        <div className="mono muted" style={{fontSize:11, marginTop:2}}>
          machines: {req.machines.join(", ")}
          {req.attach_repos && req.attach_repos.length > 0
            ? " · repos: " + req.attach_repos.join(", ")
            : ""}
        </div>
      )}
      {req.justification && (
        <div className="muted" style={{fontSize:12, marginTop:4, lineHeight:1.45}}>
          {req.justification}
        </div>
      )}
      {isPI ? (
        <div className="row" style={{marginTop:6, justifyContent:"flex-end", gap:6}}>
          <button className="btn sm primary" disabled={busy} onClick={onApprove}>
            {busy ? "…" : "approve"}
          </button>
          <button className="btn sm" disabled={busy} onClick={onDecline}>
            decline
          </button>
        </div>
      ) : (
        <div className="row" style={{marginTop:6, justifyContent:"flex-end"}}>
          <Pill tone="amber">{req.state}</Pill>
        </div>
      )}
      {err && (
        <div style={{fontSize:11, color:"var(--red)", marginTop:4, textAlign:"right"}}>
          {err}
        </div>
      )}
      {probes && probes.length > 0 && (
        <div style={{
          marginTop:8, padding:"8px 10px",
          background:"var(--paper-2)", border:"1px solid var(--rule)", borderRadius:2,
        }}>
          <div style={{fontSize:11, marginBottom:4, color:"var(--muted)"}}>
            provisioning: <strong style={{
              color: overall === "ok" ? "var(--green)" :
                     overall === "warn" ? "var(--tiger)" : "var(--red)",
            }}>{overall}</strong>
          </div>
          {probes.map((p, i) => (
            <div key={p.name + i} style={{
              fontSize:11.5, fontFamily:"var(--mono)",
              display:"flex", gap:6, alignItems:"baseline", marginTop:1,
            }}>
              <span style={{
                color: p.status === "ok" ? "var(--green)" :
                       p.status === "warn" ? "var(--tiger)" : "var(--red)",
                width:12,
              }}>
                {p.status === "ok" ? "✓" : p.status === "warn" ? "!" : "✗"}
              </span>
              <span style={{width:140, color:"var(--muted)"}}>{p.name}</span>
              <span style={{flex:1, color:"var(--ink)"}}>{p.detail}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* (11) The standalone "Requests · project join" window is gone: project
   membership is now lead-controlled (certificates issued from the project's
   Members section), not request-to-join. Project-CREATE approvals still live
   in the ProjectsPanel queue (RequestActionRow). */

/* ───────── SEA catalog (we offer) ───────── */
async function postCatalogUpsert(body) {
  const params = new URLSearchParams(window.location.search);
  const userParam = params.get("user");
  const url = "/api/sea_catalog" + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}
async function postCatalogAction(slug, action) {
  const params = new URLSearchParams(window.location.search);
  const userParam = params.get("user");
  const url = "/api/sea_catalog/" + encodeURIComponent(slug) + "/" + encodeURIComponent(action)
    + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
  const res = await fetch(url, { method: "POST", headers: { Accept: "application/json" } });
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

function CatalogEntryForm({ entry, onClose }) {
  const [slug, setSlug] = useState(entry?.slug || "");
  const [title, setTitle] = useState(entry?.title || "");
  const [kind, setKind] = useState(entry?.kind || "experiment");
  const [contact, setContact] = useState(entry?.contact || "");
  const [turnaround, setTurnaround] = useState(entry?.turnaround_days || "");
  const [description, setDescription] = useState(entry?.description || "");
  const [prereqs, setPrereqs] = useState((entry?.prerequisites || []).join(", "));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const submit = async (e) => {
    e.preventDefault();
    if (!slug.trim() || !title.trim() || !contact.trim()) {
      setErr("slug, title, and contact are required"); return;
    }
    setBusy(true); setErr(null);
    try {
      await postCatalogUpsert({
        slug: slug.trim(),
        title: title.trim(),
        kind,
        contact: contact.trim(),
        description: description.trim(),
        turnaround_days: turnaround ? parseInt(turnaround, 10) : null,
        prerequisites: prereqs.split(",").map(s => s.trim()).filter(Boolean),
        accepting: entry?.accepting !== false,
      });
      if (typeof window.__murmurentFetchData === "function") {
        await window.__murmurentFetchData(window.DATA.persona);
      }
      onClose();
    } catch (ex) { setErr(String(ex.message || ex)); }
    finally { setBusy(false); }
  };
  return (
    <div onClick={onClose} style={{
      position:"fixed", inset:0, background:"rgba(32,20,54,0.55)",
      display:"flex", alignItems:"center", justifyContent:"center", zIndex:100,
    }}>
      <form onSubmit={submit} onClick={e => e.stopPropagation()} style={{
        background:"var(--card)", border:"1px solid var(--rule-strong)",
        borderRadius:2, padding:18, width:"min(560px, 92vw)",
        display:"flex", flexDirection:"column", gap:8,
      }}>
        <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:18, color:"var(--purple-deep)"}}>
          {entry ? "Edit catalog entry" : "Add catalog entry"}
        </h2>
        <p className="muted" style={{fontSize:12, margin:0}}>
          What you publish here is what other groups discover via the sea_catalog MCP.
        </p>
        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase", marginTop:6}}>slug (lower_snake_case)</label>
        <input value={slug} onChange={e => setSlug(e.target.value)} disabled={!!entry}
               placeholder="e.g. bulk_rnaseq_alignment"
               style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2, fontFamily:"var(--mono)"}}/>
        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase"}}>title</label>
        <input value={title} onChange={e => setTitle(e.target.value)}
               placeholder="DCIS bulk RNA-seq alignment"
               style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2}}/>
        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase"}}>kind</label>
        <select value={kind} onChange={e => setKind(e.target.value)}
                style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2, fontFamily:"var(--mono)"}}>
          <option value="skill">skill</option>
          <option value="experiment">experiment</option>
          <option value="analysis">analysis</option>
        </select>
        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase"}}>contact (member who owns it)</label>
        <input value={contact} onChange={e => setContact(e.target.value)} placeholder="@allie"
               style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2, fontFamily:"var(--mono)"}}/>
        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase"}}>turnaround (days, optional)</label>
        <input value={turnaround} onChange={e => setTurnaround(e.target.value)} placeholder="7"
               type="number" min="0" style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2, fontFamily:"var(--mono)", width:120}}/>
        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase"}}>prerequisites (comma-separated)</label>
        <input value={prereqs} onChange={e => setPrereqs(e.target.value)} placeholder="GRCh38 reference, fastq files"
               style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2}}/>
        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase"}}>description</label>
        <textarea value={description} onChange={e => setDescription(e.target.value)}
                  rows={3} placeholder="What we deliver, in one paragraph."
                  style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2, fontFamily:"var(--serif)", fontSize:14}}/>
        {err && <div style={{color:"var(--red)", fontSize:12}}>{err}</div>}
        <div className="row" style={{justifyContent:"flex-end", gap:6, marginTop:6}}>
          <button type="button" className="btn sm ghost" onClick={onClose}>cancel</button>
          <button type="submit" className="btn sm primary" disabled={busy}>
            {busy ? "…" : (entry ? "save" : "publish")}
          </button>
        </div>
      </form>
    </div>
  );
}

async function postCommonSeaSubmit(body) {
  const params = new URLSearchParams(window.location.search);
  const userParam = params.get("user");
  const url = "/api/registrar/common_seas"
    + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
  const res = await fetch(url, {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}
async function postCommonSeaArchive(slug) {
  const params = new URLSearchParams(window.location.search);
  const userParam = params.get("user");
  const url = "/api/registrar/common_seas/" + encodeURIComponent(slug)
    + "/archive"
    + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
  const res = await fetch(url, { method: "POST", credentials: "same-origin" });
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

function SeaCatalogPanel({ entries, span="c-12" }) {
  const persona = window.DATA.persona || "member";
  const isPI = persona === "pi";
  const [editing, setEditing] = useState(null);  // null | {} (new) | entry (edit)
  const [busy, setBusy] = useState(null);
  const [commonSeas, setCommonSeas] = useState(null);
  const [copied, setCopied] = useState(null);
  const list = entries || [];

  const refresh = async () => {
    if (typeof window.__murmurentFetchData === "function") {
      try { await window.__murmurentFetchData(window.DATA.persona); } catch (_) {}
    }
  };
  const reloadCommonSeas = async () => {
    try {
      const res = await fetch("/api/common_seas", { credentials: "same-origin" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      setCommonSeas((await res.json()).seas || []);
    } catch (_) { setCommonSeas([]); }
  };
  useEffect(() => { reloadCommonSeas(); }, []);

  const onToggle = async (entry) => {
    setBusy(entry.slug);
    try { await postCatalogAction(entry.slug, entry.accepting ? "disable" : "enable"); await refresh(); }
    catch (ex) { alert(ex.message || ex); }
    finally { setBusy(null); }
  };
  const onDelete = async (entry) => {
    if (!window.confirm(`Delete catalog entry "${entry.slug}"?`)) return;
    setBusy(entry.slug);
    try { await postCatalogAction(entry.slug, "delete"); await refresh(); }
    catch (ex) { alert(ex.message || ex); }
    finally { setBusy(null); }
  };

  const onSubmitCommon = async () => {
    const slug = window.prompt("Slug (lowercase, underscores, e.g. 'qc_drift_routine'):");
    if (!slug) return;
    const name = window.prompt("Display name:");
    if (!name) return;
    const k = window.prompt("Kind (service | skill | routine | mcp | dataset):", "skill");
    if (!k) return;
    const description = window.prompt("One-line description:", "") || "";
    const install = window.prompt("Copy-paste install command:", "") || "";
    const url = window.prompt("Canonical URL (git repo or docs):", "") || "";
    const tagsRaw = window.prompt("Tags (comma-separated, optional):", "") || "";
    const tags = tagsRaw.split(",").map(s => s.trim()).filter(Boolean);
    try {
      await postCommonSeaSubmit({ slug, name, kind: k, description, install, url, tags });
      reloadCommonSeas();
    } catch (ex) { alert("Submit failed: " + (ex.message || ex)); }
  };
  const onArchiveCommon = async (sea) => {
    if (!window.confirm(`Archive common SEA "${sea.slug}"?`)) return;
    try { await postCommonSeaArchive(sea.slug); reloadCommonSeas(); }
    catch (ex) { alert("Archive failed: " + (ex.message || ex)); }
  };
  const onCopy = async (text, key) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key); setTimeout(() => setCopied(null), 1500);
    } catch (_) {}
  };

  const commonList = commonSeas || [];

  return (
    <div className={"panel "+span}>
      <header>
        <h2>SEAs we offer</h2>
        <div className="row" style={{gap:8}}>
          <span className="meta">
            {list.length} per-lab · {commonList.length} common
          </span>
        </div>
      </header>
      {editing !== null && (
        <CatalogEntryForm
          entry={Object.keys(editing).length === 0 ? null : editing}
          onClose={() => setEditing(null)}
        />
      )}

      {/* Per-lab SEAs (existing concept: lab-to-lab agreements) */}
      <div style={{padding:"10px 14px 4px",
                    display:"flex", justifyContent:"space-between",
                    alignItems:"baseline",
                    borderBottom:"1px solid #eee"}}>
        <h3 style={{margin:0, fontSize:14}}>Per-lab agreements</h3>
        {isPI && (
          <button className="btn sm primary" onClick={() => setEditing({})}>
            ＋ add per-lab SEA
          </button>
        )}
      </div>
      <div style={{padding:0}}>
        {list.length === 0 ? (
          <div className="muted" style={{padding:"14px", fontSize:13}}>
            No per-lab SEAs yet.{" "}
            {isPI && <span>Click <code>＋ add per-lab SEA</code> for lab-to-lab service agreements.</span>}
          </div>
        ) : (
        <table className="dt">
          <thead><tr>
            <th>slug</th><th>title</th><th style={{width:90}}>kind</th>
            <th style={{width:90}}>contact</th><th style={{width:80}}>turnaround</th>
            <th style={{width:80}}>state</th>
            {isPI && <th style={{width:200}}></th>}
          </tr></thead>
          <tbody>
            {list.map(e => (
              <tr key={e.slug} style={{opacity: e.accepting ? 1 : 0.55}}>
                <td className="mono" style={{fontSize:12}}>{e.slug}</td>
                <td>
                  <div style={{fontWeight:500}}>{e.title}</div>
                  {e.description && (
                    <div className="muted" style={{fontSize:11, marginTop:2}}>
                      {e.description.length > 80 ? e.description.slice(0, 80) + "…" : e.description}
                    </div>
                  )}
                </td>
                <td className="mono muted" style={{fontSize:12}}>{e.kind}</td>
                <td className="mono" style={{fontSize:12}}>{e.contact}</td>
                <td className="num">{e.turnaround_days ? `${e.turnaround_days}d` : "—"}</td>
                <td>
                  <Pill tone={e.accepting ? "green" : "outline"}>
                    {e.accepting ? "accepting" : "paused"}
                  </Pill>
                </td>
                {isPI && (
                  <td>
                    <div className="row" style={{justifyContent:"flex-end", gap:4}}>
                      <button className="btn sm" disabled={busy===e.slug}
                              onClick={() => setEditing(e)}>edit</button>
                      <button className="btn sm" disabled={busy===e.slug}
                              onClick={() => onToggle(e)}>
                        {e.accepting ? "pause" : "resume"}
                      </button>
                      <button className="btn sm danger" disabled={busy===e.slug}
                              onClick={() => onDelete(e)}>delete</button>
                    </div>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        )}
      </div>

      {/* Centre-wide common SEAs (skills / routines / MCPs / datasets
          / services any lab can clone) */}
      <div style={{padding:"10px 14px 4px",
                    display:"flex", justifyContent:"space-between",
                    alignItems:"baseline",
                    borderTop:"1px solid #ddd",
                    borderBottom:"1px solid #eee",
                    marginTop:8}}>
        <h3 style={{margin:0, fontSize:14}}>Common SEAs (centre-wide)</h3>
        {isPI && (
          <button className="btn sm primary" onClick={onSubmitCommon}>
            ＋ submit common SEA
          </button>
        )}
      </div>
      <div style={{padding:0}}>
        {commonList.length === 0 ? (
          <div className="muted" style={{padding:"14px", fontSize:13}}>
            No common SEAs registered yet.{" "}
            {isPI && <span>Click <code>＋ submit common SEA</code> to publish a skill / routine / MCP / dataset for the whole centre.</span>}
          </div>
        ) : (
        <table className="dt">
          <thead><tr>
            <th>name</th>
            <th style={{width:90}}>kind</th>
            <th style={{width:100}}>owner</th>
            <th>install</th>
            {isPI && <th style={{width:90}}></th>}
          </tr></thead>
          <tbody>
            {commonList.map(s => (
              <tr key={s.slug}>
                <td>
                  <div style={{fontWeight:500}}>
                    {s.name}
                    {s.url && (
                      <a href={s.url} target="_blank" rel="noopener"
                         style={{marginLeft:6, fontSize:11}}>↗</a>
                    )}
                  </div>
                  {s.description && (
                    <div className="muted" style={{fontSize:11}}>{s.description}</div>
                  )}
                  {(s.tags || []).length > 0 && (
                    <div style={{marginTop:3}}>
                      {s.tags.map(x => (
                        <span key={x} className="pill" style={{fontSize:10, marginRight:3}}>{x}</span>
                      ))}
                    </div>
                  )}
                </td>
                <td className="mono muted" style={{fontSize:11}}>{s.kind}</td>
                <td className="mono" style={{fontSize:11}}>{s.owner_lab}</td>
                <td>
                  {s.install ? (
                    <div style={{display:"flex", gap:4, alignItems:"center"}}>
                      <code style={{flex:1, fontSize:11,
                                     padding:"2px 4px",
                                     background:"#f5f5f5",
                                     borderRadius:2,
                                     overflow:"hidden",
                                     textOverflow:"ellipsis",
                                     whiteSpace:"nowrap"}}>{s.install}</code>
                      <button className="btn sm" onClick={() => onCopy(s.install, s.slug)}>
                        {copied === s.slug ? "copied!" : "copy"}
                      </button>
                    </div>
                  ) : (
                    <span className="muted" style={{fontSize:11}}>see source ↗</span>
                  )}
                </td>
                {isPI && (
                  <td>
                    <div className="row" style={{justifyContent:"flex-end", gap:4}}>
                      <button className="btn sm danger" onClick={() => onArchiveCommon(s)}>
                        archive
                      </button>
                    </div>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        )}
      </div>
    </div>
  );
}

/* ───────── Core services panel (Phase 3e of the cores rollout) ─────────
   Lists every active service across every core (cross-core browse),
   with a per-service Book button that opens a modal slot-picker. The
   Book button is disabled (and shows the training-required reason)
   when can_book.ok is false for the viewing member. Below the catalog,
   "My bookings" shows the viewer's own live requests with cancel +
   reschedule actions. Hidden when no cores are registered. */

// Inline modal styles — the hifi HTML doesn't define .modal-backdrop /
// .modal classes (only the registrar.html does), so we hand-roll them
// to guarantee the overlay is visible.
const MODAL_BACKDROP_STYLE = {
  position: "fixed", inset: 0,
  background: "rgba(0,0,0,0.45)",
  display: "flex", alignItems: "center", justifyContent: "center",
  zIndex: 100, padding: 20,
};
const MODAL_PANEL_STYLE = {
  background: "white", borderRadius: 4,
  width: "100%", maxHeight: "90vh", overflowY: "auto",
  boxShadow: "0 8px 32px rgba(0,0,0,0.2)",
};

async function fetchCoresServices(member) {
  const url = "/api/cores/services" + (member ? "?member=" + encodeURIComponent(member) : "");
  const res = await fetch(url, { credentials: "same-origin" });
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}
async function fetchMyRequests(member, includeTerminal=false) {
  if (!member) return { requests: [] };
  const url = "/api/member/" + encodeURIComponent(member) + "/requests"
    + (includeTerminal ? "?include_terminal=true" : "");
  const res = await fetch(url, { credentials: "same-origin" });
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}
async function requestTraining(core, trainingSlug, note) {
  const params = new URLSearchParams(window.location.search);
  const userParam = params.get("user");
  const url = "/api/core/" + encodeURIComponent(core)
    + "/training/" + encodeURIComponent(trainingSlug) + "/request"
    + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
  const res = await fetch(url, {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note: note || "" }),
  });
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

async function postBookSlot(core, slug, body) {
  const params = new URLSearchParams(window.location.search);
  const userParam = params.get("user");
  const url = "/api/core/" + encodeURIComponent(core)
    + "/services/" + encodeURIComponent(slug) + "/book"
    + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
  const res = await fetch(url, {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}
async function fetchJobFiles(core, jobId) {
  const params = new URLSearchParams(window.location.search);
  const userParam = params.get("user");
  const url = "/api/core/" + encodeURIComponent(core)
    + "/jobs/" + encodeURIComponent(jobId) + "/files"
    + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
  const res = await fetch(url, { credentials: "same-origin" });
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}
function jobFileUrl(core, jobId, relpath) {
  const params = new URLSearchParams(window.location.search);
  const userParam = params.get("user");
  return "/api/core/" + encodeURIComponent(core)
    + "/jobs/" + encodeURIComponent(jobId)
    + "/files/" + relpath.split("/").map(encodeURIComponent).join("/")
    + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
}
function jobBundleUrl(core, jobId) {
  const params = new URLSearchParams(window.location.search);
  const userParam = params.get("user");
  return "/api/core/" + encodeURIComponent(core)
    + "/jobs/" + encodeURIComponent(jobId) + "/bundle"
    + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
}

function JobFilesModal({ core, jobId, onClose }) {
  const [data, setData] = useState(null);
  const [err, setErr]   = useState(null);

  useEffect(() => {
    (async () => {
      try { setData(await fetchJobFiles(core, jobId)); }
      catch (ex) { setErr(String(ex.message || ex)); }
    })();
  }, [core, jobId]);

  return (
    <div onClick={onClose} style={MODAL_BACKDROP_STYLE}>
      <div onClick={(e) => e.stopPropagation()}
           style={{...MODAL_PANEL_STYLE, maxWidth:640}}>
        <header style={{padding:"11px 14px 9px",
                         borderBottom:"1px solid var(--rule)"}}>
          <h3 style={{margin:0, fontSize:16}}>Files for {jobId}</h3>
        </header>
        <div style={{padding:14}}>
          {err && <div className="error">{err}</div>}
          {!err && data === null && <div className="muted">Loading…</div>}
          {data && data.files && data.files.length === 0 && (
            <div className="muted">
              No files yet. The core staff hasn't uploaded any deliverables.
            </div>
          )}
          {data && data.files && data.files.length > 0 && (
            <table className="dt">
              <thead><tr><th>relpath</th><th>size</th><th></th></tr></thead>
              <tbody>
                {data.files.map(f => (
                  <tr key={f.relpath}>
                    <td className="mono" style={{fontSize:12}}>{f.relpath}</td>
                    <td className="num">{f.size_bytes.toLocaleString()} B</td>
                    <td>
                      <a className="btn sm"
                         href={jobFileUrl(core, jobId, f.relpath)}
                         download>download</a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="row" style={{justifyContent:"space-between", marginTop:10}}>
            {data && data.files && data.files.length > 0 ? (
              <a className="btn sm" href={jobBundleUrl(core, jobId)} download>
                download all (tar.gz)
              </a>
            ) : <span />}
            <button className="btn sm" onClick={onClose}>Close</button>
          </div>
        </div>
      </div>
    </div>
  );
}

async function postRequestLifecycle(core, requestId, action, body={}) {
  const params = new URLSearchParams(window.location.search);
  const userParam = params.get("user");
  const url = "/api/core/" + encodeURIComponent(core)
    + "/requests/" + encodeURIComponent(requestId) + "/" + action
    + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
  const res = await fetch(url, {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

// Pads minutes to two digits for the local-timezone offset format
// (e.g. -240 → "-04:00").
function _tzOffsetIso() {
  const m = -new Date().getTimezoneOffset();
  const sign = m >= 0 ? "+" : "-";
  const abs = Math.abs(m);
  return sign + String(Math.floor(abs/60)).padStart(2,"0")
              + ":" + String(abs%60).padStart(2,"0");
}
// `<input type="datetime-local">` gives "YYYY-MM-DDTHH:mm" with no
// timezone; the backend needs ISO8601 with offset. Append local offset.
function _toIsoWithLocalTz(localDt) {
  if (!localDt) return "";
  return localDt + ":00" + _tzOffsetIso();
}

function BookSlotModal({ service, member, onClose, onBooked }) {
  const tiers = Object.keys((service.fee && service.fee.tiers) || {});
  // Default start = next round hour from now, end = start + service.duration.
  const _defaultStart = () => {
    const d = new Date();
    d.setMinutes(0, 0, 0);
    d.setHours(d.getHours() + 1);
    // datetime-local wants "YYYY-MM-DDTHH:mm" in *local* time.
    const pad = n => String(n).padStart(2,"0");
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`
         + `T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };
  const _addMin = (localDt, mins) => {
    const [date, time] = localDt.split("T");
    const [y, mo, d] = date.split("-").map(Number);
    const [hh, mm] = time.split(":").map(Number);
    const dt = new Date(y, mo-1, d, hh, mm);
    dt.setMinutes(dt.getMinutes() + mins);
    const pad = n => String(n).padStart(2,"0");
    return `${dt.getFullYear()}-${pad(dt.getMonth()+1)}-${pad(dt.getDate())}`
         + `T${pad(dt.getHours())}:${pad(dt.getMinutes())}`;
  };
  const initialStart = _defaultStart();
  const initialEnd = _addMin(initialStart, service.duration_default_min || 60);

  const [start, setStart] = useState(initialStart);
  const [end, setEnd]     = useState(initialEnd);
  const [tier, setTier]   = useState(tiers[0] || "");
  const [notes, setNotes] = useState("");
  const [busy, setBusy]   = useState(false);
  const [err, setErr]     = useState(null);

  // When the user changes start, snap end to start + default duration
  // (only if they haven't manually edited end since the last start change).
  const handleStartChange = (v) => {
    const newEnd = _addMin(v, service.duration_default_min || 60);
    setStart(v);
    setEnd(newEnd);
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!start || !end) { setErr("Pick a start and end time."); return; }
    if (end <= start) { setErr("End must be after start."); return; }
    setBusy(true); setErr(null);
    try {
      const body = {
        slot: { start: _toIsoWithLocalTz(start), end: _toIsoWithLocalTz(end) },
        notes: notes.trim(),
      };
      if (tier) body.tier = tier;
      const resp = await postBookSlot(service.core, service.slug, body);
      onBooked && onBooked(resp);
      onClose();
    } catch (ex) {
      setErr(String(ex.message || ex));
    } finally { setBusy(false); }
  };

  return (
    <div onClick={onClose} style={MODAL_BACKDROP_STYLE}>
      <div onClick={(e) => e.stopPropagation()}
           style={{...MODAL_PANEL_STYLE, maxWidth:560}}>
        <header style={{padding:"11px 14px 9px",
                         borderBottom:"1px solid var(--rule)"}}>
          <h3 style={{margin:0, fontSize:16}}>Book {service.name} ({service.core})</h3>
        </header>
        <form onSubmit={submit} style={{padding:14}}>
          <div className="muted" style={{fontSize:12, marginBottom:10}}>
            Booking as <b>@{member || "?"}</b>. Times are in your local
            timezone ({_tzOffsetIso()}).
          </div>
          <label style={{display:"block", marginBottom:8}}>
            <div style={{fontSize:11, color:"#666"}}>Start</div>
            <input type="datetime-local" value={start}
                   onChange={e=>handleStartChange(e.target.value)}
                   step="900"
                   style={{width:"100%"}} required />
          </label>
          <label style={{display:"block", marginBottom:8}}>
            <div style={{fontSize:11, color:"#666"}}>End</div>
            <input type="datetime-local" value={end}
                   onChange={e=>setEnd(e.target.value)}
                   step="900"
                   style={{width:"100%"}} required />
          </label>
          {tiers.length > 0 && (
            <label style={{display:"block", marginBottom:8}}>
              <div style={{fontSize:11, color:"#666"}}>Tier</div>
              <select value={tier} onChange={e=>setTier(e.target.value)}>
                {tiers.map(t => (
                  <option key={t} value={t}>
                    {t} — ${service.fee.tiers[t]} {service.fee.unit}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label style={{display:"block", marginBottom:8}}>
            <div style={{fontSize:11, color:"#666"}}>Notes (for the core staff)</div>
            <textarea value={notes} onChange={e=>setNotes(e.target.value)}
                      rows={3} style={{width:"100%"}} />
          </label>
          {err && <div className="error" style={{marginBottom:8}}>{err}</div>}
          <div className="row" style={{justifyContent:"flex-end", gap:6}}>
            <button type="button" className="btn sm" onClick={onClose}
                    disabled={busy}>Cancel</button>
            <button type="submit" className="btn sm primary" disabled={busy}>
              {busy ? "Booking…" : "Book slot"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function CoreServicesPanel({ span="c-12" }) {
  const params = new URLSearchParams(window.location.search);
  const member = (params.get("user") || (window.DATA.identity && window.DATA.identity.handle) || "").replace(/^@/, "");
  const [services, setServices] = useState(null);
  const [myReqs, setMyReqs]     = useState([]);
  const [showTerm, setShowTerm] = useState(false);
  const [booking, setBooking]   = useState(null);
  const [busyReq, setBusyReq]   = useState(null);
  const [filesFor, setFilesFor] = useState(null);  // { core, jobId } or null
  const [err, setErr]           = useState(null);

  const reload = async () => {
    setErr(null);
    try {
      const [a, b] = await Promise.all([
        fetchCoresServices(member),
        fetchMyRequests(member, showTerm),
      ]);
      setServices(a.services || []);
      setMyReqs(b.requests || []);
    } catch (ex) { setErr(String(ex.message || ex)); }
  };
  useEffect(() => { reload(); /* eslint-disable-line */ }, [showTerm]);

  if (services === null) {
    return (
      <div className={"panel " + span}>
        <header><h2>Core services</h2></header>
        <div className="body muted" style={{padding:14}}>Loading…</div>
      </div>
    );
  }
  if (services.length === 0) return null;  // no cores → hide panel

  const byCore = {};
  for (const s of services) {
    (byCore[s.core] = byCore[s.core] || []).push(s);
  }

  const onCancel = async (r) => {
    if (!window.confirm(`Cancel request ${r.request_id}?`)) return;
    setBusyReq(r.request_id);
    try { await postRequestLifecycle(r.core, r.request_id, "cancel"); await reload(); }
    catch (ex) { alert(ex.message || ex); }
    finally { setBusyReq(null); }
  };
  const onReschedule = async (r) => {
    const newStart = window.prompt("New start (ISO8601 + tz)", r.slot.start);
    if (!newStart) return;
    const newEnd = window.prompt("New end (ISO8601 + tz)", r.slot.end);
    if (!newEnd) return;
    setBusyReq(r.request_id);
    try {
      await postRequestLifecycle(r.core, r.request_id, "reschedule",
        { slot: { start: newStart, end: newEnd } });
      await reload();
    } catch (ex) { alert(ex.message || ex); }
    finally { setBusyReq(null); }
  };

  return (
    <div className={"panel " + span}>
      <header>
        <h2>Core services</h2>
        <span className="meta">
          {services.length} active service{services.length === 1 ? "" : "s"} ·
          {" "}{Object.keys(byCore).length} core{Object.keys(byCore).length === 1 ? "" : "s"}
        </span>
      </header>
      <div className="body" style={{padding:0}}>
        {Object.keys(byCore).sort().map(coreName => (
          <div key={coreName} style={{padding:"8px 14px", borderTop:"1px solid #eee"}}>
            <div style={{fontWeight:600, marginBottom:6}}>
              {byCore[coreName][0].core_display_name || coreName}
              <span className="mono muted" style={{marginLeft:8, fontSize:11}}>
                ({coreName})
              </span>
            </div>
            <table className="dt">
              <thead><tr>
                <th>service</th>
                <th style={{width:130}}>capability</th>
                <th style={{width:80}}>fee</th>
                <th style={{width:140}}>training</th>
                <th style={{width:110}}></th>
              </tr></thead>
              <tbody>
                {byCore[coreName].map(s => {
                  const tier0 = Object.keys((s.fee && s.fee.tiers) || {})[0];
                  const price = tier0 ? `$${s.fee.tiers[tier0]} ${s.fee.unit}` : "—";
                  const canBook = !s.can_book || s.can_book.ok;
                  return (
                    <tr key={s.core+"::"+s.slug}>
                      <td>
                        <div style={{fontWeight:500}}>{s.name}</div>
                        {s.description && (
                          <div className="muted" style={{fontSize:11}}>{s.description}</div>
                        )}
                      </td>
                      <td className="mono muted" style={{fontSize:11}}>{s.capability || "—"}</td>
                      <td className="mono" style={{fontSize:12}}>{price}</td>
                      <td>
                        {s.training_required
                          ? <Pill tone={canBook ? "green" : "warn"}>
                              {s.training_required}
                            </Pill>
                          : <span className="muted" style={{fontSize:11}}>none</span>}
                      </td>
                      <td>
                        {canBook ? (
                          <button className="btn sm primary"
                                  onClick={() => setBooking(s)}>
                            Book
                          </button>
                        ) : (
                          <button className="btn sm"
                                  title={(s.can_book && s.can_book.reason) || ""}
                                  onClick={async () => {
                                    const note = window.prompt(
                                      `Request training on ${s.training_required} from the trainer(s) for ${s.core}.\n\nOptional note (e.g. "afternoons work best"):`,
                                      "",
                                    );
                                    if (note === null) return;
                                    try {
                                      await requestTraining(s.core, s.training_required, note);
                                      alert(`Request posted to Slack for ${s.training_required}.\nThe trainer will reach out to schedule a session.`);
                                    } catch (ex) {
                                      alert("Request failed: " + (ex.message || ex));
                                    }
                                  }}
                                  style={{background:"#fff5d6", borderColor:"#d4a017",
                                          color:"#6b4d00"}}>
                            Request training
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ))}
      </div>

      {/* My bookings — plain div instead of <header> so the panel
          CSS doesn't reposition it on top of the catalog above. */}
      <div style={{borderTop:"1px solid #eee",
                    padding:"10px 14px 4px",
                    display:"flex", justifyContent:"space-between",
                    alignItems:"baseline"}}>
        <h3 style={{margin:0, fontSize:14}}>My bookings</h3>
        <label style={{fontSize:11}}>
          <input type="checkbox" checked={showTerm}
                 onChange={e=>setShowTerm(e.target.checked)} />
          {" "}show cancelled / completed
        </label>
      </div>
      <div style={{padding:0}}>
        {myReqs.length === 0 && (
          <div className="muted" style={{padding:14, fontSize:13}}>
            No bookings yet.
          </div>
        )}
        {myReqs.length > 0 && (
          <table className="dt">
            <thead><tr>
              <th style={{width:90}}>core</th>
              <th style={{width:100}}>service</th>
              <th style={{width:170}}>start</th>
              <th style={{width:90}}>state</th>
              <th style={{width:80}}>fee</th>
              <th></th>
            </tr></thead>
            <tbody>
              {myReqs.map(r => {
                const terminal = r.state === "completed" || r.state === "cancelled";
                return (
                  <tr key={r.core+"::"+r.request_id}
                      style={{opacity: terminal ? 0.55 : 1}}>
                    <td className="mono" style={{fontSize:11}}>{r.core}</td>
                    <td className="mono" style={{fontSize:12}}>{r.service}</td>
                    <td className="mono" style={{fontSize:11}}>{r.slot.start}</td>
                    <td>
                      <Pill tone={terminal ? "outline" :
                                  r.state === "in_progress" ? "warn" : "green"}>
                        {r.state}
                      </Pill>
                    </td>
                    <td className="num">{r.fee_at_booking.total ? "$" + r.fee_at_booking.total : "—"}</td>
                    <td>
                      <div className="row" style={{justifyContent:"flex-end", gap:4}}>
                        <button className="btn sm"
                                onClick={() => setFilesFor({ core: r.core, jobId: r.request_id })}>
                          files
                        </button>
                        {!terminal && (
                          <button className="btn sm"
                                  disabled={busyReq === r.request_id}
                                  onClick={() => onReschedule(r)}>
                            reschedule
                          </button>
                        )}
                        {!terminal && (
                          <button className="btn sm danger"
                                  disabled={busyReq === r.request_id}
                                  onClick={() => onCancel(r)}>
                            cancel
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
      {err && <div className="error" style={{padding:10}}>{err}</div>}
      {booking && (
        <BookSlotModal service={booking} member={member}
                       onClose={() => setBooking(null)}
                       onBooked={() => reload()} />
      )}
      {filesFor && (
        <JobFilesModal core={filesFor.core} jobId={filesFor.jobId}
                       onClose={() => setFilesFor(null)} />
      )}
    </div>
  );
}

/* ───────── PI-only lab core-charges summary (Phase 4d of cores rollout) ─────────
   Shows how much THIS lab owes each core this month. Hidden on the
   member dashboard and when no cores have billed the lab yet. Read-only;
   the actual invoices are written by the core leader via core.html. */

function LabCoreChargesPanel({ span="c-6" }) {
  const lab = (window.DATA.lab_settings && window.DATA.lab_settings.short_name)
            || (window.DATA.lab_settings && window.DATA.lab_settings.lab)
            || "";
  const [data, setData] = useState(null);
  const [err, setErr]   = useState(null);

  useEffect(() => {
    if (!lab) { setData({ cores: [], total: 0 }); return; }
    (async () => {
      try {
        const res = await fetch(`/api/lab/${encodeURIComponent(lab)}/core_charges`,
                                 { credentials: "same-origin" });
        if (!res.ok) throw new Error("HTTP " + res.status);
        setData(await res.json());
      } catch (ex) { setErr(String(ex.message || ex)); }
    })();
  }, [lab]);

  if (err) return (
    <div className={"panel " + span}>
      <header><h2>Core charges this month</h2></header>
      <div className="body error" style={{padding:14}}>{err}</div>
    </div>
  );
  if (data === null) return null;
  if (!data.cores || data.cores.length === 0) return null;   // hide cleanly

  return (
    <div className={"panel " + span}>
      <header>
        <h2>Core charges this month</h2>
        <span className="meta">
          {data.month} · {data.cores.length} core{data.cores.length === 1 ? "" : "s"}
          {data.unconfirmed > 0 && (
            <span style={{marginLeft:6}}>· {data.unconfirmed} unconfirmed</span>
          )}
        </span>
      </header>
      <div className="body" style={{padding:0}}>
        <table className="dt">
          <thead><tr>
            <th>core</th>
            <th style={{textAlign:"right"}}>lines</th>
            <th style={{textAlign:"right"}}>unconfirmed</th>
            <th style={{textAlign:"right"}}>subtotal</th>
          </tr></thead>
          <tbody>
            {data.cores.map(c => (
              <tr key={c.core}>
                <td className="mono">{c.core}</td>
                <td className="num">{c.lines}</td>
                <td className="num">{c.unconfirmed > 0 ? c.unconfirmed : "—"}</td>
                <td className="num">${c.subtotal.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot><tr style={{fontWeight:600}}>
            <td>TOTAL</td><td></td><td></td>
            <td className="num">${data.total.toFixed(2)}</td>
          </tr></tfoot>
        </table>
      </div>
    </div>
  );
}

/* ───────── Centre broadcasts (item 3 of post-smoke design) ─────────
   Tier-tailored Slack messages across the centre. PI/registrar
   composes; every member sees the audit log. Channel IDs live in
   the registrar profile so different institutions name them
   differently. */

async function postBroadcast(body) {
  const params = new URLSearchParams(window.location.search);
  const userParam = params.get("user");
  const url = "/api/broadcast"
    + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
  const res = await fetch(url, {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

function BroadcastsPanel({ span="c-12" }) {
  const persona = window.DATA.persona || "member";
  const canSend = persona === "pi" || persona === "registrar";
  const [recent, setRecent] = useState(null);
  const [audience, setAudience] = useState("everyone");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [showCompose, setShowCompose] = useState(false);

  const reload = async () => {
    try {
      const r = await fetch("/api/broadcast/recent?limit=10",
                             { credentials: "same-origin" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      setRecent((await r.json()).broadcasts || []);
    } catch (ex) { setErr(String(ex.message || ex)); }
  };
  useEffect(() => { reload(); }, []);

  const onSend = async () => {
    if (!message.trim()) { setErr("Message is empty."); return; }
    setBusy(true); setErr(null);
    try {
      await postBroadcast({ audience, message });
      setMessage("");
      setShowCompose(false);
      reload();
    } catch (ex) { setErr(String(ex.message || ex)); }
    finally { setBusy(false); }
  };

  if (recent === null) return null;

  // Format ISO ts compactly: "2026-05-26 14:23 UTC" (drop microseconds).
  const fmtTs = (iso) => {
    if (!iso) return "";
    const m = iso.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})/);
    return m ? `${m[1]} ${m[2]}:${m[3]} UTC` : iso;
  };

  return (
    <div className={"panel "+span}>
      <header>
        <h2>Centre broadcasts</h2>
        <div className="row" style={{gap:8}}>
          <span className="meta">{recent.length} recent</span>
          {canSend && (
            <button className="btn sm primary"
                    onClick={() => setShowCompose(!showCompose)}>
              {showCompose ? "cancel" : "＋ compose"}
            </button>
          )}
        </div>
      </header>
      {showCompose && canSend && (
        <div style={{padding:"10px 14px", borderBottom:"1px solid #eee",
                      background:"#fafafa"}}>
          <div className="row" style={{gap:8, marginBottom:6, alignItems:"baseline"}}>
            <label style={{fontSize:11}}>to</label>
            <select value={audience} onChange={e=>setAudience(e.target.value)}>
              <option value="everyone">everyone</option>
              <option value="pis">pis</option>
              <option value="leaders">leaders</option>
              <option value="admin">admin</option>
            </select>
          </div>
          <textarea value={message} onChange={e=>setMessage(e.target.value)}
                    placeholder="Your message …"
                    rows={3}
                    style={{width:"100%", fontSize:13, fontFamily:"inherit",
                             padding:6, border:"1px solid var(--rule)",
                             borderRadius:2}} />
          {err && <div className="error" style={{fontSize:11, marginTop:4}}>{err}</div>}
          <div className="row" style={{justifyContent:"flex-end", marginTop:6}}>
            <button className="btn sm primary" disabled={busy}
                    onClick={onSend}>
              {busy ? "Sending…" : `Send to #${audience}`}
            </button>
          </div>
        </div>
      )}
      <div className="body" style={{padding:0}}>
        {recent.length === 0 ? (
          <div className="muted" style={{padding:14, fontSize:13}}>
            No broadcasts yet.{" "}
            {canSend && <span>Click <code>＋ compose</code> to send the first one.</span>}
          </div>
        ) : (
        <table className="dt">
          <thead><tr>
            <th style={{width:140}}>when</th>
            <th style={{width:90}}>to</th>
            <th style={{width:110}}>from</th>
            <th>message</th>
          </tr></thead>
          <tbody>
            {recent.map(b => (
              <tr key={b.iso_ts + "::" + b.sender}>
                <td className="mono" style={{fontSize:11}}>{fmtTs(b.iso_ts)}</td>
                <td><Pill tone="outline">{b.audience}</Pill></td>
                <td className="mono" style={{fontSize:11}}>@{b.sender}</td>
                <td>
                  <div style={{whiteSpace:"pre-wrap", fontSize:13}}>{b.message}</div>
                  {b.message_link && (
                    <a href={b.message_link} target="_blank" rel="noopener"
                       style={{fontSize:11}}>open in Slack ↗</a>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        )}
      </div>
    </div>
  );
}

/* ───────── Centre projects (centre_cable_guy front door, item 0e) ─────────
   PI of primary_lab can declare and reconcile their projects from
   here. Members see read-only listing of every centre project they
   belong to (visibility, not editing). */

async function postCentreProject(body) {
  const params = new URLSearchParams(window.location.search);
  const userParam = params.get("user");
  const url = "/api/centre/projects"
    + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
  const res = await fetch(url, {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

async function postCentreProjectReconcile(name, body) {
  const params = new URLSearchParams(window.location.search);
  const userParam = params.get("user");
  const url = "/api/centre/projects/" + encodeURIComponent(name) + "/reconcile"
    + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
  const res = await fetch(url, {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

function CentreProjectsPanel({ span="c-12" }) {
  const persona = window.DATA.persona || "member";
  const isPI = persona === "pi" || persona === "registrar";
  const labSettings = window.DATA.lab_settings || {};
  const myLab = (labSettings.short_name || labSettings.lab || "").toLowerCase();
  const myHandle = ((window.DATA.identity && window.DATA.identity.handle) || "")
    .replace(/^@/, "").toLowerCase();
  const [rows, setRows] = useState(null);
  const [deltas, setDeltas] = useState({});       // name → Delta[]
  const [err, setErr] = useState(null);

  const reload = async () => {
    try {
      const r = await fetch("/api/centre/projects", { credentials: "same-origin" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      setRows((await r.json()).projects || []);
    } catch (ex) { setErr(String(ex.message || ex)); }
  };
  useEffect(() => { reload(); }, []);

  const onDeclare = async () => {
    const name = window.prompt("Project name (slug):");
    if (!name) return;
    const primary_lab = window.prompt("Primary lab id:", myLab) || myLab;
    if (!primary_lab) return;
    const membersRaw = window.prompt("Members (comma-separated @handles):", "@" + myHandle);
    if (membersRaw === null) return;
    const members = membersRaw.split(",").map(s => s.trim()).filter(Boolean);
    const machinesRaw = window.prompt("Machines hosting the data (comma-separated):", "lab-server");
    if (machinesRaw === null) return;
    const machines = machinesRaw.split(",").map(s => s.trim()).filter(Boolean);
    const description = window.prompt("Description (optional):", "") || "";
    try {
      await postCentreProject({ name, primary_lab, members, machines, description });
      reload();
    } catch (ex) { alert("Declare failed: " + (ex.message || ex)); }
  };

  const onReconcile = async (proj) => {
    // v1: pure-diff with empty actuals — surfaces "this lab member
    // hasn't been wired to Slack/GitHub/FS yet" deltas for every
    // declared member. A future commit will fetch actual state.
    try {
      const r = await postCentreProjectReconcile(proj.name, {});
      setDeltas({ ...deltas, [proj.name]: r.deltas });
    } catch (ex) { alert("Reconcile failed: " + (ex.message || ex)); }
  };

  if (err) return (
    <div className={"panel " + span}>
      <header><h2>Centre projects</h2></header>
      <div className="body error" style={{padding:14}}>{err}</div>
    </div>
  );
  if (rows === null) return null;

  // Hide for non-PI members when they belong to no declared project.
  const visible = isPI
    ? rows
    : rows.filter(r => (r.members || []).includes(myHandle));
  if (visible.length === 0 && !isPI) return null;

  return (
    <div className={"panel " + span}>
      <header>
        <h2>Centre projects</h2>
        <div className="row" style={{gap:8}}>
          <span className="meta">
            {visible.length} project{visible.length === 1 ? "" : "s"}
          </span>
          {isPI && (
            <button className="btn sm primary" onClick={onDeclare}>
              ＋ declare
            </button>
          )}
        </div>
      </header>
      <div className="body" style={{padding:0}}>
        {visible.length === 0 ? (
          <div className="muted" style={{padding:14, fontSize:13}}>
            No centre projects declared yet.{" "}
            {isPI && <span>Click <code>＋ declare</code> to register one.</span>}
          </div>
        ) : (
        <table className="dt">
          <thead><tr>
            <th>name</th>
            <th style={{width:110}}>primary lab</th>
            <th>members</th>
            <th style={{width:120}}>machines</th>
            <th style={{width:130}}>github</th>
            {isPI && <th style={{width:130}}></th>}
          </tr></thead>
          <tbody>
            {visible.map(r => (
              <React.Fragment key={r.name}>
                <tr>
                  <td>
                    <div style={{fontWeight:500}}>{r.name}</div>
                    {r.description && (
                      <div className="muted" style={{fontSize:11}}>{r.description}</div>
                    )}
                  </td>
                  <td className="mono" style={{fontSize:11}}>{r.primary_lab}</td>
                  <td>
                    {(r.members || []).map(h => (
                      <code key={h} style={{fontSize:11, marginRight:4}}>
                        @{h}
                      </code>
                    ))}
                  </td>
                  <td className="mono" style={{fontSize:11}}>
                    {(r.machines || []).join(", ") || "—"}
                  </td>
                  <td className="mono" style={{fontSize:11}}>
                    {r.github_org ? `${r.github_org}/${r.github_repo}` : "—"}
                  </td>
                  {isPI && (
                    <td>
                      <div className="row" style={{justifyContent:"flex-end", gap:4}}>
                        <button className="btn sm" onClick={() => onReconcile(r)}>
                          reconcile
                        </button>
                      </div>
                    </td>
                  )}
                </tr>
                {(deltas[r.name] || []).length > 0 && (
                  <tr><td colSpan={isPI ? 6 : 5}
                          style={{padding:"6px 14px", background:"#fffbe6"}}>
                    <strong style={{fontSize:11}}>Reconcile drift:</strong>
                    <ul style={{margin:"4px 0 0", paddingLeft:18, fontSize:11}}>
                      {deltas[r.name].map((d, i) => (
                        <li key={i}>
                          <Pill tone={d.severity === "block" ? "red"
                                    : d.severity === "warn" ? "warn" : "outline"}>
                            {d.kind}
                          </Pill>{" "}
                          {d.summary}
                          {d.apply_hint && (
                            <div className="muted" style={{fontFamily:"monospace",
                                                            fontSize:10, marginTop:2}}>
                              {d.apply_hint}
                            </div>
                          )}
                        </li>
                      ))}
                    </ul>
                  </td></tr>
                )}
                {deltas[r.name] && deltas[r.name].length === 0 && (
                  <tr><td colSpan={isPI ? 6 : 5}
                          style={{padding:"6px 14px", background:"#f0fff4",
                                   fontSize:11, color:"#2d7a2d"}}>
                    ✓ Reconcile clean — no drift.
                  </td></tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
        )}
      </div>
    </div>
  );
}

/* (12) The Collaborations window is gone: inter-group work is now plain
   projects whose members span groups (with an agreed shared Slack
   workspace enforced at creation). The registrar dashboard keeps its own
   collaboration-registry UI.  */

/* ───────── DecommissionsPanel — browse past soft-deletes ─────────
   The dashboard's "where did X go?" panel. Lists every decommission
   report on this machine, grouped by entity kind. Reports are local
   to the machine (per ~/.murmurent/decommissions/) — there's no
   cross-machine aggregation, by design. PI-only because the report
   contents include private paths and project memberships. */

function DecommissionsPanel({ span = "c-12" }) {
  const persona = window.DATA.persona || "member";
  const isPI = persona === "pi";
  const [reports, setReports] = useState(null);  // null = not yet loaded
  const [expanded, setExpanded] = useState(false);
  const [openReport, setOpenReport] = useState(null);  // {file, body}
  const [filter, setFilter] = useState("");

  const fetchList = async () => {
    try {
      const params = new URLSearchParams(window.location.search);
      const userParam = params.get("user");
      const r = await fetch(
        "/api/decommissions" + (userParam ? "?user=" + encodeURIComponent(userParam) : ""),
        { headers: { Accept: "application/json" } },
      );
      const j = await r.json();
      if (!r.ok) {
        setReports([]);
        return;
      }
      setReports(j.reports || []);
    } catch (_) { setReports([]); }
  };

  useEffect(() => { if (expanded && reports === null && isPI) fetchList(); }, [expanded]);

  const viewReport = async (file) => {
    try {
      const params = new URLSearchParams(window.location.search);
      const userParam = params.get("user");
      const r = await fetch(
        "/api/decommissions/" + encodeURIComponent(file)
        + (userParam ? "?user=" + encodeURIComponent(userParam) : ""),
        { headers: { Accept: "application/json" } },
      );
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || ("HTTP " + r.status));
      setOpenReport(j);
    } catch (ex) {
      window.alert("Could not load report: " + (ex.message || ex));
    }
  };

  if (!isPI) return null;

  const filtered = (reports || []).filter(
    r => !filter || r.kind === filter,
  );
  const kindCounts = (reports || []).reduce((acc, r) => {
    acc[r.kind] = (acc[r.kind] || 0) + 1; return acc;
  }, {});

  return (
    <div className={"panel " + span}>
      <header>
        <h2>Decommissions</h2>
        <div className="row" style={{gap:6}}>
          <span className="meta">
            {reports === null
              ? "click to load"
              : `${reports.length} report${reports.length === 1 ? "" : "s"} on this machine`}
          </span>
          <button className="btn sm" onClick={() => setExpanded(e => !e)}>
            {expanded ? "▾ hide" : "▸ show"}
          </button>
        </div>
      </header>
      {expanded && (
        <div className="body" style={{padding:0}}>
          {reports === null ? (
            <div style={{padding:"14px 18px", color:"var(--muted)", fontSize:12}}>loading…</div>
          ) : reports.length === 0 ? (
            <div style={{padding:"14px 18px", color:"var(--muted)", fontSize:12}}>
              No decommission reports yet. They appear here when you archive a
              project, disconnect an installation, deactivate a member, etc.
              Stored at <code>~/.murmurent/decommissions/</code>.
            </div>
          ) : (
            <>
              <div style={{padding:"6px 14px", borderBottom:"1px solid var(--rule)",
                           display:"flex", gap:6, alignItems:"center", flexWrap:"wrap"}}>
                <span className="mono muted" style={{fontSize:10, letterSpacing:1,
                                                     textTransform:"uppercase"}}>filter:</span>
                <button
                  type="button"
                  onClick={() => setFilter("")}
                  style={_filterStyle(filter === "")}>
                  all ({reports.length})
                </button>
                {Object.keys(kindCounts).sort().map(k => (
                  <button
                    key={k}
                    type="button"
                    onClick={() => setFilter(k)}
                    style={_filterStyle(filter === k)}>
                    {k} ({kindCounts[k]})
                  </button>
                ))}
              </div>
              <table className="dt">
                <thead><tr>
                  <th style={{width:90}}>kind</th>
                  <th>name</th>
                  <th>by</th>
                  <th style={{width:160}}>when</th>
                  <th style={{width:70}}></th>
                </tr></thead>
                <tbody>
                  {filtered.map(r => (
                    <tr key={r.file}>
                      <td>
                        <Pill tone={
                          r.kind === "project" ? "purple"
                          : r.kind === "machine" ? ""
                          : r.kind === "user" ? "amber"
                          : r.kind === "installation" ? ""
                          : r.kind === "sea" ? ""
                          : ""
                        }>{r.kind}</Pill>
                      </td>
                      <td>
                        <strong>{r.name}</strong>
                        <div className="mono muted" style={{fontSize:10}}>{r.file}</div>
                      </td>
                      <td className="mono" style={{fontSize:12}}>{r.decommissioned_by}</td>
                      <td className="muted" style={{fontSize:11}}>
                        {r.decommissioned_at ? r.decommissioned_at.slice(0, 16).replace("T", " ") : ""}
                      </td>
                      <td style={{textAlign:"right"}}>
                        <button
                          type="button"
                          onClick={() => viewReport(r.file)}
                          style={{
                            background:"transparent", border:"1px solid var(--rule-strong)",
                            borderRadius:2, padding:"1px 8px", cursor:"pointer",
                            fontSize:11, color:"var(--purple)", fontFamily:"var(--mono)",
                          }}>
                          view
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
      )}
      {openReport && (
        <DecommissionReportModal report={openReport} onClose={() => setOpenReport(null)} />
      )}
    </div>
  );
}

function _filterStyle(active) {
  return {
    fontFamily: "var(--mono)", fontSize: 11, padding: "1px 8px",
    border: "1px solid var(--rule-strong)", borderRadius: 2,
    cursor: "pointer",
    background: active ? "var(--purple)" : "var(--card)",
    color: active ? "white" : "var(--ink)",
  };
}

function DecommissionReportModal({ report, onClose }) {
  return (
    <div onClick={onClose} style={{
      position:"fixed", inset:0, background:"rgba(32,20,54,0.55)",
      display:"flex", alignItems:"flex-start", justifyContent:"center",
      zIndex:200, padding:"40px 20px", overflowY:"auto",
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background:"var(--card)", border:"1px solid var(--rule-strong)",
        borderRadius:2, padding:"18px 22px", width:"min(780px, 96vw)",
      }}>
        <div className="row" style={{justifyContent:"space-between", alignItems:"baseline"}}>
          <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:18, color:"var(--purple-deep)"}}>
            Decommission report
          </h2>
          <button type="button" className="btn sm ghost" onClick={onClose}>✕ close</button>
        </div>
        <div className="mono muted" style={{fontSize:11, marginBottom:8}}>
          ~/.murmurent/decommissions/{report.file}
        </div>
        <pre style={{
          background:"var(--paper-2)", border:"1px solid var(--rule)",
          borderRadius:2, padding:"12px 14px",
          fontFamily:"var(--mono)", fontSize:12, lineHeight:1.5,
          whiteSpace:"pre-wrap", wordBreak:"break-word",
          maxHeight:"60vh", overflowY:"auto", margin:0,
        }}>{report.body}</pre>
      </div>
    </div>
  );
}

/* ───────── Receptionist (inbound cross-group SEA queue) ───────── */
async function postInboundAction(id, action, body) {
  const params = new URLSearchParams(window.location.search);
  const userParam = params.get("user");
  const url = "/api/inbound-sea/" + encodeURIComponent(id) + "/" + encodeURIComponent(action)
    + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

function ReceptionistPanel({ inbound, span="c-12" }) {
  const persona = window.DATA.persona || "member";
  if (persona !== "pi") return null;  // member doesn't see this box
  const list = inbound || [];
  const refresh = async () => {
    if (typeof window.__murmurentFetchData === "function") {
      try { await window.__murmurentFetchData(window.DATA.persona); } catch (_) {}
    }
  };
  const onAccept = async (req) => {
    const routed_to = window.prompt("Route to which member? (e.g. @allie)");
    if (!routed_to || !routed_to.trim()) return;
    try { await postInboundAction(req.id, "accept", { routed_to: routed_to.trim() }); await refresh(); }
    catch (ex) { alert(ex.message || ex); }
  };
  const onDecline = async (req) => {
    const reason = window.prompt("Decline reason:");
    if (!reason || !reason.trim()) return;
    try { await postInboundAction(req.id, "decline", { reason: reason.trim() }); await refresh(); }
    catch (ex) { alert(ex.message || ex); }
  };
  return (
    <div className={"panel "+span}>
      <header>
        <h2>Receptionist · inbound SEA requests</h2>
        <span className="meta">
          {list.filter(r => r.state === "pending").length} pending ·
          {" "}{list.filter(r => r.state !== "pending").length} resolved
        </span>
      </header>
      <div className="body" style={{padding:"6px 0"}}>
        {list.length === 0 && (
          <div className="muted" style={{padding:"14px", fontSize:13}}>
            No inbound requests. Other groups will appear here when they
            consume our sea_catalog MCP.
          </div>
        )}
        {list.map(r => (
          <div key={r.id} style={{padding:"9px 14px", borderBottom:"1px solid var(--rule)",
                                  opacity: r.state === "pending" ? 1 : 0.6}}>
            <div style={{display:"flex", justifyContent:"space-between", alignItems:"baseline", gap:8}}>
              <div>
                <Pill tone={r.state === "pending" ? "amber" : (r.state === "accepted" ? "green" : "red")}>
                  {r.state}
                </Pill>
                <span className="mono" style={{fontSize:12, marginLeft:8}}>#{r.id}</span>
                <span className="muted" style={{marginLeft:6}}>·</span>
                <span style={{marginLeft:6, fontWeight:500}}>{r.from_handle}</span>
                <span className="muted" style={{marginLeft:4}}>({r.from_group})</span>
                <span className="muted" style={{marginLeft:6}}>→</span>
                <span className="mono" style={{marginLeft:6, fontSize:12, color:"var(--purple)"}}>
                  {r.catalog_slug}
                </span>
              </div>
              <span className="mono muted" style={{fontSize:10}}>{r.created_at}</span>
            </div>
            {r.description && (
              <div className="muted" style={{fontSize:12, marginTop:4, lineHeight:1.45}}>
                {r.description}
              </div>
            )}
            {r.routed_to && (
              <div className="mono muted" style={{fontSize:11, marginTop:3}}>
                routed to {r.routed_to}
              </div>
            )}
            {r.decline_reason && (
              <div style={{fontSize:11, color:"var(--red)", marginTop:3}}>
                {r.decline_reason}
              </div>
            )}
            {r.state === "pending" && (
              <div className="row" style={{marginTop:6, justifyContent:"flex-end", gap:6}}>
                <button className="btn sm primary" onClick={() => onAccept(r)}>accept · route</button>
                <button className="btn sm" onClick={() => onDecline(r)}>decline</button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ───────── lab oracle panel ───────── */
function OracleProcessButton() {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg]   = useState(null);
  const onClick = async () => {
    setBusy(true); setMsg(null);
    try {
      const params = new URLSearchParams(window.location.search);
      const userParam = params.get("user");
      const url = "/api/oracle/process" + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
      const res = await fetch(url, { method: "POST", headers: { Accept: "application/json" } });
      if (!res.ok) {
        let detail = "HTTP " + res.status;
        try { detail = (await res.json()).detail || detail; } catch (_) {}
        throw new Error(detail);
      }
      const j = await res.json();
      setMsg(j.stub
        ? `queued (${j.inputs.concluded_seas} concluded SEAs ready) — pipeline lands soon`
        : "processed");
      setTimeout(() => setMsg(null), 3500);
    } catch (ex) {
      setMsg("Failed: " + (ex.message || ex));
    } finally { setBusy(false); }
  };
  return (
    <span style={{display:"inline-flex", alignItems:"center", gap:6}}>
      <button className="btn sm" disabled={busy} onClick={onClick}
              title="Trigger an oracle distillation pass over recent activity">
        {busy ? "…" : "process input"}
      </button>
      {msg && <span style={{fontSize:10, color:"var(--muted)", maxWidth:240}}>{msg}</span>}
    </span>
  );
}

async function postOracleAction(slug, action, body) {
  const params = new URLSearchParams(window.location.search);
  const userParam = params.get("user");
  // strip oracle/ prefix if present
  const cleanSlug = slug.replace(/^oracle\//, "");
  const url = "/api/oracle/" + encodeURIComponent(cleanSlug) + "/" + encodeURIComponent(action)
    + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

function OracleDraftRow({ entry }) {
  const refresh = async () => {
    if (typeof window.__murmurentFetchData === "function") {
      try { await window.__murmurentFetchData(window.DATA.persona); } catch (_) {}
    }
  };
  const onApprove = async () => {
    try { await postOracleAction(entry.path, "approve"); await refresh(); }
    catch (ex) { alert(ex.message || ex); }
  };
  const onDecline = async () => {
    const reason = window.prompt("Decline reason:");
    if (!reason || !reason.trim()) return;
    try { await postOracleAction(entry.path, "decline", { reason: reason.trim() }); await refresh(); }
    catch (ex) { alert(ex.message || ex); }
  };
  return (
    <div style={{padding:"9px 14px", borderBottom:"1px solid var(--rule)",
                 background:"#fff7eb"}}>
      <div style={{display:"flex", justifyContent:"space-between", alignItems:"baseline", gap:8}}>
        <span style={{fontWeight:500, fontSize:14}}>{entry.title}</span>
        <Pill tone="amber">draft</Pill>
      </div>
      <div className="muted" style={{fontSize:12, marginTop:4, lineHeight:1.45}}>
        {entry.excerpt}
      </div>
      <div className="mono muted" style={{fontSize:10, marginTop:5}}>
        {entry.author} · {entry.date}
        {entry.project && <span> · {entry.project}</span>}
        <span style={{marginLeft:10, color:"var(--purple)"}}><code>{entry.path}</code></span>
      </div>
      <div className="row" style={{marginTop:6, justifyContent:"flex-end", gap:6}}>
        <button className="btn sm primary" onClick={onApprove}>approve</button>
        <button className="btn sm" onClick={onDecline}>decline</button>
      </div>
    </div>
  );
}

/* Personal Oracle — the member's own evolving knowledge base, backed by
   their personal Obsidian vault. No drafts/approval flow (that's the
   lab oracle's job); this is just the member's notes-to-self. */
function PersonalOraclePanel({ data, span="c-4" }) {
  const block = data || { folder: "oracle/", entry_count: 0, recent: [] };
  const recent = block.recent || [];
  // Vault read-access health: without Full Disk Access the vault silently reads
  // empty, so surface it here — an empty panel could mean "blocked", not "no notes".
  const vh = window.DATA.vault_health || { status: "unregistered", detail: "", path: null };
  const HEALTH = {
    ok:           { chip: "✓ readable",    color: "var(--green)",  bg: "rgba(79,107,58,0.10)", bd: "rgba(79,107,58,0.30)" },
    empty:        { chip: "✓ readable",    color: "var(--green)",  bg: "rgba(79,107,58,0.10)", bd: "rgba(79,107,58,0.30)" },
    missing:      { chip: "no oracle dir", color: "var(--amber, #8a6d3b)", bg: "rgba(138,109,59,0.10)", bd: "rgba(138,109,59,0.30)" },
    unregistered: { chip: "no vault",      color: "var(--muted-ink, #888)", bg: "rgba(136,136,136,0.10)", bd: "rgba(136,136,136,0.30)" },
    blocked:      { chip: "⚠ BLOCKED",     color: "var(--red)",    bg: "rgba(160,50,50,0.10)", bd: "rgba(160,50,50,0.35)" },
  };
  const hs = HEALTH[vh.status] || HEALTH.unregistered;
  return (
    <div className={"panel "+span}>
      <header>
        <h2>Oracle · personal</h2>
        <span style={{fontFamily:"var(--mono)", fontSize:10, letterSpacing:0.5,
              padding:"1px 6px", borderRadius:2, color:hs.color,
              background:hs.bg, border:"1px solid "+hs.bd}}
              title={vh.path ? "vault oracle dir: "+vh.path : "no vault registered"}>
          {hs.chip}
        </span>
      </header>
      <div className="muted" style={{padding:"2px 14px 6px",
           fontSize:11, borderBottom:"1px solid var(--rule)"}}>
        <code className="mono">{block.folder}</code>
        <span style={{marginLeft:8}}>{block.entry_count} entries</span>
      </div>
      {vh.status === "blocked" && (
        <div style={{margin:"8px 14px", padding:"8px 10px", borderRadius:3,
             color:"var(--red)", background:"rgba(160,50,50,0.08)",
             border:"1px solid rgba(160,50,50,0.30)", fontSize:12, lineHeight:1.5}}>
          <strong>Vault not readable — Full Disk Access needed.</strong> Entries
          below may be incomplete (blocked reads look like "no entries"). Grant FDA
          to VS Code, quit + relaunch, then run <code className="mono">murmurent oracle doctor</code>.
        </div>
      )}
      <div className="body" style={{padding:"6px 0"}}>
        {recent.map((e, i) => (
          <div key={i} style={{padding:"9px 14px", borderBottom:"1px solid var(--rule)"}}>
            <div style={{display:"flex", justifyContent:"space-between", alignItems:"baseline", gap:10}}>
              <span style={{fontWeight:500, fontSize:14, lineHeight:1.3, color:"var(--purple-deep)"}}>{e.title}</span>
              <span className="mono muted" style={{fontSize:10, whiteSpace:"nowrap"}}>{e.date}</span>
            </div>
            <div className="muted" style={{fontSize:12, marginTop:4, lineHeight:1.45}}>
              {e.excerpt}
            </div>
            <div className="mono muted" style={{fontSize:10, marginTop:5, letterSpacing:0.5, color:"var(--purple)"}}>
              <code>{e.path}</code>
            </div>
          </div>
        ))}
        {recent.length === 0 && (
          <div className="muted" style={{padding:"14px", fontSize:13}}>
            No personal oracle entries yet. Ask the Oracle to remember
            something and it'll show up here.
          </div>
        )}
      </div>
    </div>
  );
}

// A deterministic, vivid colour per agent name — same agent always gets the same
// hue, so the live feed is scannable at a glance.
const AGENT_PALETTE = [
  "#c0392b", "#d35400", "#b7791f", "#2e7d32", "#0b7285", "#1565c0",
  "#5b3a91", "#8e2f6b", "#00838f", "#4e342e", "#37474f", "#6a1b9a",
];
function agentColour(name) {
  let h = 0;
  for (let i = 0; i < (name || "").length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return AGENT_PALETTE[h % AGENT_PALETTE.length];
}

// Short day label for an agent-activity entry: "today" / "yesterday" /
// "Jul 10" from the entry's date, so days-old activity doesn't read as if it
// just happened. Legacy time-only lines (no date) fall back to "earlier".
function _agentDayLabel(dateStr) {
  if (!dateStr) return "earlier";
  const todayIso = (window.DATA.today && window.DATA.today.iso) || "";
  if (dateStr === todayIso) return "today";
  try {
    const d = new Date(dateStr + "T00:00:00");
    const t = todayIso ? new Date(todayIso + "T00:00:00") : new Date();
    const diffDays = Math.round((t - d) / 86400000);
    if (diffDays === 1) return "yesterday";
    const mon = d.toLocaleString("en-US", { month: "short" });
    const yr = d.getFullYear() !== t.getFullYear() ? " " + d.getFullYear() : "";
    return mon + " " + d.getDate() + yr;
  } catch (_) { return dateStr; }
}

function AgentsActivityPanel({ activity, span="c-12" }) {
  const feed = activity || [];
  return (
    <div className={"panel "+span}>
      <header>
        <h2>Agents · live</h2>
        <span className="meta">{feed.length ? feed.length + " recent" : "idle"}</span>
      </header>
      <div className="muted" style={{padding:"2px 14px 6px", fontSize:11,
           borderBottom:"1px solid var(--rule)"}}>
        subagent activity from <code className="mono">~/.murmurent/agents.log</code>
        {" "}· newest first
      </div>
      <div className="body" style={{padding:"6px 0", maxHeight:280, overflowY:"auto"}}>
        {feed.map((a, i) => {
          const col = agentColour(a.agent);
          return (
            <div key={i} style={{display:"flex", gap:10, alignItems:"baseline",
                 padding:"7px 14px", borderBottom:"1px solid var(--rule)",
                 borderLeft:"3px solid "+col, opacity: a.started ? 0.72 : 1}}>
              <span className="mono muted" style={{fontSize:10, whiteSpace:"nowrap",
                    display:"flex", flexDirection:"column", alignItems:"flex-start", lineHeight:1.3}}>
                <span style={{fontWeight:600, opacity:0.9}}>{_agentDayLabel(a.date)}</span>
                <span>{a.time}</span>
              </span>
              <span style={{fontFamily:"var(--mono)", fontSize:11, fontWeight:700,
                    letterSpacing:0.3, color:"#fff", background:col,
                    padding:"1px 7px", borderRadius:3, whiteSpace:"nowrap"}}>
                {a.agent}
              </span>
              <span style={{fontSize:12.5, lineHeight:1.4, color:"var(--ink)",
                    fontStyle: a.started ? "italic" : "normal",
                    fontWeight: a.started ? 400 : 500}}>
                {a.started ? "▸ " : ""}{a.text}
              </span>
            </div>
          );
        })}
        {feed.length === 0 && (
          <div className="muted" style={{padding:"14px", fontSize:13}}>
            No recent agent activity. When you dispatch an agent (or one finishes),
            its verdict shows up here. Requires the agent-log hook
            (<code className="mono">murmurent install --hooks</code>).
          </div>
        )}
      </div>
    </div>
  );
}

function LabOraclePanel({ entries, drafts, labFolder, span="c-6" }) {
  const list = entries || [];
  const pendingDrafts = drafts || [];
  const persona = window.DATA.persona || "member";
  const isPI = persona === "pi";
  return (
    <div className={"panel "+span}>
      <header>
        <h2>Lab oracle · recent</h2>
        <div className="row" style={{gap:6}}>
          <span className="meta">
            {list.length} published
            {isPI && pendingDrafts.length > 0 && (
              <span> · <strong style={{color:"var(--tiger-deep)"}}>
                {pendingDrafts.length} draft{pendingDrafts.length === 1 ? "" : "s"}
              </strong></span>
            )}
          </span>
          <OracleProcessButton />
        </div>
      </header>
      {labFolder && (
        <div className="muted" style={{padding:"2px 14px 6px",
             fontSize:11, borderBottom:"1px solid var(--rule)"}}>
          <code className="mono">{labFolder}</code>
        </div>
      )}
      <div className="body" style={{padding:"6px 0"}}>
        {/* PI-only: drafts queue at the top, awaiting approval. */}
        {isPI && pendingDrafts.length > 0 && (
          <>
            <div className="mono muted" style={{padding:"6px 14px", fontSize:10,
                                                 letterSpacing:1.5, textTransform:"uppercase",
                                                 borderBottom:"1px solid var(--rule)"}}>
              Drafts awaiting approval
            </div>
            {pendingDrafts.map((e, i) => (
              <OracleDraftRow key={"d"+i} entry={e} />
            ))}
            {list.length > 0 && (
              <div className="mono muted" style={{padding:"6px 14px", fontSize:10,
                                                  letterSpacing:1.5, textTransform:"uppercase",
                                                  borderBottom:"1px solid var(--rule)"}}>
                Published
              </div>
            )}
          </>
        )}
        {list.map((e, i) => (
          <div key={i} style={{padding:"9px 14px", borderBottom:"1px solid var(--rule)"}}>
            <div style={{display:"flex", justifyContent:"space-between", alignItems:"baseline", gap:10}}>
              <span style={{fontWeight:500, fontSize:14, lineHeight:1.3}}>{e.title}</span>
              <span className="mono muted" style={{fontSize:10, whiteSpace:"nowrap"}}>{e.date}</span>
            </div>
            <div className="muted" style={{fontSize:12, marginTop:4, lineHeight:1.45}}>
              {e.excerpt}
            </div>
            <div className="mono muted" style={{fontSize:10, marginTop:5, letterSpacing:0.5}}>
              {e.author}
              {e.project && <span> · {e.project}</span>}
              <span style={{marginLeft:10, color:"var(--purple)"}}>
                <code>{e.path}</code>
              </span>
            </div>
          </div>
        ))}
        {list.length === 0 && (
          <div className="muted" style={{padding:"14px", fontSize:13}}>
            No oracle entries yet. Promote a finding with{" "}
            <code className="mono">murmurent publish &lt;path&gt; --to oracle</code>.
          </div>
        )}
      </div>
    </div>
  );
}

/* ───────── inventory panel ───────── */
function InventoryPanel({ inv, span="c-3" }) {
  return (
    <div className={"panel "+span}>
      <header>
        <h2>Inventory</h2>
        <span className="meta">{inv.expired.length} expired · {inv.low.length} low</span>
      </header>
      <div className="body">
        <div className="hbar">
          <span className="lbl">reagents</span>
          <div className="track"><div className="fill" style={{width: (inv.stock.reagents[0]/inv.stock.reagents[1]*100)+"%"}}/></div>
          <span className="val">{inv.stock.reagents[0]}/{inv.stock.reagents[1]}</span>
        </div>
        <div className="hbar">
          <span className="lbl">kits</span>
          <div className="track"><div className="fill tiger" style={{width: (inv.stock.kits[0]/inv.stock.kits[1]*100)+"%"}}/></div>
          <span className="val">{inv.stock.kits[0]}/{inv.stock.kits[1]}</span>
        </div>

        <h4 style={{margin:"12px 0 6px", fontFamily:"var(--mono)", fontSize:10, letterSpacing:1.5, color:"var(--red)", textTransform:"uppercase"}}>expired</h4>
        {inv.expired.map(x => (
          <div key={x.name} style={{display:"flex",justifyContent:"space-between",fontSize:13,padding:"3px 0",borderBottom:"1px dotted var(--rule)"}}>
            <span>{x.name}</span><span className="mono muted">{x.expiry}</span>
          </div>
        ))}

        <h4 style={{margin:"12px 0 6px", fontFamily:"var(--mono)", fontSize:10, letterSpacing:1.5, color:"var(--tiger-deep)", textTransform:"uppercase"}}>low stock</h4>
        {inv.low.map(x => (
          <div key={x.name} style={{display:"flex",justifyContent:"space-between",fontSize:13,padding:"3px 0",borderBottom:"1px dotted var(--rule)"}}>
            <span>{x.name}</span><span className="mono muted">{x.qty}</span>
          </div>
        ))}

        <button className="btn sm" style={{marginTop:10, width:"100%"}}>↗ open inventory</button>
      </div>
    </div>
  );
}

/* ───────── activity panel (sparkline + feed) ───────── */
function ActivityPanel({ span="c-3" }) {
  return (
    <div className={"panel "+span}>
      <header>
        <h2>Activity</h2>
        <span className="meta">last 12 weeks</span>
      </header>
      <div className="body">
        <div className="mono" style={{fontSize:10, color:"var(--muted)", letterSpacing:1, textTransform:"uppercase"}}>SEAs closed / week</div>
        <div className="row" style={{justifyContent:"space-between", alignItems:"flex-end"}}>
          <div className="num" style={{fontSize:28, fontWeight:600, color:"var(--purple-deep)"}}>{D.spark[D.spark.length-1]}</div>
          <Sparkline data={D.spark} w={180} h={42} />
        </div>
        <div className="mono muted" style={{fontSize:11, marginTop:2}}>+28% vs 4-week avg</div>

        <h4 style={{margin:"14px 0 6px", fontFamily:"var(--mono)", fontSize:10, letterSpacing:1.5, color:"var(--muted)", textTransform:"uppercase"}}>since you last looked</h4>
        {D.notifs.map((n,i) => (
          <div key={i} style={{display:"flex",gap:8,fontSize:12,padding:"4px 0",borderBottom:"1px dotted var(--rule)"}}>
            <span className="mono muted" style={{width:60}}>{n.time}</span>
            <span style={{flex:1}}>{n.text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* Phase 6: POST /api/notebook/edit — opens today's entry in the user's
   editor. Server creates the file with a small template if missing. */
async function postNotebookEdit(date) {
  const res = await fetch("/api/notebook/edit", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(date ? { date } : {}),
  });
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}
// Expose so hifi-notebook.jsx (loaded as a separate <script>) can call it.
window.postNotebookEdit = postNotebookEdit;

function NotebookEditButton({ date, label="edit", style }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg]   = useState(null);
  const onClick = async (e) => {
    e.preventDefault();
    setBusy(true); setMsg(null);
    try {
      const r = await postNotebookEdit(date);
      setMsg(r.created ? "created · opened" : "opened");
      // Refresh dashboard — picks up word_count change for new files.
      if (typeof window.__murmurentFetchData === "function") {
        try { await window.__murmurentFetchData(window.DATA.persona); } catch (_) {}
      }
      setTimeout(() => setMsg(null), 2200);
    } catch (ex) {
      setMsg(String(ex.message || ex));
      console.warn("[murmurent] notebook edit failed", ex);
    } finally {
      setBusy(false);
    }
  };
  return (
    <span style={{display:"inline-flex", alignItems:"center", gap:8, ...(style||{})}}>
      <button className="btn sm" disabled={busy} onClick={onClick}>
        {busy ? "…" : label}
      </button>
      {msg && (
        <span style={{fontSize:11, color: /failed|HTTP/i.test(msg) ? "var(--red)" : "var(--muted)"}}>
          {msg}
        </span>
      )}
    </span>
  );
}

/* ───────── notebook panel — pulls from hifi-notebook.jsx ───────── */
function NotebookPanel({ span="c-9" }) {
  const NB = window.DATA.notebook || {};
  const t  = NB.today || {};
  const days = NB.days || [];
  const path = (NB.folder || "lab-notebook/") + (t.iso || "") + ".md";
  const todayDay = days.find(d => d.is_today) || {};
  const words = todayDay.word_count || 0;

  // Inline 7-day strip in the header — replaces the dropped rail.
  const onDayClick = async (iso) => {
    try {
      await window.postNotebookEdit(iso);
      if (typeof window.__murmurentFetchData === "function") {
        try { await window.__murmurentFetchData(window.DATA.persona); } catch (_) {}
      }
    } catch (ex) {
      alert("Could not open " + iso + ".md: " + (ex.message || ex));
    }
  };

  return (
    <div className={"panel "+span}>
      <header>
        <h2>Lab notebook · today</h2>
        <div className="row" style={{gap:10}}>
          <span className="meta">
            <code className="mono">{path}</code> · {words} words
          </span>
          <NotebookEditButton date={t.iso} />
        </div>
      </header>
      {/* 7-day strip (formerly the daily-notes rail). Click to open. */}
      <div style={{display:"flex", gap:4, padding:"8px 14px",
                   borderBottom:"1px solid var(--rule)",
                   background:"var(--paper-2)"}}>
        {days.slice().reverse().map(d => (
          <div
            key={d.iso}
            onClick={() => onDayClick(d.iso)}
            title={"Open " + d.iso + ".md"}
            style={{
              flex:1, textAlign:"center", cursor:"pointer",
              padding:"4px 2px", borderRadius:2,
              fontFamily:"var(--mono)",
              background: d.is_today ? "var(--purple)" : "transparent",
              color: d.is_today ? "#fff" : (d.has_entry ? "var(--ink-2)" : "var(--muted-2)"),
              border: d.has_entry ? "1px solid var(--rule)" : "1px dashed var(--rule)",
            }}
          >
            <div style={{fontSize:10, opacity:0.85}}>{d.weekday.toUpperCase()}</div>
            <div style={{fontSize:13, fontWeight:600}}>{d.iso.slice(8)}</div>
            <div style={{fontSize:9, opacity:0.7}}>
              {d.has_entry ? `${d.word_count}w` : "—"}
            </div>
          </div>
        ))}
      </div>
      <div className="body" style={{padding:"16px 22px 22px"}}>
        <window.NbToday />
      </div>
    </div>
  );
}

/* (NotebookRailPanel removed — daily-notes calendar lives inside the
   NotebookPanel header now, since both fed off the same files.) */

/* MemberProfileModal — view/edit member-specific settings. Opened from
   the gear button beside the member name in FooterMeta. POSTs to
   /api/member/settings on save (silently ignores 404 / fetch errors
   while the backend wiring lands). */
function MemberProfileModal({ onClose }) {
  const m = window.DATA.member || {};
  const initial = window.DATA.member_settings || {};
  const machineInitial = window.DATA.machine_settings || {};
  const labProviders = (window.DATA.lab_settings || {}).git_providers || [];
  const [form, setForm] = useState({
    email:    initial.email    || "",
    orcid:    initial.orcid    || "",
    bluesky:  initial.bluesky  || "",
    github:   initial.github   || "",
    osf:      initial.osf      || "",
    website:  initial.website  || "",
    office:   initial.office   || "",
    dry_lab:  initial.dry_lab  || "",
    wet_labs: initial.wet_labs || "",
    address:  initial.address  || "",
    city:     initial.city     || "",
    department: initial.department || "",
    // Phase 3: per-provider git usernames. Seed from the snapshot's
    // git_logins map (which back-fills github from legacy contact.github).
    git_logins: { ...(initial.git_logins || {}) },
  });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg]   = useState(null);
  // Server returns git commit + push probes after the save (lab_mgmt
  // is a git repo, so we replicate the change to the remote on every
  // edit — otherwise reseeds can silently wipe it). Surfacing the
  // probes inline lets the user see whether the push actually went
  // through.
  const [probes, setProbes] = useState(null);

  const update = (k) => (e) =>
    setForm((prev) => ({ ...prev, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setMsg(null); setProbes(null);
    try {
      const res = await fetch("/api/member/settings", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(form),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || ("HTTP " + res.status));
      }
      const body = await res.json();
      setProbes(body.probes || []);
      setMsg("saved");
      if (typeof window.__murmurentFetchData === "function") {
        try { await window.__murmurentFetchData(window.DATA.persona); } catch (_) {}
      }
      // Auto-close only when every git step was green; keep modal up
      // if push warned so the user sees it.
      const allGreen = (body.probes || []).every(p => p.status === "ok");
      if (allGreen) setTimeout(onClose, 1200);
    } catch (ex) {
      setMsg(String(ex.message || ex));
    } finally {
      setBusy(false);
    }
  };

  const labelStyle = {
    fontFamily:"var(--mono)", fontSize:10, letterSpacing:1,
    textTransform:"uppercase", color:"var(--muted)",
    marginTop:8, marginBottom:2,
  };
  const inputStyle = {
    padding:"5px 8px", border:"1px solid var(--rule-strong)",
    borderRadius:2, fontFamily:"var(--mono)", fontSize:12, width:"100%",
    boxSizing:"border-box", background:"var(--paper)",
  };
  const sectionStyle = {
    borderTop:"1px solid var(--rule)", paddingTop:10, marginTop:10,
  };
  const sectionHeader = {
    margin:0, fontFamily:"var(--mono)", fontSize:10, letterSpacing:1.5,
    textTransform:"uppercase", color:"var(--purple-deep)",
  };

  // Personal-vault display sources from machine_settings now — Obsidian
  // paths moved out of the member profile because they're per-machine.
  const vaultName = machineInitial.obsidian_vault_name || "—";

  return (
    <div onClick={onClose} style={{
      position:"fixed", inset:0, background:"rgba(32,20,54,0.55)",
      display:"flex", alignItems:"flex-start", justifyContent:"center",
      zIndex:200, padding:"40px 20px", overflowY:"auto",
    }}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} style={{
        background:"var(--card)", border:"1px solid var(--rule-strong)",
        borderRadius:2, padding:18, width:"min(640px, 96vw)",
        display:"flex", flexDirection:"column", gap:4,
      }}>
        <div className="row" style={{justifyContent:"space-between", alignItems:"baseline"}}>
          <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:20, color:"var(--purple-deep)"}}>
            Member profile
          </h2>
          <button type="button" className="btn sm ghost" onClick={onClose}>✕ close</button>
        </div>
        <p className="muted" style={{fontSize:12, margin:"4px 0 0"}}>
          Edits save to <code>&lt;lab-mgmt&gt;/members/&lt;handle&gt;.md</code> —
          follows you to any machine. Per-machine paths (Obsidian vault,
          notebook subfolder) live in the <strong>Machine settings</strong>
          dialog instead.
        </p>

        {/* Identity (read-only) */}
        <div style={sectionStyle}>
          <h4 style={sectionHeader}>Identity</h4>
          <div className="row" style={{flexWrap:"wrap", gap:14, marginTop:6, fontSize:13}}>
            <div><span className="muted">name</span> {_displayMemberName(m)}</div>
            <div><span className="muted">role</span> {_displayRole(m.role)}</div>
            <div><span className="muted">lab</span> {_displayLab(m.lab)}</div>
            <div><span className="muted">personal vault</span> <code className="mono">{vaultName}/</code></div>
          </div>
        </div>

        {/* Contact */}
        <div style={sectionStyle}>
          <h4 style={sectionHeader}>Contact</h4>
          <div style={labelStyle}>email</div>
          <input style={inputStyle} value={form.email} onChange={update("email")} />
          <div className="row" style={{gap:10, marginTop:4}}>
            <div style={{flex:1}}>
              <div style={labelStyle}>ORCID</div>
              <input style={inputStyle} value={form.orcid} onChange={update("orcid")} />
            </div>
            <div style={{flex:1}}>
              <div style={labelStyle}>Bluesky</div>
              <input style={inputStyle} value={form.bluesky} onChange={update("bluesky")} />
            </div>
          </div>
          <div className="row" style={{gap:10, marginTop:4}}>
            <div style={{flex:1}}>
              <div style={labelStyle}>GitHub</div>
              <input style={inputStyle} value={form.github} onChange={update("github")} />
            </div>
            <div style={{flex:1}}>
              <div style={labelStyle}>OSF</div>
              <input style={inputStyle} value={form.osf} onChange={update("osf")} />
            </div>
          </div>
          <div style={labelStyle}>website</div>
          <input style={inputStyle} value={form.website} onChange={update("website")} />
        </div>

        {/* Location */}
        <div style={sectionStyle}>
          <h4 style={sectionHeader}>Location</h4>
          <div className="row" style={{gap:10, marginTop:4}}>
            <div style={{flex:1}}>
              <div style={labelStyle}>office</div>
              <input style={inputStyle} value={form.office} onChange={update("office")} />
            </div>
            <div style={{flex:1}}>
              <div style={labelStyle}>dry lab</div>
              <input style={inputStyle} value={form.dry_lab} onChange={update("dry_lab")} />
            </div>
          </div>
          <div style={labelStyle}>wet labs</div>
          <input style={inputStyle} value={form.wet_labs} onChange={update("wet_labs")} />
          <div style={labelStyle}>address</div>
          <input style={inputStyle} value={form.address} onChange={update("address")} />
          <div style={labelStyle}>city, province</div>
          <input style={inputStyle} value={form.city} onChange={update("city")}
                 placeholder="London, ON N6A 3K7" />
          <div style={labelStyle}>department</div>
          <input style={inputStyle} value={form.department} onChange={update("department")} />
        </div>

        {/* Phase 3: Per-provider git logins. One input per provider the
            lab has declared. If the lab list is empty (legacy state),
            show only the GitHub field so existing users keep working. */}
        <div style={sectionStyle}>
          <h4 style={sectionHeader}>Git logins</h4>
          <div style={{fontSize:11, color:"var(--muted)", marginTop:3, marginBottom:6, lineHeight:1.5}}>
            Your username on each of the lab's git providers. The PI uses these
            to add you as a collaborator when you join a project.
          </div>
          {(labProviders.length === 0
            ? [{ id: "github", kind: "github", label: "GitHub", target: "" }]
            : labProviders).map((p) => (
            <div key={p.id} style={{marginTop:6}}>
              <div style={labelStyle}>
                {p.label || `${p.kind}${p.target ? " · " + p.target : ""}`}
                <span style={{textTransform:"none", letterSpacing:0, color:"var(--muted)", marginLeft:6}}>
                  ({p.id})
                </span>
              </div>
              <input style={inputStyle}
                     value={form.git_logins[p.id] || ""}
                     placeholder={p.kind === "github" ? "your-github-username" :
                                  p.kind === "gitea"  ? "your-gitea-username"  :
                                                        "(local-bare: not needed)"}
                     disabled={p.kind === "local-bare"}
                     onChange={(e) => setForm(prev => ({
                       ...prev,
                       git_logins: { ...prev.git_logins, [p.id]: e.target.value },
                     }))} />
            </div>
          ))}
        </div>

        {probes && probes.length > 0 && (
          <div style={{
            marginTop:12, padding:"8px 10px",
            background:"var(--paper-2)", border:"1px solid var(--rule)", borderRadius:2,
          }}>
            <div style={{fontSize:10.5, marginBottom:4, color:"var(--muted)",
                         textTransform:"uppercase", letterSpacing:1, fontFamily:"var(--mono)"}}>
              persisted to lab_mgmt
            </div>
            {probes.map((p, i) => (
              <div key={p.name + i} style={{
                fontSize:11.5, fontFamily:"var(--mono)",
                display:"flex", gap:6, alignItems:"baseline", marginTop:1,
              }}>
                <span style={{
                  color: p.status === "ok" ? "var(--green)" :
                         p.status === "warn" ? "var(--tiger)" : "var(--red)",
                  width:12,
                }}>
                  {p.status === "ok" ? "✓" : p.status === "warn" ? "!" : "✗"}
                </span>
                <span style={{width:100, color:"var(--muted)"}}>{p.name}</span>
                <span style={{flex:1, color:"var(--ink)"}}>{p.detail}</span>
              </div>
            ))}
          </div>
        )}

        <div className="row" style={{justifyContent:"flex-end", gap:6, marginTop:14, alignItems:"center"}}>
          {msg && (
            <span className="muted" style={{fontSize:11, marginRight:"auto"}}>{msg}</span>
          )}
          <button type="button" className="btn sm ghost" onClick={onClose}>close</button>
          <button type="submit" className="btn sm primary" disabled={busy}>
            {busy ? "…" : "save"}
          </button>
        </div>
      </form>
    </div>
  );
}

/* ───────── Hosts modal (R4: register + probe install targets) ─────────
   Lets the user register a remote SSH host (lab-server is the canonical
   first one), test connectivity, and remove. Once a host is registered
   it shows up in the New Project modal's host dropdown. */
function HostsModal({ onClose }) {
  const [hosts, setHosts] = useState([]);
  const [loadErr, setLoadErr] = useState(null);
  const [showAdd, setShowAdd] = useState(false);
  const [testing, setTesting] = useState({});  // {hostName: bool}
  const [results, setResults] = useState({});  // {hostName: probeBlock}

  const refresh = async () => {
    try {
      const r = await fetch("/api/hosts", { headers: { Accept: "application/json" } });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const j = await r.json();
      setHosts(j.hosts || []);
      setLoadErr(null);
    } catch (ex) {
      setLoadErr(String(ex.message || ex));
    }
  };
  useEffect(() => { refresh(); }, []);

  const runTest = async (name) => {
    setTesting(t => ({ ...t, [name]: true }));
    try {
      const r = await fetch("/api/hosts/" + encodeURIComponent(name) + "/test", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
      });
      const j = await r.json();
      if (!r.ok) {
        setResults(rs => ({ ...rs, [name]: {
          overall: "fail", probes: [],
          error: j.detail || ("HTTP " + r.status),
        }}));
      } else {
        setResults(rs => ({ ...rs, [name]: j }));
      }
    } catch (ex) {
      setResults(rs => ({ ...rs, [name]: {
        overall: "fail", probes: [], error: String(ex.message || ex),
      }}));
    } finally {
      setTesting(t => ({ ...t, [name]: false }));
    }
  };

  const removeHost = async (name) => {
    if (!window.confirm(`Remove host ${name}? (local cannot be removed)`)) return;
    try {
      const _actor = (window.DATA.member && window.DATA.member.handle) || "";
      const r = await fetch("/api/hosts/" + encodeURIComponent(name)
        + "?user=" + encodeURIComponent(_actor.replace(/^@/, "")),
        { method: "DELETE" });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        throw new Error(j.detail || ("HTTP " + r.status));
      }
      setResults(rs => { const o = {...rs}; delete o[name]; return o; });
      await refresh();
    } catch (ex) {
      alert("remove failed: " + (ex.message || ex));
    }
  };

  return (
    <div onClick={onClose} style={{
      position:"fixed", inset:0, background:"rgba(32,20,54,0.55)",
      display:"flex", alignItems:"flex-start", justifyContent:"center",
      zIndex:200, padding:"40px 20px", overflowY:"auto",
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background:"var(--card)", border:"1px solid var(--rule-strong)",
        borderRadius:2, padding:18, width:"min(720px, 96vw)",
        display:"flex", flexDirection:"column", gap:10,
      }}>
        <div className="row" style={{justifyContent:"space-between", alignItems:"baseline"}}>
          <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:20, color:"var(--purple-deep)"}}>
            Install hosts
          </h2>
          <button type="button" className="btn sm ghost" onClick={onClose}>✕ close</button>
        </div>
        <p className="muted" style={{fontSize:12, margin:0}}>
          Hosts you can install projects on. <code>local</code> is always this laptop;
          register an SSH host (e.g. <code>lab-server</code>) to enable the
          <em> New Project → host=&lt;name&gt;</em> deploy flow.
          Saved to <code>~/.murmurent/hosts.yaml</code>.
        </p>

        {loadErr && (
          <div style={{color:"var(--red)", fontSize:12}}>load failed: {loadErr}</div>
        )}

        <table className="dt" style={{marginTop:6}}>
          <thead><tr>
            <th>name</th><th>kind</th><th>target</th><th>project_root</th>
            <th>lab_vm_root</th><th style={{width:200}}>actions</th>
          </tr></thead>
          <tbody>
            {hosts.map(h => (
              <React.Fragment key={h.name}>
                <tr>
                  <td><strong>{h.name}</strong></td>
                  <td><Pill tone={h.kind === "ssh" ? "purple" : "green"}>{h.kind}</Pill></td>
                  <td className="mono" style={{fontSize:11}}>
                    {h.is_remote ? h.ssh_host : "(this laptop)"}
                  </td>
                  <td className="mono" style={{fontSize:11}}>{h.project_root}</td>
                  <td className="mono" style={{fontSize:11}}>{h.lab_vm_root}</td>
                  <td>
                    <button className="btn sm" disabled={testing[h.name]}
                            onClick={() => runTest(h.name)}>
                      {testing[h.name] ? "…" : "test"}
                    </button>
                    {h.name !== "local" && (window.DATA.persona === "pi") && (
                      <button className="btn sm" onClick={() => removeHost(h.name)}
                              style={{marginLeft:4, color:"var(--red)"}}>remove</button>
                    )}
                  </td>
                </tr>
                {results[h.name] && (
                  <tr>
                    <td colSpan={6} style={{
                      background:"var(--paper-2)", padding:"10px 14px",
                      borderBottom:"1px solid var(--rule)",
                    }}>
                      {results[h.name].error ? (
                        <div style={{color:"var(--red)", fontSize:12}}>
                          {results[h.name].error}
                        </div>
                      ) : (
                        <>
                          <div style={{fontSize:12, marginBottom:6}}>
                            overall: <Pill tone={results[h.name].overall === "ok" ? "green" : "red"}>
                              {results[h.name].overall}
                            </Pill>
                          </div>
                          {results[h.name].probes.map(p => (
                            <div key={p.name} style={{fontSize:12, fontFamily:"var(--mono)", display:"flex", gap:8, alignItems:"baseline"}}>
                              <span style={{
                                color: p.status === "ok" ? "var(--green)" :
                                       p.status === "warn" ? "var(--tiger)" : "var(--red)",
                                width: 14,
                              }}>
                                {p.status === "ok" ? "✓" : p.status === "warn" ? "!" : "✗"}
                              </span>
                              <span style={{width:80, color:"var(--muted)"}}>{p.name}</span>
                              <span style={{flex:1, color:"var(--ink)"}}>{p.detail}</span>
                            </div>
                          ))}
                        </>
                      )}
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>

        <div style={{marginTop:8}}>
          {showAdd ? (
            <HostAddForm onCancel={() => setShowAdd(false)} onAdded={async () => {
              setShowAdd(false);
              await refresh();
            }} />
          ) : (
            <button className="btn sm" onClick={() => setShowAdd(true)}>+ Add SSH host</button>
          )}
        </div>

        <div className="muted" style={{fontSize:11, marginTop:10, lineHeight:1.55}}>
          <strong>Once a host is registered:</strong>
          <ol style={{margin:"4px 0 0 18px", padding:0}}>
            <li>Run <code>bash scripts/install_remote.sh &lt;name&gt;</code> from the murmurent repo to install <code>uv</code> + <code>murmurent</code> on the host.</li>
            <li>Click <strong>test</strong> above — the four probes should all be ✓ or warn.</li>
            <li>Open <strong>New Project</strong> and pick the host from the dropdown.</li>
          </ol>
        </div>
      </div>
    </div>
  );
}

function HostAddForm({ onCancel, onAdded }) {
  /* Mirrors the machine cards: beyond the connection details (name,
     SSH host, username), a machine is described by the same three fields
     the cards show — Obsidian vault, Files, Repo locations. */
  const [form, setForm] = useState({
    name: "", ssh_host: "", remote_user: "",
    vault_root: "~/Obsidian", files_root: "~/lab_vm/data",
    repos_text: "~/repos", description: "",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr]   = useState(null);
  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    if (!form.name.trim() || !form.ssh_host.trim()) {
      setErr("name and SSH host are required"); return;
    }
    setBusy(true); setErr(null);
    try {
      const repos = form.repos_text
        .split("\n").map(s => s.trim()).filter(Boolean);
      const r = await fetch("/api/hosts", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          name: form.name.trim(),
          ssh_host: form.ssh_host.trim(),
          remote_user: form.remote_user.trim(),
          vault_root: form.vault_root.trim() || "~/Obsidian",
          lab_vm_root: form.files_root.trim() || "~/lab_vm/data",
          // First repo location doubles as where new clones land.
          project_root: repos[0] || "~/repos",
          scan_dirs: repos,
          description: form.description.trim(),
        }),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        throw new Error(j.detail || ("HTTP " + r.status));
      }
      onAdded();
    } catch (ex) {
      setErr(String(ex.message || ex));
    } finally { setBusy(false); }
  };

  const inp = {padding:"5px 8px", border:"1px solid var(--rule-strong)", borderRadius:2,
               fontFamily:"var(--mono)", fontSize:12, width:"100%", boxSizing:"border-box"};
  const lbl = {fontFamily:"var(--mono)", fontSize:10, letterSpacing:1,
               textTransform:"uppercase", color:"var(--muted)", marginTop:6, marginBottom:2};

  return (
    <form onSubmit={submit} style={{
      border:"1px solid var(--rule-strong)", borderRadius:2,
      padding:"10px 14px", background:"var(--paper)",
    }}>
      <div className="row" style={{justifyContent:"space-between", alignItems:"baseline"}}>
        <strong style={{fontFamily:"var(--serif)"}}>Add machine</strong>
        <button type="button" className="btn sm ghost" onClick={onCancel}>cancel</button>
      </div>
      <div className="row" style={{gap:10, marginTop:6}}>
        <div style={{flex:1}}>
          <div style={lbl}>name (short id)</div>
          <input style={inp} value={form.name} onChange={set("name")}
                 placeholder="lab-server" />
        </div>
        <div style={{flex:2}}>
          <div style={lbl}>SSH host (alias in ~/.ssh/config or full hostname)</div>
          <input style={inp} value={form.ssh_host} onChange={set("ssh_host")}
                 placeholder="lab-server.example.edu" />
        </div>
      </div>
      <div className="row" style={{gap:10, marginTop:4}}>
        <div style={{flex:1}}>
          <div style={lbl}>username on host (optional)</div>
          <input style={inp} value={form.remote_user} onChange={set("remote_user")}
                 placeholder="the_pi" />
        </div>
        <div style={{flex:2}}>
          <div style={lbl}>Obsidian vault (full path)</div>
          <input style={inp} value={form.vault_root} onChange={set("vault_root")} />
        </div>
      </div>
      <div style={lbl}>Files (data root — raw/ + refined/ live here)</div>
      <input style={inp} value={form.files_root} onChange={set("files_root")} />
      <div style={lbl}>Repo locations (one per line; the first is where new clones go)</div>
      <textarea style={{...inp, fontFamily:"var(--mono)", minHeight:54, resize:"vertical"}}
                value={form.repos_text} onChange={set("repos_text")}
                placeholder={"~/repos\n/srv/projects"} />
      <div style={lbl}>description (free text, optional)</div>
      <input style={inp} value={form.description} onChange={set("description")} />
      <div className="row" style={{justifyContent:"flex-end", gap:6, marginTop:10, alignItems:"baseline"}}>
        {err && <span style={{color:"var(--red)", fontSize:11, marginRight:"auto"}}>{err}</span>}
        <button type="submit" className="btn sm primary" disabled={busy}>
          {busy ? "…" : "add machine"}
        </button>
      </div>
    </form>
  );
}

/* ───────── Machines modal ─────────
   Unified per-machine view: lists the current machine plus every
   registered SSH host as a card, lets the user edit wigamig_base and the
   Obsidian vault for the current machine, and offers an "Add machine"
   form (the same one HostsModal used to use under "Add SSH host").

   Storage: the current machine's settings live in ~/.murmurent/machine.yaml
   (loaded into window.DATA.machine_settings). Remote hosts live in
   ~/.murmurent/hosts.yaml and are fetched from /api/hosts on mount. */

function _joinUnder(base, sub) {
  if (!base) return "—";
  const trimmed = String(base).replace(/\/+$/, "");
  return trimmed + "/" + String(sub).replace(/^\/+/, "");
}

/* Inline editor for a single host's scan_dirs. Stays put inside the
   MachineCard so the rest of the card (wigamig_base, vault, etc.)
   keeps its layout. Save → PATCH /api/hosts/{name}/scan-dirs → parent
   re-fetches /api/hosts via onSaved. */
function ScanDirsEditor({ hostName, initial, onSaved, onCancel }) {
  const [text, setText] = useState((initial || []).join("\n"));
  const [busy, setBusy] = useState(false);
  const [err, setErr]   = useState(null);
  const save = async () => {
    const scan_dirs = text.split("\n").map(s => s.trim()).filter(Boolean);
    setBusy(true); setErr(null);
    try {
      const r = await fetch(
        "/api/hosts/" + encodeURIComponent(hostName) + "/scan-dirs",
        { method: "PATCH",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ scan_dirs }) });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        throw new Error(j.detail || ("HTTP " + r.status));
      }
      await onSaved();
    } catch (ex) {
      setErr(String(ex.message || ex));
    } finally { setBusy(false); }
  };
  const inp = {padding:"5px 8px", border:"1px solid var(--rule-strong)", borderRadius:2,
               fontFamily:"var(--mono)", fontSize:12, width:"100%",
               boxSizing:"border-box", minHeight:64, resize:"vertical"};
  return (
    <div style={{marginTop:6, padding:"6px 8px",
                 border:"1px dashed var(--rule-strong)", borderRadius:2}}>
      <textarea style={inp} value={text} onChange={e => setText(e.target.value)}
                placeholder={"repos\nwork/clones\n/srv/projects"} />
      <div className="row" style={{justifyContent:"flex-end", gap:6, marginTop:6, alignItems:"baseline"}}>
        {err && <span style={{color:"var(--red)", fontSize:11, marginRight:"auto"}}>{err}</span>}
        <button type="button" className="btn sm ghost" onClick={onCancel} disabled={busy}>cancel</button>
        <button type="button" className="btn sm primary" onClick={save} disabled={busy}>
          {busy ? "…" : "save"}
        </button>
      </div>
    </div>
  );
}

function MachineCard({ machine, isCurrent, onEditClick, onRemove, onScanDirsSaved }) {
  const wb = machine.wigamig_base;
  const scanDirs = machine.scan_dirs || [];
  const labelStyle = {
    fontFamily:"var(--mono)", fontSize:10, letterSpacing:1,
    textTransform:"uppercase", color:"var(--muted)",
    display:"inline-block", width:120,
  };
  return (
    <div style={{
      border: isCurrent ? "2px solid var(--purple)" : "1px solid var(--rule-strong)",
      borderRadius:2, padding:"12px 14px", marginBottom:10,
      background: isCurrent ? "rgba(79,38,131,0.04)" : "var(--paper)",
    }}>
      <div className="row" style={{justifyContent:"space-between", alignItems:"baseline"}}>
        <div>
          <strong style={{fontFamily:"var(--serif)", fontSize:15}}>{machine.name}</strong>
          {" "}
          <Pill tone={machine.kind === "ssh" ? "purple" : "green"}>
            {machine.kind === "ssh" ? "SSH" : "this machine"}
          </Pill>
          {isCurrent && <span className="muted" style={{fontSize:11, marginLeft:6}}>· you are here</span>}
        </div>
        <div style={{display:"flex", gap:6}}>
          {onEditClick && (
            <button type="button" className="btn sm" onClick={onEditClick}>edit</button>
          )}
          {onRemove && (window.DATA.persona === "pi") && (
            <button type="button" className="btn sm" onClick={onRemove}
                    style={{color:"var(--red)"}}>delete</button>
          )}
        </div>
      </div>
      {machine.kind === "ssh" && (
        <div style={{fontSize:11, fontFamily:"var(--mono)", color:"var(--muted)", marginTop:4}}>
          {machine.remote_user ? machine.remote_user + "@" : ""}{machine.ssh_host}
        </div>
      )}
      {machine.description && (
        <div style={{fontSize:11, color:"var(--muted)", marginTop:4}}>{machine.description}</div>
      )}
      {/* Three locations per machine: Obsidian vault, Files (the data root —
          raw/ + refined/ live under it), and Repo location (where clones live).
          All editable together from the single "edit" button above. */}
      <div style={{marginTop:8, fontSize:12, lineHeight:1.7}}>
        <div><span style={labelStyle}>Obsidian vault</span>
          <code className="mono">{machine.obsidian_vault_path || machine.obsidian_vault_name || "—"}</code></div>
        <div><span style={labelStyle}>Files</span>
          <code className="mono">{wb || "—"}</code></div>
        <div><span style={labelStyle}>Repo location</span>
          <code className="mono">{scanDirs.length === 0
            ? <span className="muted">default (~/repo + ~/repos)</span>
            : scanDirs.join(", ")}</code></div>
      </div>
    </div>
  );
}

function ThisMachineEditor({ initial, onSaved, onCancel }) {
  const [form, setForm] = useState({
    wigamig_base:        initial.wigamig_base        || "~/wigamig",
    obsidian_vault_path: initial.obsidian_vault_path || "",
    obsidian_vault_name: initial.obsidian_vault_name || "",
    notebook_subfolder:  initial.notebook_subfolder  || "lab-notebook",
    oracle_subfolder:    initial.oracle_subfolder    || "oracle",
  });
  // Repo location (scan_dirs) is stored on the host registry, not machine.yaml,
  // so it's a separate field + a second save call.
  const [repos, setRepos] = useState((initial.scan_dirs || []).join("\n"));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg]   = useState(null);
  // Server-returned preflight probes (wigamig_base subfolder mkdirs +
  // Obsidian vault existence). Shown as green/yellow/red rows so the
  // user sees exactly which directories were created vs already there.
  const [probes, setProbes] = useState(null);
  const [overall, setOverall] = useState(null);

  const update = (k) => (e) => setForm((p) => ({ ...p, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setMsg(null); setProbes(null); setOverall(null);
    try {
      const res = await fetch("/api/machine/settings", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(form),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || ("HTTP " + res.status));
      }
      const body = await res.json();
      // Also persist Repo location (scan_dirs) to the local host registry.
      try {
        const scan_dirs = repos.split("\n").map(s => s.trim()).filter(Boolean);
        await fetch("/api/hosts/local/scan-dirs", {
          method: "PATCH",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ scan_dirs }),
        });
      } catch (_) {}
      setProbes(body.probes || []);
      setOverall(body.overall || "ok");
      setMsg("saved");
      if (typeof window.__murmurentFetchData === "function") {
        try { await window.__murmurentFetchData(window.DATA.persona); } catch (_) {}
      }
      // Only auto-close when everything was green; otherwise leave
      // the panel up so the user can see what went yellow/red.
      if ((body.overall || "ok") === "ok") {
        setTimeout(onSaved, 1200);
      }
    } catch (ex) { setMsg(String(ex.message || ex)); }
    finally { setBusy(false); }
  };

  const labelStyle = {
    fontFamily:"var(--mono)", fontSize:10, letterSpacing:1,
    textTransform:"uppercase", color:"var(--muted)", marginTop:8, marginBottom:2,
  };
  const inputStyle = {
    padding:"5px 8px", border:"1px solid var(--rule-strong)",
    borderRadius:2, fontFamily:"var(--mono)", fontSize:12, width:"100%",
    boxSizing:"border-box", background:"var(--paper)",
  };
  const derivedStyle = {
    padding:"5px 8px", border:"1px dashed var(--rule)",
    borderRadius:2, fontFamily:"var(--mono)", fontSize:12,
    background:"var(--paper-2)", color:"var(--ink-2)",
  };

  return (
    <form onSubmit={submit} style={{
      border:"1px solid var(--purple-soft)", borderRadius:2, padding:14,
      background:"var(--card)", marginBottom:10,
    }}>
      <h4 style={{margin:0, fontFamily:"var(--serif)", fontSize:15, color:"var(--purple-deep)"}}>
        Edit: this machine
      </h4>
      <p className="muted" style={{fontSize:11, margin:"2px 0 4px"}}>
        Saved to <code>~/.murmurent/machine.yaml</code>.
      </p>

      <div style={labelStyle}>Files (data root — raw/ + refined/ + lab_notebooks/ live under it)</div>
      <input style={inputStyle} value={form.wigamig_base}
             onChange={update("wigamig_base")} placeholder="~/wigamig" />

      <div style={labelStyle}>Repo location (one path per line; where clones live)</div>
      <textarea style={{...inputStyle, minHeight:56, resize:"vertical"}} value={repos}
                onChange={e => setRepos(e.target.value)} placeholder={"repos\nwork/clones"} />

      <div style={{borderTop:"1px solid var(--rule)", marginTop:10, paddingTop:6}}>
        <div style={labelStyle}>Obsidian vault (full path)</div>
        <input style={inputStyle} value={form.obsidian_vault_path}
               onChange={update("obsidian_vault_path")}
               placeholder="/Users/you/.../obsidian-lab" />
        <div style={{fontSize:11, color:"var(--muted)", marginTop:3}}>
          The vault name (used by <code>obsidian://</code> URLs) is derived
          automatically from the last segment of the path. The Obsidian vault is
          typically in iCloud Drive and lives separately from <code>wigamig_base</code>.
          It hosts your personal oracle.
        </div>
        <div className="row" style={{gap:10, marginTop:4}}>
          <div style={{flex:1}}>
            <div style={labelStyle}>notebook subfolder</div>
            <input style={inputStyle} value={form.notebook_subfolder}
                   onChange={update("notebook_subfolder")} />
          </div>
          <div style={{flex:1}}>
            <div style={labelStyle}>oracle subfolder</div>
            <input style={inputStyle} value={form.oracle_subfolder}
                   onChange={update("oracle_subfolder")} />
          </div>
        </div>
      </div>

      {probes && probes.length > 0 && (
        <div style={{
          marginTop:12, padding:"10px 12px",
          background:"var(--paper-2)", border:"1px solid var(--rule)", borderRadius:2,
        }}>
          <div style={{fontSize:11, marginBottom:6, color:"var(--muted)"}}>
            preflight: <strong style={{
              color: overall === "ok" ? "var(--green)" :
                     overall === "warn" ? "var(--tiger)" : "var(--red)",
            }}>{overall}</strong>
          </div>
          {probes.map(p => (
            <div key={p.name} style={{
              fontSize:12, fontFamily:"var(--mono)",
              display:"flex", gap:8, alignItems:"baseline", marginTop:2,
            }}>
              <span style={{
                color: p.status === "ok" ? "var(--green)" :
                       p.status === "warn" ? "var(--tiger)" : "var(--red)",
                width:14,
              }}>
                {p.status === "ok" ? "✓" : p.status === "warn" ? "!" : "✗"}
              </span>
              <span style={{width:140, color:"var(--muted)"}}>{p.name}</span>
              <span style={{flex:1, color:"var(--ink)"}}>{p.detail}</span>
            </div>
          ))}
        </div>
      )}

      <div className="row" style={{justifyContent:"flex-end", gap:6, marginTop:12, alignItems:"center"}}>
        {msg && <span className="muted" style={{
          fontSize:11, marginRight:"auto",
          color: msg === "saved" ? "var(--green)" : "var(--red)",
        }}>{msg}</span>}
        <button type="button" className="btn sm ghost" onClick={onCancel}>
          {overall === "ok" || !probes ? "cancel" : "close"}
        </button>
        <button type="submit" className="btn sm primary" disabled={busy}>
          {busy ? "…" : "save"}
        </button>
      </div>
    </form>
  );
}

function MachinesModal({ onClose }) {
  const ms = window.DATA.machine_settings || {};
  const [thisMachine, setThisMachine] = useState({ short_hostname: "", kind: "host" });
  const [hosts, setHosts] = useState([]);
  const [loadErr, setLoadErr] = useState(null);
  const [editingThis, setEditingThis] = useState(false);
  const [showAdd, setShowAdd] = useState(false);

  useEffect(() => {
    fetch("/api/environment/this_machine")
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setThisMachine(d); })
      .catch(() => {});
  }, []);

  const refreshHosts = async () => {
    try {
      const r = await fetch("/api/hosts", { headers: { Accept: "application/json" } });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const j = await r.json();
      setHosts(j.hosts || []);
      setLoadErr(null);
    } catch (ex) {
      setLoadErr(String(ex.message || ex));
    }
  };
  useEffect(() => { refreshHosts(); }, []);

  const removeHost = async (name) => {
    if (!window.confirm(`Remove machine "${name}"?`)) return;
    try {
      const _actor = (window.DATA.member && window.DATA.member.handle) || "";
      const r = await fetch("/api/hosts/" + encodeURIComponent(name)
        + "?user=" + encodeURIComponent(_actor.replace(/^@/, "")),
        { method: "DELETE" });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        throw new Error(j.detail || ("HTTP " + r.status));
      }
      await refreshHosts();
    } catch (ex) {
      alert("remove failed: " + (ex.message || ex));
    }
  };

  // Synthesise a card for "this machine" from machine_settings. The
  // local row from /api/hosts contributes scan_dirs (the only field
  // we surface there today); the rest of the local-machine knobs are
  // owned by machine.yaml.
  const localHost = hosts.find(h => h.name === "local");
  const thisCard = {
    // Use the "local" key so onScanDirsSaved PATCHes the right row.
    name: "local",
    kind: "local",
    wigamig_base:        ms.wigamig_base        || "",
    obsidian_vault_path: ms.obsidian_vault_path || "",
    obsidian_vault_name: ms.obsidian_vault_name || "",
    description: (thisMachine.short_hostname ? thisMachine.short_hostname + " · " : "")
                 + "OS user: " + (thisMachine.local_user || "?"),
    scan_dirs: localHost ? (localHost.scan_dirs || []) : [],
  };

  // Map remote hosts onto the same shape. The legacy hosts.yaml field
  // ``lab_vm_root`` semantically corresponds to ``wigamig_base`` on the
  // remote machine, so surface it under that name.
  const remoteCards = hosts.filter(h => h.name !== "local").map(h => ({
    name: h.name, kind: "ssh",
    ssh_host: h.ssh_host, remote_user: h.remote_user || "",
    wigamig_base: h.lab_vm_root || h.wigamig_base || "",
    obsidian_vault_path: h.vault_root || "",
    obsidian_vault_name: "",
    description: h.description || "",
    scan_dirs: h.scan_dirs || [],
  }));

  return (
    <div onClick={onClose} style={{
      position:"fixed", inset:0, background:"rgba(32,20,54,0.55)",
      display:"flex", alignItems:"flex-start", justifyContent:"center",
      zIndex:200, padding:"40px 20px", overflowY:"auto",
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background:"var(--card)", border:"1px solid var(--rule-strong)",
        borderRadius:2, padding:18, width:"min(720px, 96vw)",
        display:"flex", flexDirection:"column", gap:4,
      }}>
        <div className="row" style={{justifyContent:"space-between", alignItems:"baseline"}}>
          <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:20, color:"var(--purple-deep)"}}>
            Machines
          </h2>
          <button type="button" className="btn sm ghost" onClick={onClose}>✕ close</button>
        </div>
        <p className="muted" style={{fontSize:12, margin:"4px 0 8px"}}>
          Computers where you work. Each declares a <code>wigamig_base</code>
          containing <code>raw/</code>, <code>refined/</code>,
          <code> lab_notebooks/</code>, and <code>repos/</code>. The Obsidian
          vault (which hosts your personal oracle) lives separately. Stored
          in <code>~/.murmurent/machine.yaml</code> and <code>~/.murmurent/hosts.yaml</code>.
        </p>

        {editingThis ? (
          <ThisMachineEditor
            initial={ms}
            onSaved={() => setEditingThis(false)}
            onCancel={() => setEditingThis(false)}
          />
        ) : (
          <MachineCard machine={thisCard} isCurrent
                       onEditClick={() => setEditingThis(true)}
                       onScanDirsSaved={refreshHosts} />
        )}

        {loadErr && (
          <div style={{color:"var(--red)", fontSize:12}}>load failed: {loadErr}</div>
        )}

        {remoteCards.map(m => (
          <MachineCard key={m.name} machine={m} isCurrent={false}
                       onRemove={() => removeHost(m.name)}
                       onScanDirsSaved={refreshHosts} />
        ))}

        <div style={{marginTop:6}}>
          {showAdd ? (
            <HostAddForm onCancel={() => setShowAdd(false)} onAdded={async () => {
              setShowAdd(false);
              await refreshHosts();
            }} />
          ) : (
            <button type="button" className="btn sm" onClick={() => setShowAdd(true)}>
              + Add machine (SSH host)
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/* Backwards-compat alias: the FooterMeta still calls MachineSettingsModal. */
const MachineSettingsModal = MachinesModal;

/* ───────── MachinesPanel: inline content block ───────── */
/* Same data as MachinesModal but rendered as a side-by-side panel that
   sits next to Projects (below Installations). Replaces the old footer
   "⚙ machines" button — machines are conceptually part of the dashboard's
   content, not chrome. */
/* Unified editor for a REMOTE machine — Files (data root) + Repo location.
   (Obsidian vaults are per-user/local, so they aren't set for remote hosts.)
   Saves via PATCH /api/hosts/<name>. */
function HostEditForm({ host, onCancel, onSaved }) {
  const [files, setFiles] = useState(host.wigamig_base || "");
  const [repos, setRepos] = useState((host.scan_dirs || []).join("\n"));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setMsg(null);
    try {
      const scan_dirs = repos.split("\n").map(s => s.trim()).filter(Boolean);
      const res = await fetch("/api/hosts/" + encodeURIComponent(host.name), {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ lab_vm_root: files, scan_dirs }),
      });
      if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.detail || ("HTTP " + res.status)); }
      setMsg("saved");
      setTimeout(onSaved, 700);
    } catch (ex) { setMsg(String(ex.message || ex)); }
    finally { setBusy(false); }
  };
  const lbl = {fontFamily:"var(--mono)", fontSize:10, letterSpacing:1, textTransform:"uppercase",
               color:"var(--muted)", marginTop:8, marginBottom:2};
  const inp = {padding:"5px 8px", border:"1px solid var(--rule-strong)", borderRadius:2,
               fontFamily:"var(--mono)", fontSize:12, width:"100%", boxSizing:"border-box", background:"var(--paper)"};
  return (
    <form onSubmit={submit} style={{border:"1px solid var(--purple-soft)", borderRadius:2,
          padding:14, background:"var(--card)", marginBottom:10}}>
      <h4 style={{margin:0, fontFamily:"var(--serif)", fontSize:15, color:"var(--purple-deep)"}}>Edit: {host.name}</h4>
      <p className="muted" style={{fontSize:11, margin:"2px 0 4px"}}>
        Remote machine. (Obsidian vaults are per-user/local, so not set here.)
      </p>
      <div style={lbl}>Files (data root — raw/ + refined/ live under it)</div>
      <input style={inp} value={files} onChange={e => setFiles(e.target.value)} placeholder="/data/lab_vm/…" />
      <div style={lbl}>Repo location (one path per line; where clones live)</div>
      <textarea style={{...inp, minHeight:60, resize:"vertical"}} value={repos}
                onChange={e => setRepos(e.target.value)} placeholder={"repos\nwork/clones"} />
      <div className="row" style={{justifyContent:"flex-end", gap:6, marginTop:8, alignItems:"center"}}>
        {msg && <span className="muted" style={{fontSize:11, marginRight:"auto"}}>{msg}</span>}
        <button type="button" className="btn sm ghost" onClick={onCancel}>cancel</button>
        <button type="submit" className="btn sm primary" disabled={busy}>{busy ? "…" : "save"}</button>
      </div>
    </form>
  );
}

function MachinesPanel({ span = "c-5" }) {
  const ms = window.DATA.machine_settings || {};
  const [thisMachine, setThisMachine] = useState({ short_hostname: "", kind: "host" });
  const [hosts, setHosts] = useState([]);
  const [loadErr, setLoadErr] = useState(null);
  const [editingThis, setEditingThis] = useState(false);
  const [editingHost, setEditingHost] = useState(null);   // remote machine being edited
  const [showAdd, setShowAdd] = useState(false);

  useEffect(() => {
    fetch("/api/environment/this_machine")
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setThisMachine(d); })
      .catch(() => {});
  }, []);

  const refreshHosts = async () => {
    try {
      const r = await fetch("/api/hosts", { headers: { Accept: "application/json" } });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const j = await r.json();
      setHosts(j.hosts || []);
      setLoadErr(null);
    } catch (ex) {
      setLoadErr(String(ex.message || ex));
    }
  };
  useEffect(() => { refreshHosts(); }, []);

  const removeHost = async (name) => {
    if (!window.confirm(`Remove machine "${name}"?`)) return;
    try {
      const _actor = (window.DATA.member && window.DATA.member.handle) || "";
      const r = await fetch("/api/hosts/" + encodeURIComponent(name)
        + "?user=" + encodeURIComponent(_actor.replace(/^@/, "")),
        { method: "DELETE" });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        throw new Error(j.detail || ("HTTP " + r.status));
      }
      await refreshHosts();
    } catch (ex) {
      alert("remove failed: " + (ex.message || ex));
    }
  };

  const localHost = hosts.find(h => h.name === "local");
  const thisCard = {
    name: "local",
    kind: "local",
    wigamig_base:        ms.wigamig_base        || "",
    obsidian_vault_path: ms.obsidian_vault_path || "",
    obsidian_vault_name: ms.obsidian_vault_name || "",
    description: (thisMachine.short_hostname ? thisMachine.short_hostname + " · " : "")
                 + "OS user: " + (thisMachine.local_user || "?"),
    scan_dirs: localHost ? (localHost.scan_dirs || []) : [],
  };
  const remoteCards = hosts.filter(h => h.name !== "local").map(h => ({
    name: h.name, kind: "ssh",
    ssh_host: h.ssh_host, remote_user: h.remote_user || "",
    wigamig_base: h.lab_vm_root || h.wigamig_base || "",
    obsidian_vault_path: h.vault_root || "",
    obsidian_vault_name: "",
    description: h.description || "",
    scan_dirs: h.scan_dirs || [],
  }));
  const total = 1 + remoteCards.length;

  return (
    <div className={"panel " + span}>
      <header>
        <h2>Machines</h2>
        <div className="row" style={{gap:6}}>
          <span className="meta">
            {total} total · 1 here · {remoteCards.length} remote
          </span>
          <button className="btn sm" onClick={() => setShowAdd(s => !s)}>
            {showAdd ? "× cancel" : "＋ add machine"}
          </button>
        </div>
      </header>
      <div style={{padding:"10px 14px"}}>
        {loadErr && (
          <div style={{color:"var(--red)", fontSize:12, marginBottom:8}}>
            load failed: {loadErr}
          </div>
        )}
        {editingThis ? (
          <ThisMachineEditor
            initial={{ ...ms, scan_dirs: thisCard.scan_dirs }}
            onSaved={() => { setEditingThis(false); refreshHosts(); }}
            onCancel={() => setEditingThis(false)}
          />
        ) : editingHost ? (
          <HostEditForm
            host={remoteCards.find(m => m.name === editingHost) || {}}
            onCancel={() => setEditingHost(null)}
            onSaved={async () => { setEditingHost(null); await refreshHosts(); }}
          />
        ) : (
          /* Up to 3 machine cards per row. */
          <div style={{display:"flex", flexWrap:"wrap", gap:10, alignItems:"stretch"}}>
            <div style={{flex:"1 1 calc(33.333% - 7px)", minWidth:230, display:"flex"}}>
              <MachineCard machine={thisCard} isCurrent
                           onEditClick={() => setEditingThis(true)} />
            </div>
            {remoteCards.map(m => (
              <div key={m.name} style={{flex:"1 1 calc(33.333% - 7px)", minWidth:230, display:"flex"}}>
                <MachineCard machine={m} isCurrent={false}
                             onEditClick={() => setEditingHost(m.name)}
                             onRemove={() => removeHost(m.name)} />
              </div>
            ))}
          </div>
        )}
        {showAdd && (
          <HostAddForm onCancel={() => setShowAdd(false)} onAdded={async () => {
            setShowAdd(false);
            await refreshHosts();
          }} />
        )}
      </div>
    </div>
  );
}

/* ───────── Lab settings modal (PI + admins only) ───────── */
/* Split a lab_base "host:/abs/path" string into host and path components.
   Falls back to (null, value) if there is no host: prefix. */
function _splitLabBase(s) {
  if (!s) return { host: null, path: "" };
  const i = s.indexOf(":/");
  if (i < 0) return { host: null, path: s };
  return { host: s.slice(0, i), path: s.slice(i + 1) };
}

/* Append a subpath under lab_base, preserving the host: prefix. Returns "—"
   if lab_base is empty so the UI can show a placeholder. */
function _underLabBase(labBase, sub) {
  if (!labBase) return "—";
  const { host, path } = _splitLabBase(labBase);
  const joined = (path.replace(/\/+$/, "")) + "/" + String(sub).replace(/^\/+/, "");
  return host ? host + ":" + joined : joined;
}

/* MasterFoldersDot — tiny persistent status pill next to "⚙ lab" in
   the footer. Renders from the cached snapshot field
   ``window.DATA.master_folders`` so it never blocks page load on an
   SSH probe. Clicking opens Lab Settings so the user can re-check or
   initialize. The cache fills in the first time the user presses the
   "check" or "initialize" buttons inside Lab Settings → Master Folders. */
function MasterFoldersDot({ onClick }) {
  const mf = (window.DATA && window.DATA.master_folders) || {};
  const overall = mf.overall;
  const color =
    overall === "ok"   ? "var(--green)" :
    overall === "warn" ? "var(--tiger)" :
    overall === "fail" ? "var(--red)"   : "var(--muted)";
  const label =
    overall === "ok"   ? "master folders ok"     :
    overall === "warn" ? "master folders: gaps"  :
    overall === "fail" ? "master folders: error" :
                          "master folders: ?";
  const tip = mf.checked
    ? `Last checked ${mf.checked.slice(0, 16).replace("T", " ")}. Click for details.`
    : "Master folders status not yet probed. Click to check.";
  return (
    <button
      type="button"
      onClick={onClick}
      title={tip}
      style={{
        background:"transparent", border:"1px solid var(--rule)",
        borderRadius:2, padding:"1px 6px", cursor:"pointer",
        fontSize:11, color:"var(--muted)",
        display:"inline-flex", alignItems:"center", gap:4,
      }}>
      <span style={{color, fontSize:13, lineHeight:1}}>●</span>
      <span>{label}</span>
    </button>
  );
}

/* MasterFoldersPanel — inline block on the Lab Settings modal that
   probes the five master folders on the lab_base server and lets the
   PI bootstrap any that are missing. Probes go through SSH (Remote
   over ~/.ssh/config), so the panel only fires on explicit user
   click — no automatic SSH on dashboard open. The result is cached
   server-side so the dashboard's persistent indicator can render
   without re-connecting. */
function MasterFoldersPanel({ labBase }) {
  const cached = (window.DATA && window.DATA.master_folders) || {};
  const [probes, setProbes] = useState(null);
  const [overall, setOverall] = useState(cached.overall || null);
  const [checked, setChecked] = useState(cached.checked || null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  // Lockout cooldown: lab-server locks the account for 30 minutes after
  // 3 failed auths. When we see a "Permission denied" / auth-failure
  // detail, freeze the buttons for 90s so the user can read the
  // message and fix their key/VPN before tripping the lockout.
  const [cooldownUntil, setCooldownUntil] = useState(0);
  const [, setTick] = useState(0);  // forces re-render so the countdown updates
  useEffect(() => {
    if (cooldownUntil <= Date.now()) return;
    const id = setInterval(() => setTick(t => t + 1), 1000);
    return () => clearInterval(id);
  }, [cooldownUntil]);
  const remainingSec = Math.max(0, Math.ceil((cooldownUntil - Date.now()) / 1000));
  const onCooldown = remainingSec > 0;

  // Heuristic: any of these substrings in the probe details means the
  // SSH server actively rejected our auth (vs a connection-refused /
  // timeout, which doesn't count against the lockout).
  const _looksLikeAuthFailure = (probesList) => {
    const blob = (probesList || []).map(p => (p.detail || "").toLowerCase()).join("\n");
    return [
      "permission denied",
      "authentication failed",
      "publickey,password",
      "too many authentication failures",
    ].some(s => blob.includes(s));
  };

  const run = async (mode /* "check" | "init" */) => {
    if (onCooldown) return;
    setBusy(true); setErr(null); setProbes(null);
    try {
      const url = mode === "init"
        ? "/api/lab/master_folders/init?user="
            + encodeURIComponent(new URLSearchParams(window.location.search).get("user") || "")
        : "/api/lab/master_folders?refresh=true";
      const res = await fetch(url, { method: mode === "init" ? "POST" : "GET" });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || ("HTTP " + res.status));
      setProbes(body.probes || []);
      setOverall(body.overall || null);
      setChecked(body.checked || null);
      if (_looksLikeAuthFailure(body.probes)) {
        setCooldownUntil(Date.now() + 90 * 1000);
      }
      if (typeof window.__murmurentFetchData === "function") {
        try { await window.__murmurentFetchData(window.DATA.persona); } catch (_) {}
      }
    } catch (ex) { setErr(String(ex.message || ex)); }
    finally { setBusy(false); }
  };

  const pillColor =
    overall === "ok"   ? "var(--green)" :
    overall === "warn" ? "var(--tiger)" :
    overall === "fail" ? "var(--red)"   : "var(--muted)";
  const pillText =
    overall === "ok"   ? "all 5 folders present" :
    overall === "warn" ? "some folders missing"  :
    overall === "fail" ? "ssh / probe failed"    :
    "not checked yet";

  return (
    <div style={{marginTop:12, padding:"10px 12px",
                 background:"var(--paper-2)", border:"1px solid var(--rule)", borderRadius:2}}>
      <div className="row" style={{justifyContent:"space-between", alignItems:"baseline", gap:8}}>
        <div>
          <div style={{fontSize:10.5, letterSpacing:1, textTransform:"uppercase",
                       fontFamily:"var(--mono)", color:"var(--muted)"}}>
            master folders on lab server
          </div>
          <div style={{fontSize:12, marginTop:2}}>
            <span style={{color:pillColor, marginRight:6}}>●</span>
            <span style={{color:"var(--ink)"}}>{pillText}</span>
            {checked && (
              <span className="muted" style={{fontSize:10.5, marginLeft:8}}>
                checked {checked.slice(0, 16).replace("T", " ")}
              </span>
            )}
          </div>
        </div>
        <div style={{display:"flex", gap:6}}>
          <button type="button" className="btn sm"
                  disabled={busy || onCooldown || !labBase}
                  onClick={() => run("check")}>
            {busy ? "…" : onCooldown ? `wait ${remainingSec}s` : "check"}
          </button>
          <button type="button" className="btn sm primary"
                  disabled={busy || onCooldown || !labBase}
                  onClick={() => run("init")}>
            {onCooldown ? `wait ${remainingSec}s` : "initialize missing"}
          </button>
        </div>
      </div>
      {onCooldown && (
        <div style={{
          marginTop:8, padding:"8px 10px", borderRadius:2,
          background:"rgba(240, 167, 87, 0.12)",
          border:"1px solid var(--tiger)",
          fontSize:11.5, lineHeight:1.5, color:"var(--ink)",
        }}>
          <strong>Auth failure detected.</strong> lab-server locks the account for
          <strong> 30 minutes after 3 failed logins</strong>. Buttons disabled
          for {remainingSec}s so you can: (1) check Western VPN is connected;
          (2) verify <code>ssh lab-server.example.edu</code> works in a
          terminal; (3) install your key with <code>ssh-copy-id -i ~/.ssh/laptop.pub lab-server.example.edu</code> if it isn't already authorized.
          Each click here is one auth attempt against the 3-strike limit.
        </div>
      )}
      {err && (
        <div style={{fontSize:11, color:"var(--red)", marginTop:6}}>{err}</div>
      )}
      {probes && probes.length > 0 && (
        <div style={{marginTop:8}}>
          {probes.map((p, i) => (
            <div key={p.name + i} style={{
              fontSize:12, fontFamily:"var(--mono)",
              display:"flex", gap:6, alignItems:"baseline", marginTop:1,
            }}>
              <span style={{
                color: p.status === "ok" ? "var(--green)" :
                       p.status === "warn" ? "var(--tiger)" : "var(--red)",
                width:12,
              }}>
                {p.status === "ok" ? "✓" : p.status === "warn" ? "!" : "✗"}
              </span>
              <span style={{width:100, color:"var(--muted)"}}>{p.name}</span>
              <span style={{flex:1, color:"var(--ink)"}}>{p.detail}</span>
            </div>
          ))}
        </div>
      )}
      <div className="muted" style={{fontSize:11, marginTop:8, lineHeight:1.5}}>
        Probes <code>{labBase || "(set lab_base above first)"}</code> over
        SSH. <strong>check</strong> only reads; <strong>initialize</strong> runs <code>mkdir -p</code> for each missing subfolder. Existing folders are
        never overwritten.
      </div>
    </div>
  );
}

/* GitProvidersEditor — inline list editor used inside Lab Settings.
   Each row is one provider: {id, kind, label, target}. PI adds /
   edits / removes; the parent form sends the full list on save. Kept
   ascii-friendly so monospace alignment stays readable. */
function GitProvidersEditor({ value, onChange }) {
  const KINDS = ["github", "gitea", "local-bare"];
  const HINTS = {
    "github":     "target = org name (e.g. hallettmiket)",
    "gitea":      "target = base URL (e.g. https://lab-server/gitea)",
    "local-bare": "target = absolute server-side dir (e.g. /data/<lab id>/repos)",
  };

  const update = (i, k, v) => {
    const next = value.slice();
    next[i] = { ...(next[i] || {}), [k]: v };
    onChange(next);
  };
  const remove = (i) => onChange(value.filter((_, j) => j !== i));
  const addRow = () => onChange([...value, {
    id: "", kind: "github", label: "", target: "",
  }]);

  const labelStyle = {
    fontFamily:"var(--mono)", fontSize:10, letterSpacing:1,
    textTransform:"uppercase", color:"var(--muted)", marginBottom:2,
  };
  const inputStyle = {
    padding:"4px 7px", border:"1px solid var(--rule-strong)",
    borderRadius:2, fontFamily:"var(--mono)", fontSize:12,
    boxSizing:"border-box", background:"var(--paper)", width:"100%",
  };

  return (
    <div>
      {(!value || value.length === 0) && (
        <div className="muted" style={{
          fontSize:11.5, padding:"8px 10px",
          border:"1px dashed var(--rule)", borderRadius:2,
          background:"var(--paper-2)",
        }}>
          No providers declared. Add one to enable per-project provider
          selection; otherwise the system synthesizes a single GitHub
          provider from the legacy <code>github_org</code> field.
        </div>
      )}
      {(value || []).map((p, i) => (
        <div key={i} style={{
          padding:"8px 10px", marginTop: i === 0 ? 0 : 6,
          border:"1px solid var(--rule)", borderRadius:2,
          background:"var(--paper-2)",
        }}>
          <div className="row" style={{gap:8, flexWrap:"wrap"}}>
            <div style={{flex:"1 1 140px", minWidth:120}}>
              <div style={labelStyle}>id</div>
              <input style={inputStyle} value={p.id || ""}
                     placeholder="github"
                     onChange={(e) => update(i, "id", e.target.value)} />
            </div>
            <div style={{flex:"0 0 130px"}}>
              <div style={labelStyle}>kind</div>
              <select style={inputStyle} value={p.kind || "github"}
                      onChange={(e) => update(i, "kind", e.target.value)}>
                {KINDS.map(k => <option key={k} value={k}>{k}</option>)}
              </select>
            </div>
            <div style={{flex:"2 1 220px", minWidth:160}}>
              <div style={labelStyle}>target</div>
              <input style={inputStyle} value={p.target || ""}
                     placeholder={HINTS[p.kind || "github"]}
                     onChange={(e) => update(i, "target", e.target.value)} />
            </div>
            <div style={{flex:"1 1 160px", minWidth:140}}>
              <div style={labelStyle}>display name (optional)</div>
              <input style={inputStyle} value={p.label || ""}
                     placeholder="e.g. Lab GitHub"
                     onChange={(e) => update(i, "label", e.target.value)} />
            </div>
            <div style={{display:"flex", alignItems:"flex-end"}}>
              <button type="button" className="btn sm ghost"
                      onClick={() => remove(i)}
                      style={{color:"var(--red)"}}>remove</button>
            </div>
          </div>
          <div className="muted" style={{fontSize:11, marginTop:4}}>
            {HINTS[p.kind || "github"]}
          </div>
        </div>
      ))}
      <div style={{marginTop:6}}>
        <button type="button" className="btn sm" onClick={addRow}>+ add provider</button>
      </div>
    </div>
  );
}

// Split/join a "host:/path" storage string into a machine + path pair.
function _splitHostPath(s) {
  const str = (s || "").trim();
  const i = str.indexOf(":");
  if (i < 0) return { host: str, path: "" };
  return { host: str.slice(0, i), path: str.slice(i + 1) };
}
function _joinHostPath(host, path) {
  const h = (host || "").trim();
  const p = (path || "").trim();
  if (!h && !p) return "";
  return h + ":" + p;
}
// Resolve the repos location to a FULL path so the Storage row reads
// /data/<id>/repos, consistent with the files row — not a bare "repos"
// subpath. A stored absolute path is used verbatim; a bare subpath is joined
// under the files path.
function _reposFullPath(filesPath, stored) {
  const s = (stored || "").trim();
  if (s.startsWith("/")) return s;                 // already an absolute path
  const base = (filesPath || "").replace(/\/+$/, "");
  // No files path configured yet → leave blank so the row shows its
  // placeholder (/data/<id>/repos), consistent with the empty files row
  // (which also shows a placeholder rather than a bare value).
  if (!base) return "";
  return base + "/" + (s || "repos").replace(/^\/+/, "");
}
// Inverse of _reposFullPath: the repos value is STORED as a subpath under
// lab_base (that's what the clone-remote + local-root resolvers expect), so on
// save we strip the files path back off the full path the user sees/edits.
function _reposSubpath(reposPath, filesPath) {
  const rp = (reposPath || "").trim().replace(/\/+$/, "");
  const fp = (filesPath || "").trim().replace(/\/+$/, "");
  if (!rp) return "repos";
  if (fp && (rp === fp || rp.startsWith(fp + "/"))) {
    return rp.slice(fp.length).replace(/^\/+/, "") || "repos";
  }
  return rp.replace(/^\/+/, "") || "repos";
}

function LabSettingsModal({ onClose }) {
  const ls = window.DATA.lab_settings || {};
  const _fb = _splitHostPath(ls.lab_base);
  const [form, setForm] = useState({
    // Identity
    display_name:      ls.display_name      || "",
    website:           ls.website           || "",
    // Lab parameters
    admins:            (ls.admins || []).join(", "),
    // GitHub — the PI's own GitHub IS the lab's GitHub org, so seed the org
    // from pi_github when the lab hasn't set an explicit org. Never fall back
    // to another lab's org.
    github_org:        ls.github_org        || ls.pi_github || "",
    // Repos are a full Machine + Path location like notebooks/Obsidian (not a
    // bare "repos" subpath), so the Path field reads /data/<id>/repos to match
    // the files row. Own host so editing it never moves the files machine.
    repos_host:        _fb.host,
    repos_path:        _reposFullPath(_fb.path, ls.git_repos_subpath),
    git_providers:     ls.git_providers     || [],
    // Slack — the PI's workspace is the lab's workspace.
    slack_workspace:   ls.slack_workspace   || "",
    slack_invite_url:  ls.slack_invite_url  || "",
    // Storage servers — three machine + path pairs. Files = the umbrella
    // (lab_base); notebooks + Obsidian get their own if the lab wants.
    files_host:        _fb.host,
    files_path:        _fb.path,
    notebook_host:     ls.notebook_host     || "",
    notebook_path:     ls.notebook_path     || "",
    obsidian_host:     ls.obsidian_host     || "",
    obsidian_path:     ls.obsidian_path     || "",
  });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg]   = useState(null);

  const update = (k) => (e) => setForm((prev) => ({ ...prev, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setMsg(null);
    try {
      const payload = {
        display_name:      form.display_name,
        website:           form.website,
        admins:            form.admins.split(",").map(s => s.trim()).filter(Boolean),
        github_org:        form.github_org,
        git_repos_subpath: _reposSubpath(form.repos_path, form.files_path),
        git_providers:     form.git_providers,
        slack_workspace:   form.slack_workspace,
        slack_invite_url:  form.slack_invite_url,
        // Files → the umbrella lab_base (host:/path).
        lab_base:          _joinHostPath(form.files_host, form.files_path),
        notebook_host:     form.notebook_host,
        notebook_path:     form.notebook_path,
        obsidian_host:     form.obsidian_host,
        obsidian_path:     form.obsidian_path,
      };
      const res = await fetch("/api/lab/settings", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || ("HTTP " + res.status));
      }
      setMsg("saved");
      if (typeof window.__murmurentFetchData === "function") {
        try { await window.__murmurentFetchData(window.DATA.persona); } catch (_) {}
      }
      setTimeout(onClose, 800);
    } catch (ex) { setMsg(String(ex.message || ex)); }
    finally { setBusy(false); }
  };

  const labelStyle = {
    fontFamily:"var(--mono)", fontSize:10, letterSpacing:1,
    textTransform:"uppercase", color:"var(--muted)", marginTop:8, marginBottom:2,
  };
  const inputStyle = {
    padding:"5px 8px", border:"1px solid var(--rule-strong)",
    borderRadius:2, fontFamily:"var(--mono)", fontSize:12, width:"100%",
    boxSizing:"border-box", background:"var(--paper)",
  };
  const microHint = {
    fontFamily:"var(--mono)", fontSize:9, letterSpacing:1,
    textTransform:"uppercase", color:"var(--muted)", marginTop:2,
  };
  const sectionHeader = {
    margin:0, fontFamily:"var(--mono)", fontSize:10, letterSpacing:1.5,
    textTransform:"uppercase", color:"var(--purple-deep)",
  };
  const sectionStyle = {
    borderTop:"1px solid var(--rule)", paddingTop:10, marginTop:6,
  };

  // One machine + path row for the Storage section. Rendered as a function
  // (not a nested component) so typing never loses input focus.
  const storageRow = ({ label, host, path, onHost, onPath, hostPh, pathPh, hint }) => (
    <div style={{marginTop:8}}>
      <div style={labelStyle}>{label}</div>
      <div className="row" style={{gap:8, alignItems:"flex-start"}}>
        <div style={{flex:"0 0 40%"}}>
          <input style={inputStyle} value={host} onChange={onHost} placeholder={hostPh} />
          <div style={microHint}>machine</div>
        </div>
        <div style={{flex:1}}>
          <input style={inputStyle} value={path} onChange={onPath} placeholder={pathPh} />
          <div style={microHint}>path</div>
        </div>
      </div>
      {hint ? <div style={{fontSize:11, color:"var(--muted)", marginTop:3, lineHeight:1.5}}>{hint}</div> : null}
    </div>
  );

  const githubOrg = (form.github_org || "").trim();
  const filesBase = _joinHostPath(form.files_host, form.files_path);
  const labMgmtPath = ls.lab_mgmt_path || "lab_mgmt";
  // Storage convention: everything for lab <id> lives under /data/<id>/.
  // We derive the example paths off the real lab id so the placeholders show
  // /data/mh/… for lab "mh", not a stale /data/lab_vm/wigamig.
  const labId       = (ls.name || "").trim();
  const dataRoot    = labId ? `/data/${labId}` : "/data/<lab id>";

  return (
    <div onClick={onClose} style={{
      position:"fixed", inset:0, background:"rgba(32,20,54,0.55)",
      display:"flex", alignItems:"flex-start", justifyContent:"center",
      zIndex:200, padding:"40px 20px", overflowY:"auto",
    }}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} style={{
        background:"var(--card)", border:"1px solid var(--rule-strong)",
        borderRadius:2, padding:18, width:"min(640px, 96vw)",
        display:"flex", flexDirection:"column", gap:4,
      }}>
        <div className="row" style={{justifyContent:"space-between", alignItems:"baseline"}}>
          <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:20, color:"var(--purple-deep)"}}>
            Lab settings
          </h2>
          <button type="button" className="btn sm ghost" onClick={onClose}>✕ close</button>
        </div>
        <p className="muted" style={{fontSize:12, margin:"4px 0 8px", lineHeight:1.5}}>
          Lab-wide parameters. Only the PI and designated admins can save. Edits
          write to <code className="mono">{labMgmtPath}/lab.md</code> and are
          committed + pushed for you.
        </p>

        {/* 1 · Identity */}
        <div style={sectionStyle}>
          <h4 style={sectionHeader}>Identity</h4>
          <div className="row" style={{flexWrap:"wrap", gap:14, marginTop:6, fontSize:13}}>
            <div><span className="muted">lab id</span> <code className="mono">{ls.name || "—"}</code></div>
            <div><span className="muted">netname of PI</span> <code className="mono">{ls.pi_handle || "—"}</code></div>
          </div>
          <div className="muted" style={{fontSize:11, marginTop:4, lineHeight:1.5}}>
            The lab id and PI netname you supplied at <code className="mono">murmurent init</code>.
            The lab's GitHub and Slack — which are the PI's — are set in the GitHub
            and Slack sections below.
          </div>
          <div style={labelStyle}>display name</div>
          <input style={inputStyle} value={form.display_name} onChange={update("display_name")}
                 placeholder="e.g. Hallett Lab" />
          <div style={labelStyle}>lab website</div>
          <input style={inputStyle} value={form.website} onChange={update("website")}
                 placeholder="https://mikehallett.science" />
        </div>

        {/* 2 · Members with administrative privileges */}
        <div style={sectionStyle}>
          <h4 style={sectionHeader}>Members with administrative privileges</h4>
          <div style={labelStyle}>handles (comma-separated)</div>
          <input style={inputStyle} value={form.admins} onChange={update("admins")}
                 placeholder="e.g. jsmith, admin_asst" />
          <div style={{fontSize:11, color:"var(--muted)", marginTop:4, lineHeight:1.5}}>
            The PI always has edit rights; add handles here to let those members
            change these lab settings too.
          </div>
        </div>

        {/* 3 · Lab GitHub account */}
        <div style={sectionStyle}>
          <h4 style={sectionHeader}>Lab GitHub account</h4>
          <div style={labelStyle}>GitHub org</div>
          <input style={inputStyle} value={form.github_org} onChange={update("github_org")}
                 placeholder="your-github-org" />
          {githubOrg
            ? <div style={{fontSize:11, color:"var(--muted)", marginTop:3}}>
                Lab GitHub: <a href={`https://github.com/${githubOrg}`} target="_blank" rel="noopener">https://github.com/{githubOrg}</a>
              </div>
            : null}
          <div style={{...labelStyle, marginTop:12}}>additional git providers</div>
          <div style={{fontSize:11, color:"var(--muted)", marginTop:3, marginBottom:6, lineHeight:1.5}}>
            Declare extra git origin servers (a self-hosted Gitea, a lab-server
            bare repo) if some projects don't use the GitHub org above. Each
            project picks one; each member registers a username per provider in
            Member Profile. The <em>display name</em> is just a friendly label
            in that picker — leave it blank to fall back to the id.
          </div>
          <GitProvidersEditor
            value={form.git_providers}
            onChange={(next) => setForm((p) => ({ ...p, git_providers: next }))}
          />
        </div>

        {/* 4 · Slack */}
        <div style={sectionStyle}>
          <h4 style={sectionHeader}>Slack</h4>
          <div style={{fontSize:11, color:"var(--muted)", marginTop:3, marginBottom:6, lineHeight:1.5}}>
            The lab's Slack workspace — the PI's workspace, recorded at Slack
            setup. Lab and project channels live here; the invite link is what
            you send new members so they can join.
          </div>
          <div style={labelStyle}>Slack workspace id</div>
          <input style={inputStyle} value={form.slack_workspace} onChange={update("slack_workspace")}
                 placeholder="e.g. TDUD7D20Y" />
          <div style={labelStyle}>Slack invite link</div>
          <input style={inputStyle} value={form.slack_invite_url} onChange={update("slack_invite_url")}
                 placeholder="https://join.slack.com/t/…/shared_invite/…" />
          {form.slack_invite_url
            ? <div style={{fontSize:11, color:"var(--muted)", marginTop:3}}>
                <a href={form.slack_invite_url} target="_blank" rel="noopener" style={{color:"var(--purple)"}}>join link ↗</a>
              </div>
            : null}
        </div>

        {/* 5 · Storage servers */}
        <div style={sectionStyle}>
          <h4 style={sectionHeader}>Storage servers</h4>
          <div style={{fontSize:11, color:"var(--muted)", marginTop:3, marginBottom:2, lineHeight:1.5}}>
            Lab files are located here — just a suggestion; each lab picks its
            own (e.g. <code className="mono">{dataRoot}</code>).
          </div>
          {storageRow({
            label: "files",
            host: form.files_host, path: form.files_path,
            onHost: update("files_host"), onPath: update("files_path"),
            hostPh: "lab-server.example.edu", pathPh: dataRoot,
          })}
          {/* Repos — moved here from the GitHub section. Same Machine/Path shape
              as the other storage rows for consistency. */}
          {storageRow({
            label: "repos on the lab server",
            host: form.repos_host, path: form.repos_path,
            onHost: update("repos_host"), onPath: update("repos_path"),
            hostPh: form.files_host || "lab-server.example.edu",
            pathPh: `${dataRoot}/repos`,
            hint: "Local copies of lab repos",
          })}
          {storageRow({
            label: "lab notebooks",
            host: form.notebook_host, path: form.notebook_path,
            onHost: update("notebook_host"), onPath: update("notebook_path"),
            hostPh: form.files_host || "lab-server.example.edu",
            pathPh: filesBase ? _underLabBase(filesBase, "notebooks") : `${dataRoot}/notebooks`,
            hint: "Where per-member lab notebooks live. Leave blank to keep them under the files path.",
          })}
          {storageRow({
            label: "Obsidian",
            host: form.obsidian_host, path: form.obsidian_path,
            onHost: update("obsidian_host"), onPath: update("obsidian_path"),
            hostPh: "this-laptop", pathPh: "~/Obsidian/lab-vault",
            hint: "The lab's Obsidian vault location (per-member vaults are set in Machine settings).",
          })}
        </div>

        <div className="row" style={{justifyContent:"flex-end", gap:6, marginTop:14, alignItems:"center"}}>
          {msg && <span className="muted" style={{fontSize:11, marginRight:"auto"}}>{msg}</span>}
          <button type="button" className="btn sm ghost" onClick={onClose}>close</button>
          <button type="submit" className="btn sm primary" disabled={busy}>
            {busy ? "…" : "save"}
          </button>
        </div>
      </form>
    </div>
  );
}

/* ───────── footer ───────── */
/* FooterMeta reads everything from window.DATA.member — the API merges the
   member's frontmatter (`contact:` / `location:`) on top of the lab defaults,
   so postdocs in a different building see their own office while inheriting
   the lab address. See snapshot._merge_contact / _merge_location. */
function FooterMeta() {
  const m = window.DATA.member;
  const loc = m.location || {};
  const c = m.contact || {};
  const [showProfile, setShowProfile] = useState(false);
  const ls = window.DATA.lab_settings || {};
  const persona = window.DATA.persona || "member";
  const isPI = persona === "pi";
  const myHandle = (m.handle || "").toLowerCase();
  const canEditLab = isPI || (ls.admins || []).map(h => h.toLowerCase()).includes(myHandle);
  const [showLabSettings, setShowLabSettings] = useState(false);
  const [showMachine, setShowMachine] = useState(false);

  // Build the office/dry-lab/wet-labs line, dropping any blank pieces.
  const officeBits = [
    loc.office     ? "Office: "   + loc.office   : null,
    loc.dry_lab    ? "Dry lab: "  + loc.dry_lab  : null,
    loc.wet_labs   ? "Wet labs: " + loc.wet_labs : null,
  ].filter(Boolean).join(" · ");

  return (
    <div className="footer-meta">
      {showProfile    && <MemberProfileModal  onClose={() => setShowProfile(false)} />}
      {showMachine    && <MachinesModal       onClose={() => setShowMachine(false)} />}
      {showLabSettings && <LabSettingsModal   onClose={() => setShowLabSettings(false)} />}
      <div className="grid">
        <div>
          <h5>
            <span style={{display:"inline-flex", alignItems:"center", gap:6}}>
              {m.name || m.handle}
              <button
                type="button"
                title="Edit my profile"
                onClick={() => setShowProfile(true)}
                style={{
                  background:"transparent", border:"1px solid var(--rule-strong)",
                  borderRadius:2, padding:"1px 6px", cursor:"pointer",
                  fontSize:11, color:"var(--purple)",
                }}>
                ⚙ profile
              </button>
              {/* ⚙ machines button moved into the Machines content block
                  (next to Projects, below Installations). The MachinesModal
                  state stays wired for back-compat in case external callers
                  still trigger it. */}
              {canEditLab && (
                <>
                  <button
                    type="button"
                    title="Lab settings (PI / admin)"
                    onClick={() => setShowLabSettings(true)}
                    style={{
                      background:"transparent", border:"1px solid var(--rule-strong)",
                      borderRadius:2, padding:"1px 6px", cursor:"pointer",
                      fontSize:11, color:"var(--purple)",
                    }}>
                    ⚙ lab
                  </button>
                  <MasterFoldersDot onClick={() => setShowLabSettings(true)} />
                </>
              )}
              {m.is_registrar && (
                <a
                  href={"/registrar?user=" + encodeURIComponent((m.handle || "").replace(/^@/, ""))}
                  title="Switch to the centre's registrar dashboard (you're listed as a registrar in _registry.yaml)"
                  style={{
                    background:"transparent", border:"1px solid var(--purple)",
                    borderRadius:2, padding:"1px 6px", cursor:"pointer",
                    fontSize:11, color:"var(--purple)", textDecoration:"none",
                  }}>
                  → registrar
                </a>
              )}
            </span>
          </h5>
          <div className="row mono muted" style={{fontSize:11, marginBottom:6}}>
            @{m.handle} · {_displayRole(m.role)} · {_displayLab(m.lab)}
          </div>
          <h5 style={{marginTop:10}}>Location</h5>
          {officeBits && <div className="row">{officeBits}</div>}
          {loc.address && <div className="row">{loc.address}</div>}
          {loc.city && <div className="row">{loc.city}</div>}
          {loc.department && <div className="row" style={{marginTop:8, color:"var(--muted)"}}>{loc.department}</div>}
        </div>

        <div>
          <h5>Contact</h5>
          {c.email && (
            <div className="row">
              <span className="lbl">Email</span>
              <a href={"mailto:" + c.email} target="_blank" rel="noopener">{c.email}</a>
            </div>
          )}
          {c.orcid && (
            <div className="row">
              <span className="lbl">ORCID</span>
              <a href={"https://orcid.org/" + c.orcid} target="_blank" rel="noopener">{c.orcid}</a>
            </div>
          )}
          {c.bluesky && (
            <div className="row">
              <span className="lbl">BlueSky</span>
              <a href={"https://bsky.app/profile/" + c.bluesky.replace(/^@/, "")} target="_blank" rel="noopener">{c.bluesky}</a>
            </div>
          )}
          {c.github && (
            <div className="row">
              <span className="lbl">GitHub</span>
              <a href={"https://github.com/" + c.github} target="_blank" rel="noopener">{c.github}</a>
            </div>
          )}
          {c.osf && (
            <div className="row">
              <span className="lbl">OSF</span>
              <a href={"https://" + c.osf} target="_blank" rel="noopener">{c.osf}</a>
            </div>
          )}
          {c.website && (
            <div className="row">
              <span className="lbl">Web</span>
              <a href={c.website} target="_blank" rel="noopener">{c.website}</a>
            </div>
          )}
          {ls.website && (
            <div className="row">
              <span className="lbl">Lab</span>
              <a href={ls.website} target="_blank" rel="noopener">{ls.website}</a>
            </div>
          )}
        </div>

        <div>
          <h5>Affiliations</h5>
          <div className="affil">
            <a href="https://www.schulich.uwo.ca/" target="_blank" rel="noopener">
              <img className="schulich" src="assets/Schulich_horizontal_CMYK.png" alt="Schulich School of Dentristy and Medicine" />
            </a>
            <a href="https://www.uwo.ca/" target="_blank" rel="noopener">
              <img className="western" src="assets/western_longWhite.png" alt="Western University" />
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}

function Footer() {
  return (
    <div className="footer">
      <div className="bar">
        <img className="lab-logo-mini" src="assets/lab-logo-hi-res.jpg" alt="Hallett Lab" />
        <a href="https://www.schulich.uwo.ca/" target="_blank" rel="noopener">
          <img className="schulich-mini" src="assets/Schulich_horizontal_CMYK.png" alt="Schulich School of Dentristy and Medicine" />
        </a>
        <a href="https://www.uwo.ca/" target="_blank" rel="noopener">
          <img className="western-mini" src="assets/western_longWhite.png" alt="Western University" />
        </a>
        <span className="dept">Department of Biochemistry · London, ON, Canada</span>
      </div>
      <div className="ack">
        We acknowledge that Western University is located on the traditional lands of the Anishinaabek, Haudenosaunee, Lūnaapéewak and Attawandaron peoples.
      </div>
    </div>
  );
}

/* ───────── App ───────── */
function App() {
  const [query, setQuery]     = useState("");
  const persona = window.DATA.persona || "member";  // derived, not user-chosen
  // Phase 1: hifi-data.jsx mutates window.DATA after fetching /api/dashboard
  // and calls window.__wigamigRerender() to bump this counter, which forces
  // a re-render so panels pick up the new data via the (mutated) D reference.
  const [, refreshTick] = useReducer((n) => n + 1, 0);
  useEffect(() => {
    window.__wigamigRerender = refreshTick;
    return () => { delete window.__wigamigRerender; };
  }, []);

  // keyboard: / to focus search. (Persona V-shortcut removed — persona is
  // derived from lab.md, not user-toggled.)
  useEffect(() => {
    const onKey = (e) => {
      if (e.target && (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA")) return;
      if (e.key === "/" || (e.key === "k" && (e.metaKey || e.ctrlKey))) {
        e.preventDefault();
        document.querySelector(".search input")?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <>
      <TopBar />
      <div className="app">
        <CmdBar query={query} setQuery={setQuery} />

        {/* Group members — the whole group (for the PI, the PI included; for a
            member, their shared-project peers). Uppermost so the first thing
            you see is who is in the lab/core. */}
        <div className="grid" style={{marginBottom:14}}>
          <LabMembersPanel peers={D.peers} span="c-12" />
        </div>

        {/* Where you work: Projects (a set of repos + machines) + Machines. */}
        <div className="grid" style={{marginBottom:14}}>
          <ProjectsPanel projects={D.projects} span="c-7" />
          <MachinesPanel span="c-5" />
        </div>

        {/* Daily action zone (Receptionist → All SEAs). Project-join requests
            and the Collaborations window are gone — membership is
            lead-controlled via certificates (project → Members), and
            inter-group work is just a project spanning groups. */}
        {persona === "pi" && (
          <div className="grid" style={{marginBottom:14}}>
            <ReceptionistPanel inbound={D.inbound_requests} span="c-12" />
          </div>
        )}

        <div className="grid" style={{marginBottom:14}}>
          <SeasPanel seas={D.seas} span="c-12" />
        </div>

        <div className="grid" style={{marginBottom:14}}>
          <PersonalOraclePanel data={D.personal_oracle} span="c-3" />
          <NotebookPanel span="c-5" />
          <LabOraclePanel entries={D.oracle_recent} drafts={D.oracle_drafts}
                          labFolder={D.lab_oracle_folder} span="c-4" />
        </div>

        {/* Live subagent feed — the browser equivalent of the tmux BR pane. */}
        <div className="grid" style={{marginBottom:14}}>
          <AgentsActivityPanel activity={D.agents_activity} span="c-12" />
        </div>

        {/* Repo inventory: cross-machine + GitHub audit — one column per
            registered machine (local included). Cached weekly, on-demand
            refresh. Per-row "↑ adopt" / "Install on <machine>" pre-fill
            the adopt/install wizards. Sits above Inventory: repos are
            the more frequently-consulted of the two. Terminal twin:
            `murmurent repo {list,status,adopt}`. */}
        <div className="grid" style={{marginBottom:14}}>
          <RepoInventoryPanel span="c-12" />
        </div>

        {/* Inventory: things you check, but not every day. (Lab members moved
            to the top of the page.) */}
        <div className="grid" style={{marginBottom:14}}>
          <InventoryPanel inv={D.inventory} span="c-12" />
        </div>

        {/* SEAs we offer (catalog) - every member sees; PI edits.
            Includes BOTH per-lab SEAs (the lab's own catalog) AND
            common SEAs shared centre-wide (kind ∈ skill/routine/mcp/
            dataset/service). Same outbound concept, two scopes. */}
        <div className="grid" style={{marginBottom:14}}>
          <SeaCatalogPanel entries={D.sea_catalog} span="c-12" />
        </div>

        {/* Core services browse + my bookings (Phase 3e of cores rollout).
            Hidden when no cores are registered. Every member sees both
            the cross-core catalog and their own live + (toggleable)
            terminal request history. */}
        <div className="grid" style={{marginBottom:14}}>
          <CoreServicesPanel span="c-12" />
        </div>

        {/* Lab's core charges this month (Phase 4d). PI-only;
            self-hides when the lab has no billed lines this month. */}
        {persona === "pi" && (
          <div className="grid" style={{marginBottom:14}}>
            <LabCoreChargesPanel span="c-6" />
          </div>
        )}

        {/* Lab security access — PI grants/revokes the wigamig-level
            ``lab_sudo`` flag that controls /security dashboard visibility.
            Independent of OS-level sudo on the lab server (which is a
            separate sysadmin grant; see docs/security-dashboard.md). */}
        {persona === "pi" && (
          <div className="grid" style={{marginBottom:14}}>
            <SecurityAccessPanel peers={D.peers} span="c-12" />
          </div>
        )}

        {/* Decommissions — history of soft-deletes on this machine (PI only). */}
        {persona === "pi" && (
          <div className="grid" style={{marginBottom:14}}>
            <DecommissionsPanel span="c-12" />
          </div>
        )}

        {/* Agents (large, low-frequency) lives toward the bottom. */}
        <div className="grid" style={{marginBottom:14}}>
          <AgentsPanel agents={D.agents} span="c-12" />
        </div>

        {/* Compliance - most sporadic; lives at the bottom.
            Top: TCPS_2 access matrix per project (clinical access).
            Bottom: full Western training roster per member. */}
        <div className="grid" style={{marginBottom:14}}>
          <Heatmap data={D.heatmap} persona={persona} span="c-12" />
        </div>
        <div className="grid">
          <TrainingCompliancePanel data={D.training_compliance} span="c-12" />
        </div>
      </div>
      <FooterMeta />
      <Footer />
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
