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
 * otherwise the server resolves from $WIGAMIG_USER). */
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
      if (typeof window.__wigamigFetchData === "function") {
        await window.__wigamigFetchData(window.DATA.persona);
      }
    } catch (ex) {
      setErr(String(ex.message || ex));
      console.warn("[wigamig] sea action failed", ex);
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
      if (typeof window.__wigamigFetchData === "function") {
        await window.__wigamigFetchData(window.DATA.persona);
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
      "wigamig will:\n" +
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
      if (typeof window.__wigamigFetchData === "function") {
        await window.__wigamigFetchData(window.DATA.persona);
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
  const m = window.DATA.member;
  return (
    <div className="topbar">
      <img className="lab-logo" src="assets/lab-logo-hi-res.jpg" alt="Hallett Lab" />
      <span className="sep">·</span>
      <span className="uwo">Schulich School of Dentristy and Medicine · Western University</span>
      <span className="who">
        signed in as <code>@{m.handle}</code> · lab: <code>{m.lab}</code>
      </span>
    </div>
  );
}

function CmdBar({ query, setQuery }) {
  // The persona arrives via ?persona= from the /login landing page; the
  // role badge below the search is informational (it reflects the lens
  // the user picked at sign-in).
  const persona = window.DATA.persona || "member";
  return (
    <div className="cmdbar">
      <div className="home">wigamig <small>v1.0.0</small></div>
      <div className="search">
        <span className="mono muted" style={{fontSize:12}}>›</span>
        <input
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="search SEAs, experiments, projects, people, notebook…"
        />
        <K>⌘K</K>
      </div>
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
  const [installCtx, setInstallCtx] = useState(null);  // {project, machine}
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
            clone · adopt · install · open
          </strong>{" — each host cell shows what's there now and offers the next step:"}
          <ul style={{margin:"4px 0 0 18px", padding:0}}>
            <li>
              <span className="mono" style={{color:"var(--muted)"}}>—</span>{" "}
              <em>nothing here.</em> Repo isn't on this host and has no GitHub origin to clone from.
            </li>
            <li>
              <span className="mono">+ install</span> — repo lives on GitHub but isn't on this host.
              <em> One click does</em> <strong>clone</strong> (git clone into <code>~/repos/&lt;name&gt;</code>) +
              <strong> adopt</strong> (write CHARTER.md, lab_mgmt registry entry, <code>.claude/agents/</code>) +
              <strong> install</strong> (mkdir raw/refined, write installation manifest).
              You become the lead; sensitivity defaults to <code>standard</code> — edit CHARTER.md after.
            </li>
            <li>
              <span className="mono">• clone</span> + <span className="mono">↑ adopt</span> — repo is on
              this host but never made wigamig-ready. <strong>Adopt</strong> writes CHARTER + registry + manifest
              + bootstraps <code>.claude/agents/</code>. The modal asks for lead, members, and sensitivity.
            </li>
            <li>
              <span className="mono" style={{color:"var(--green)"}}>✓ wigamig</span> — fully wigamig-ready.
              See it in <em>Projects</em> and <em>Installations</em>; <strong>open</strong> it from the
              Installations row's launcher.
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
                  onInstall={(project, machine, repoUrl) => setInstallCtx({project, machine, repoUrl})}
                  onAdopt={(ctx) => setAdoptCtx(ctx)}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>
      {installCtx && (
        <InstallModal
          initialProject={installCtx.project}
          initialMachine={installCtx.machine}
          initialRepoUrl={installCtx.repoUrl}
          onClose={() => {
            setInstallCtx(null);
            // After the install wizard closes, refresh the inventory
            // so a newly-cloned repo shows up immediately.
            load(true);
          }}
        />
      )}
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

function RepoInventoryRow({ row, knownHosts, onInstall, onAdopt }) {
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
      const wig = c.is_wigamig_installed;
      if (wig) {
        return (
          <span title={c.path} style={{
            fontSize:11, color:"var(--green)", fontFamily:"var(--mono)",
          }}>
            ✓ wigamig
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
                      ? "Promote this clone to a wigamig project"
                      : `Promote this clone on ${host} to a wigamig project (over SSH)`}
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
    if (gh && !row.local_only) {
      // GitHub URL passed through so the InstallModal can do a one-shot
      // clone+adopt+install without round-tripping through ↑ adopt
      // first. The server clones into ~/repos/<name> (local) or
      // ~/repos/<name> on the remote host (SSH) before projectizing.
      const cloneUrl = `git@github.com:${gh.full_name}.git`;
      return (
        <button className="btn sm" style={{fontSize:11, padding:"2px 6px"}}
                onClick={() => onInstall(gh.name, host === "local" ? "this" : host, cloneUrl)}>
          + install
        </button>
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

/* ── AdoptCloneModal: promote a plain git clone to a wigamig project.
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
      if (typeof window.__wigamigFetchData === "function") {
        try { await window.__wigamigFetchData(window.DATA.persona); } catch (_) {}
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
            Adopt clone as wigamig project
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
              Repo Inventory will show <strong style={{color:"var(--green)"}}>✓ wigamig</strong> for
              this clone on {clone.host}, and a row appears in Projects + Installations.
            </>
          ) : (
            <>
              Writes <code>CHARTER.md</code> at <code className="mono">{clone.path}</code>
              {" "}and bootstraps <code>.claude/agents/</code>. After this, the
              Repo Inventory will show <strong style={{color:"var(--green)"}}>✓ wigamig</strong> for
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
          wigamig agents to symlink — defaults to your install-wizard pick;
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

  // Soft-delete an installation: wigamig removes ~/.wigamig/
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
      "wigamig will remove the row from this panel and write a cleanup\n" +
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
      if (typeof window.__wigamigFetchData === "function") {
        await window.__wigamigFetchData(window.DATA.persona);
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
                            × disconnect from wigamig
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
   the paths wigamig deliberately did NOT touch (raw/, refined/,
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
          The row is gone from <strong>Installations</strong>. wigamig did
          <strong> not </strong> delete any data on the target machine — the
          paths below stay until you remove them yourself. A full report
          was written to <code className="mono" style={{fontSize:11}}>
            {cleanup.report || "~/.wigamig/decommissions/"}
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
      if (typeof window.__wigamigFetchData === "function") {
        try { await window.__wigamigFetchData(window.DATA.persona); } catch (_) {}
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
                    <label {...LBL}>Wigamig agents to deploy</label>
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
      if (typeof window.__wigamigFetchData === "function") {
        await window.__wigamigFetchData(window.DATA.persona);
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
  // pressing "Create Slack channel". Empty → server uses the wigamig
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
      if (typeof window.__wigamigFetchData === "function") {
        try { await window.__wigamigFetchData(window.DATA.persona); } catch (_) {}
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
      if (typeof window.__wigamigFetchData === "function") {
        try { await window.__wigamigFetchData(window.DATA.persona); } catch (_) {}
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
  const [showDecom, setShowDecom] = useState(false);
  const [busyDecom, setBusyDecom] = useState(null);  // project name currently being archived
  const persona = window.DATA.persona || "member";
  const isPI = persona === "pi";
  const archived = window.DATA.archived_projects || [];
  // Pending project-create requests — shown as an approval queue for the PI.
  const pendingCreate = (window.DATA.requests_pending || []).filter(
    r => r.kind === "project-create"
  );

  // Soft-delete a project: POST to /api/project/<name>/archive. The PI is
  // shown a confirm dialog because the action is reversible but emits a
  // decommission report — best to opt in deliberately.
  const archiveProj = async (name) => {
    const ok = window.confirm(
      `Decommission project "${name}"?\n\n` +
      "wigamig will:\n" +
      `  • flip the project's status to "archived" in CHARTER.md\n` +
      "  • write a decommission report to ~/.wigamig/decommissions/\n\n" +
      "wigamig will NOT delete any files (working clone, lab-base raw/refined, " +
      "Slack channel, GitHub repo are all left alone — review the report).\n\n" +
      "You can unarchive at any time from the Decommissioned section."
    );
    if (!ok) return;
    setBusyDecom(name);
    try {
      const r = await fetch(
        "/api/project/" + encodeURIComponent(name) + "/archive",
        { method: "POST", headers: { Accept: "application/json" } },
      );
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail || ("HTTP " + r.status));
      window.alert("Project '" + name + "' decommissioned.\n\nReport: " + j.report);
      if (typeof window.__wigamigFetchData === "function") {
        await window.__wigamigFetchData(window.DATA.persona);
      }
    } catch (ex) {
      window.alert("Archive failed: " + (ex.message || ex));
    } finally {
      setBusyDecom(null);
    }
  };

  const unarchiveProj = async (name) => {
    setBusyDecom(name);
    try {
      const r = await fetch(
        "/api/project/" + encodeURIComponent(name) + "/unarchive",
        { method: "POST", headers: { Accept: "application/json" } },
      );
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail || ("HTTP " + r.status));
      if (typeof window.__wigamigFetchData === "function") {
        await window.__wigamigFetchData(window.DATA.persona);
      }
    } catch (ex) {
      window.alert("Unarchive failed: " + (ex.message || ex));
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
            {archived.length > 0 && (
              <span> · <button
                type="button"
                onClick={() => setShowDecom(s => !s)}
                style={{
                  background:"transparent", border:0, padding:0,
                  color:"var(--muted)", cursor:"pointer",
                  textDecoration:"underline", fontFamily:"var(--mono)",
                  fontSize:11, letterSpacing:0.5,
                }}>
                {archived.length} decommissioned {showDecom ? "▾" : "▸"}
              </button></span>
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
                    <td style={{textAlign:"right"}} onClick={(e) => e.stopPropagation()}>
                      <button
                        type="button"
                        title="Decommission this project (soft delete; reversible). Writes a manual-cleanup report."
                        disabled={busyDecom === p.name}
                        onClick={() => archiveProj(p.name)}
                        style={{
                          background:"transparent", border:"1px solid var(--rule-strong)",
                          borderRadius:2, padding:"1px 6px", cursor:"pointer",
                          fontSize:11, color:"var(--red)", fontFamily:"var(--mono)",
                        }}>
                        {busyDecom === p.name ? "…" : "archive"}
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
        {showDecom && archived.length > 0 && (
          <div style={{
            borderTop:"2px dashed var(--rule)",
            background:"var(--paper-2)",
            padding:"8px 12px",
          }}>
            <div className="mono muted" style={{
              fontSize:10, letterSpacing:1, textTransform:"uppercase",
              marginBottom:6,
            }}>
              Decommissioned ({archived.length})
            </div>
            <table className="dt" style={{background:"transparent"}}>
              <tbody>
                {archived.map(p => (
                  <tr key={p.name}>
                    <td>
                      <div style={{fontWeight:500, color:"var(--muted)",
                                   textDecoration:"line-through"}}>
                        {p.name}
                      </div>
                      <div className="mono" style={{fontSize:11, color:"var(--muted)"}}>
                        {p.decommissioned_at
                          ? "decommissioned " + p.decommissioned_at.slice(0, 10)
                          : "archived"}
                        {p.decommissioned_by ? " by " + p.decommissioned_by : ""}
                      </div>
                    </td>
                    <td style={{width:90, color:"var(--muted)"}}>
                      <Pill tone={p.sens==="clinical"?"red":""}>{p.sens}</Pill>
                    </td>
                    <td className="mono" style={{fontSize:12, color:"var(--muted)"}}>
                      {p.lead}
                    </td>
                    {isPI && (
                      <td style={{width:90, textAlign:"right"}}>
                        <button
                          type="button"
                          disabled={busyDecom === p.name}
                          onClick={() => unarchiveProj(p.name)}
                          title="Bring this project back to active. No files are touched."
                          style={{
                            background:"transparent", border:"1px solid var(--rule-strong)",
                            borderRadius:2, padding:"1px 6px", cursor:"pointer",
                            fontSize:11, color:"var(--green)", fontFamily:"var(--mono)",
                          }}>
                          {busyDecom === p.name ? "…" : "unarchive"}
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
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

function AddMemberModal({ onClose }) {
  const [handle, setHandle] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState("postdoc");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const submit = async (e) => {
    e.preventDefault();
    if (!handle.trim() || !fullName.trim()) {
      setErr("handle and full name are required"); return;
    }
    setBusy(true); setErr(null);
    try {
      await postMemberAdd({
        handle: handle.trim().replace(/^@/, ""),
        full_name: fullName.trim(),
        role,
      });
      if (typeof window.__wigamigFetchData === "function") {
        await window.__wigamigFetchData(window.DATA.persona);
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
        borderRadius:2, padding:18, width:"min(480px, 92vw)",
        display:"flex", flexDirection:"column", gap:8,
      }}>
        <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:18, color:"var(--purple-deep)"}}>
          Add member to lab
        </h2>
        <p className="muted" style={{fontSize:12, margin:0}}>
          Creates <code>&lt;lab-mgmt&gt;/members/&lt;handle&gt;.md</code>. The new member will need to
          push their own ORCID / contact info via the dashboard.
        </p>
        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase", marginTop:6}}>handle (Western username, no @)</label>
        <input value={handle} onChange={e => setHandle(e.target.value)} placeholder="e.g. jdoe123"
               style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2, fontFamily:"var(--mono)"}}/>
        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase"}}>full name</label>
        <input value={fullName} onChange={e => setFullName(e.target.value)} placeholder="Jane Doe"
               style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2}}/>
        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase"}}>role</label>
        <select value={role} onChange={e => setRole(e.target.value)}
                style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2, fontFamily:"var(--mono)"}}>
          <option value="postdoc">postdoc</option>
          <option value="student">student</option>
          <option value="research_assistant">research_assistant</option>
          <option value="staff">staff</option>
          <option value="collaborator">collaborator</option>
        </select>
        {err && <div style={{color:"var(--red)", fontSize:12}}>{err}</div>}
        <div className="row" style={{justifyContent:"flex-end", gap:6, marginTop:6}}>
          <button type="button" className="btn sm ghost" onClick={onClose}>cancel</button>
          <button type="submit" className="btn sm primary" disabled={busy}>
            {busy ? "…" : "add member"}
          </button>
        </div>
      </form>
    </div>
  );
}

function LabMembersPanel({ peers, span="c-6" }) {
  const tcpsTone = { ok:"green", expiring:"amber", missing:"red" };
  const persona = window.DATA.persona || "member";
  const isPI = persona === "pi";
  const [showAdd, setShowAdd] = useState(false);
  const [busyHandle, setBusyHandle] = useState(null);

  const refresh = async () => {
    if (typeof window.__wigamigFetchData === "function") {
      try { await window.__wigamigFetchData(window.DATA.persona); } catch (_) {}
    }
  };
  const onToggle = async (peer) => {
    const action = peer.status === "active" ? "deactivate" : "activate";
    if (action === "deactivate" && !window.confirm(
      `Deactivate @${peer.handle}?\n\n` +
      "wigamig will:\n" +
      "  • flip the member's status to inactive in members/" + peer.handle + ".md\n" +
      "  • write a decommission report listing the member's project\n" +
      "    memberships, age key, and slack pointer for review\n\n" +
      "wigamig will NOT remove them from any project MEMBERS file, rotate\n" +
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
            {isPI
              ? `${activeCount} active${inactiveCount ? " · " + inactiveCount + " inactive" : ""}`
              : `${peers.length} shared-project peers`}
          </span>
          {isPI && (
            <button className="btn sm primary" onClick={() => setShowAdd(true)}>＋ add</button>
          )}
        </div>
      </header>
      {showAdd && <AddMemberModal onClose={() => setShowAdd(false)} />}
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
                <span className="mono muted" style={{fontSize:11, marginLeft:6}}>@{p.handle} · {p.role}</span>
              </div>
              <div className="row" style={{gap:6}}>
                {p.status === "inactive" && <Pill tone="red">inactive</Pill>}
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
              {isPI && (
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
              : "No peers in your projects."}
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
      if (typeof window.__wigamigFetchData === "function") {
        try { await window.__wigamigFetchData(window.DATA.persona); } catch (_) {}
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
    if (typeof window.__wigamigFetchData === "function") {
      try { await window.__wigamigFetchData(window.DATA.persona); } catch (_) {}
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
        <option value="opus">opus (4.7)</option>
        <option value="sonnet">sonnet (4.6)</option>
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
            No agents installed. Run <code className="mono">wigamig agent list</code>.
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
async function postJoinRequest(project, justification) {
  const params = new URLSearchParams(window.location.search);
  const userParam = params.get("user");
  const url = "/api/request/join" + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
  const res = await fetch(url, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ project, justification }),
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
  // Slack channel name override. Empty = wigamig default of
  // ``proj-<project>``. The placeholder updates live as the user types
  // the project name so it's obvious what will be created if they
  // leave this blank. Validation is server-side (normalize_channel_name).
  const [slackChannelName, setSlackChannelName] = useState("");
  // Item 3 (R3): install target. Populated from /api/hosts on mount.
  // Defaults to "local"; selecting a remote host (e.g. lab-server) makes
  // approval scaffold the project on that machine over SSH.
  const [hosts, setHosts] = useState([{ name: "local", kind: "local", is_remote: false, description: "this laptop" }]);
  const [host, setHost] = useState("local");
  useEffect(() => {
    let cancelled = false;
    fetch("/api/hosts", { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(r => r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status)))
      .then(j => { if (!cancelled && Array.isArray(j.hosts) && j.hosts.length) setHosts(j.hosts); })
      .catch(err => console.warn("[wigamig] /api/hosts failed; defaulting to local", err));
    return () => { cancelled = true; };
  }, []);

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

  const submit = async (e) => {
    e.preventDefault();
    if (!name.trim()) { setErr("project name is required"); return; }
    if (selectedMembers.length === 0) { setErr("add at least one member"); return; }
    setBusy(true); setErr(null);
    try {
      await postCreateProjectRequest({
        project: name.trim(),
        proposed_members: selectedMembers,
        sensitivity,
        justification: justification.trim(),
        repo_kind: repoKind,
        local_repo_root: repoKind === "local" ? (localRepoRoot.trim() || null) : null,
        host,
        slack_channel_name: slackChannelName.trim() || null,
      });
      if (typeof window.__wigamigFetchData === "function") {
        await window.__wigamigFetchData(window.DATA.persona);
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
          PI approval required. On approval, wigamig scaffolds the project repo
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

        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase"}}>sensitivity</label>
        <select value={sensitivity} onChange={e => setSensitivity(e.target.value)}
                style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2, fontFamily:"var(--mono)"}}>
          <option value="standard">standard</option>
          <option value="restricted">restricted</option>
          <option value="clinical">clinical</option>
        </select>

        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase"}}>install on host</label>
        <select value={host} onChange={e => setHost(e.target.value)}
                style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2, fontFamily:"var(--mono)"}}>
          {hosts.map(h => (
            <option key={h.name} value={h.name}>
              {h.name}{h.is_remote ? " (" + (h.ssh_host || h.name) + ")" : " — this laptop"}
            </option>
          ))}
        </select>
        {host !== "local" && (
          <div className="muted" style={{fontSize:11, marginTop:-4}}>
            On approval, wigamig will SSH into <code>{host}</code> and
            scaffold the project at
            <code> {(hosts.find(h => h.name === host) || {}).project_root || "~/repos"}/{name.trim() || "<project>"}</code>.
            A local placeholder dir is created at <code>~/repos/{name.trim() || "<project>"}/</code>
            so the dashboard can render the project (working tree lives on the remote host).
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
    if (typeof window.__wigamigFetchData === "function") {
      try { await window.__wigamigFetchData(window.DATA.persona); } catch (_) {}
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

function RequestStatusRow({ req }) {
  const tone =
    req.state === "approved" ? "green" :
    req.state === "declined" ? "red"   : "amber";
  return (
    <div style={{padding:"7px 14px", borderBottom:"1px solid var(--rule)"}}>
      <div style={{display:"flex", justifyContent:"space-between", alignItems:"baseline"}}>
        <span className="mono" style={{fontSize:12}}>
          #{req.id} · {req.project}
        </span>
        <Pill tone={tone}>{req.state}</Pill>
      </div>
      <div className="mono muted" style={{fontSize:10, marginTop:2}}>
        filed {req.created_at || "—"}
        {req.resolved_at && <span> · resolved {req.resolved_at} by {req.resolved_by}</span>}
      </div>
      {req.state === "declined" && req.decline_reason && (
        <div style={{fontSize:11, color:"var(--red)", marginTop:3}}>
          {req.decline_reason}
        </div>
      )}
    </div>
  );
}

function NewJoinRequestButton() {
  const [busy, setBusy] = useState(false);
  const [err, setErr]   = useState(null);
  const onClick = async () => {
    const project = window.prompt("Project name to request joining (e.g. dcis_sc_tutorial):");
    if (!project || !project.trim()) return;
    const justification = window.prompt(
      "Why do you want to join this project? (visible to the PI)"
    ) || "";
    setBusy(true); setErr(null);
    try {
      await postJoinRequest(project.trim(), justification.trim());
      if (typeof window.__wigamigFetchData === "function") {
        await window.__wigamigFetchData(window.DATA.persona);
      }
    } catch (ex) {
      setErr(String(ex.message || ex));
      alert("Request failed: " + (ex.message || ex));
    } finally {
      setBusy(false);
    }
  };
  return (
    <button className="btn sm" disabled={busy} onClick={onClick}>
      {busy ? "…" : "＋ join project"}
    </button>
  );
}

function RequestsPanel({ pending, mine, span="c-6" }) {
  const persona = window.DATA.persona || "member";
  const isPI    = persona === "pi";
  const showQueue = isPI ? (pending || []) : [];
  // Member view: show only project-join (not project-create) requests in
  // the Requests panel. project-create requests show up in the PI's queue
  // and on the Projects panel; members track those via the Projects panel
  // header chip.
  const isJoin = (r) => r.kind !== "project-create";
  const filteredQueue = showQueue.filter(isJoin);
  const filteredMine  = (mine || []).filter(isJoin);

  const headerLabel = isPI
    ? `${filteredQueue.length} pending`
    : `${filteredMine.filter(r => r.state === "pending").length} pending · ${
        filteredMine.filter(r => r.state !== "pending").length} resolved`;

  return (
    <div className={"panel "+span}>
      <header>
        <h2>Requests · project join</h2>
        <div className="row" style={{gap:6}}>
          <span className="meta">{headerLabel}</span>
          <NewJoinRequestButton />
        </div>
      </header>
      <div className="body" style={{padding:"6px 0"}}>
        {isPI && filteredQueue.length === 0 && (
          <div className="muted" style={{padding:"14px", fontSize:13}}>
            No pending requests. Members will appear here when they ask to join a project.
          </div>
        )}
        {isPI && filteredQueue.map(r => (
          <RequestActionRow key={r.id} req={r} isPI={true} />
        ))}
        {!isPI && filteredMine.length === 0 && (
          <div className="muted" style={{padding:"14px", fontSize:13}}>
            You haven't filed any join requests. Click <code>＋ join project</code> above.
          </div>
        )}
        {!isPI && filteredMine.map(r => (
          <RequestStatusRow key={r.id} req={r} />
        ))}
      </div>
    </div>
  );
}

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
      if (typeof window.__wigamigFetchData === "function") {
        await window.__wigamigFetchData(window.DATA.persona);
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

function SeaCatalogPanel({ entries, span="c-12" }) {
  const persona = window.DATA.persona || "member";
  const isPI = persona === "pi";
  const [editing, setEditing] = useState(null);  // null | {} (new) | entry (edit)
  const [busy, setBusy] = useState(null);
  const list = entries || [];

  const refresh = async () => {
    if (typeof window.__wigamigFetchData === "function") {
      try { await window.__wigamigFetchData(window.DATA.persona); } catch (_) {}
    }
  };
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

  return (
    <div className={"panel "+span}>
      <header>
        <h2>SEAs we offer</h2>
        <div className="row" style={{gap:8}}>
          <span className="meta">
            {list.length} entr{list.length === 1 ? "y" : "ies"} ·
            {" "}{list.filter(e => e.accepting).length} accepting
          </span>
          {isPI && (
            <button className="btn sm primary" onClick={() => setEditing({})}>
              ＋ add
            </button>
          )}
        </div>
      </header>
      {editing !== null && (
        <CatalogEntryForm
          entry={Object.keys(editing).length === 0 ? null : editing}
          onClose={() => setEditing(null)}
        />
      )}
      <div className="body" style={{padding:0}}>
        {list.length === 0 && (
          <div className="muted" style={{padding:"14px", fontSize:13}}>
            No SEAs offered yet.{" "}
            {isPI && <span>Click <code>＋ add</code> to publish the lab's first one.</span>}
          </div>
        )}
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
      </div>
    </div>
  );
}

/* ───────── Collaborations (item #9: PI proposes; registrar approves) ─────────
   PIs use this panel to request a new cross-lab collaboration; the
   registrar's dashboard has the matching approve/decline UI. Members
   see only collabs they're a party to (read-only). The registry of
   live collaborations isn't shown here — only the request lifecycle —
   because the day-to-day work of a collab lives in the collab's own
   projects/oracle, which surface elsewhere. */

function CollaborationsPanel({ span="c-12" }) {
  const persona = window.DATA.persona || "member";
  const isPI = persona === "pi";
  const m = window.DATA.member || {};
  const myHandle = (m.handle || "").toLowerCase();
  const [rows, setRows] = useState(null);     // null = loading; [] = empty
  const [showPropose, setShowPropose] = useState(false);

  const refresh = async () => {
    try {
      const params = new URLSearchParams(window.location.search);
      const userParam = params.get("user") || myHandle;
      const r = await fetch(
        "/api/collaboration/requests?user=" + encodeURIComponent(userParam),
        { headers: { Accept: "application/json" } },
      );
      const j = await r.json();
      setRows(j.requests || []);
    } catch (_) { setRows([]); }
  };
  useEffect(() => { refresh(); }, []);

  const pending  = (rows || []).filter(r => r.state === "pending");
  const recent   = (rows || []).filter(r => r.state !== "pending").slice(0, 5);

  return (
    <div className={"panel " + span}>
      <header>
        <h2>Collaborations</h2>
        <div className="row" style={{gap:6}}>
          <span className="meta">
            {pending.length} pending
            {recent.length > 0 && <span> · {recent.length} recent</span>}
          </span>
          {isPI && (
            <button className="btn sm" onClick={() => setShowPropose(true)}>
              ＋ propose collaboration
            </button>
          )}
        </div>
      </header>
      {showPropose && (
        <ProposeCollaborationModal onClose={() => setShowPropose(false)} onFiled={refresh} />
      )}
      <div className="body" style={{padding:0}}>
        {rows === null ? (
          <div style={{padding:"14px 18px", color:"var(--muted)", fontSize:12}}>loading…</div>
        ) : rows.length === 0 ? (
          <div style={{padding:"14px 18px", color:"var(--muted)", fontSize:12}}>
            No collaboration requests yet.
            {isPI && " Use “propose collaboration” to file the first one."}
          </div>
        ) : (
          <table className="dt">
            <thead><tr>
              <th>name</th>
              <th style={{width:100}}>state</th>
              <th>groups</th>
              <th>PIs</th>
              <th style={{width:110}}>filed</th>
            </tr></thead>
            <tbody>
              {pending.concat(recent).map(r => (
                <tr key={r.id}>
                  <td>
                    <strong>{r.proposed_name}</strong>
                    <div className="mono muted" style={{fontSize:11}}>
                      #{r.id} · by {r.requester}
                    </div>
                  </td>
                  <td>
                    <Pill tone={
                      r.state === "approved" ? "green"
                      : r.state === "declined" ? "red"
                      : ""
                    }>{r.state}</Pill>
                  </td>
                  <td className="mono" style={{fontSize:12}}>
                    {(r.proposed_groups || []).join(" + ")}
                  </td>
                  <td className="mono" style={{fontSize:12}}>
                    {(r.proposed_pis || []).join(", ")}
                  </td>
                  <td className="muted" style={{fontSize:11}}>
                    {r.created_at ? r.created_at.slice(0,10) : ""}
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

function ProposeCollaborationModal({ onClose, onFiled }) {
  const [form, setForm] = useState({
    proposed_name: "",
    partner_groups: "",     // comma-separated; viewer's lab pre-appended on submit
    partner_pis: "",        // comma-separated handles
    justification: "",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const m = window.DATA.member || {};
  const myLab = (window.DATA.lab_settings || {}).name || "";

  const update = (k) => (e) => setForm(p => ({...p, [k]: e.target.value}));

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      const partnerGroups = form.partner_groups
        .split(",").map(s => s.trim().toLowerCase()).filter(Boolean);
      const partnerPis = form.partner_pis
        .split(",").map(s => s.trim()).filter(Boolean)
        .map(s => s.startsWith("@") ? s : "@" + s);
      // Include the viewer's own lab + PI handle so the registrar sees the
      // full group/PI set. The viewer is always a partner — they're the proposer.
      const myGroupSlug = String(myLab).toLowerCase().replace(/\s+lab$/i, "");
      const groups = Array.from(new Set([myGroupSlug, ...partnerGroups])).filter(Boolean);
      const pis = Array.from(new Set(["@" + (m.handle || ""), ...partnerPis])).filter(s => s !== "@");

      const params = new URLSearchParams(window.location.search);
      const userParam = params.get("user") || m.handle;
      const r = await fetch("/api/collaboration/propose?user=" + encodeURIComponent(userParam), {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          proposed_name: form.proposed_name.trim().toLowerCase(),
          proposed_groups: groups,
          proposed_pis: pis,
          proposed_member_subset: {},  // registrar can fill via edit flow
          justification: form.justification.trim(),
        }),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail || ("HTTP " + r.status));
      if (onFiled) await onFiled();
      onClose();
    } catch (ex) {
      setErr(String(ex.message || ex));
    } finally { setBusy(false); }
  };

  const lbl = { fontFamily:"var(--mono)", fontSize:10, letterSpacing:1,
                textTransform:"uppercase", color:"var(--muted)", marginTop:8, marginBottom:2 };
  const inp = { padding:"5px 8px", border:"1px solid var(--rule-strong)", borderRadius:2,
                fontFamily:"var(--mono)", fontSize:12, width:"100%", boxSizing:"border-box" };

  return (
    <div onClick={onClose} style={{
      position:"fixed", inset:0, background:"rgba(32,20,54,0.55)",
      display:"flex", alignItems:"flex-start", justifyContent:"center",
      zIndex:200, padding:"40px 20px", overflowY:"auto",
    }}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} style={{
        background:"var(--card)", border:"1px solid var(--rule-strong)",
        borderRadius:2, padding:18, width:"min(560px, 96vw)",
      }}>
        <div className="row" style={{justifyContent:"space-between", alignItems:"baseline"}}>
          <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:18, color:"var(--purple-deep)"}}>
            Propose a collaboration
          </h2>
          <button type="button" className="btn sm ghost" onClick={onClose}>✕ close</button>
        </div>
        <p className="muted" style={{fontSize:12, margin:"4px 0 10px"}}>
          Files a request to the registrar. Your lab is included automatically;
          list the partner labs + their PIs. The registrar can adjust the
          member subset before approving.
        </p>

        <div style={lbl}>short ID (snake_case)</div>
        <input style={inp} value={form.proposed_name}
               onChange={update("proposed_name")}
               placeholder="e.g. dcis_imaging" required />

        <div style={lbl}>partner lab IDs (comma-separated)</div>
        <input style={inp} value={form.partner_groups}
               onChange={update("partner_groups")}
               placeholder="e.g. core_lead, imaging_core" required />
        <div style={{fontSize:11, color:"var(--muted)", marginTop:2}}>
          Your own lab (<code>{myLab}</code>) is added automatically.
        </div>

        <div style={lbl}>partner PIs (comma-separated handles)</div>
        <input style={inp} value={form.partner_pis}
               onChange={update("partner_pis")}
               placeholder="e.g. @core_lead, @dlee" required />

        <div style={lbl}>justification (optional)</div>
        <textarea style={{...inp, minHeight:60, resize:"vertical"}}
                  value={form.justification}
                  onChange={update("justification")}
                  placeholder="What is the collaboration for?" />

        <div className="row" style={{justifyContent:"flex-end", gap:6, marginTop:14, alignItems:"baseline"}}>
          {err && <span style={{color:"var(--red)", fontSize:11, marginRight:"auto"}}>{err}</span>}
          <button type="button" className="btn sm ghost" onClick={onClose}>cancel</button>
          <button type="submit" className="btn sm primary" disabled={busy}>
            {busy ? "…" : "file request"}
          </button>
        </div>
      </form>
    </div>
  );
}

/* ───────── DecommissionsPanel — browse past soft-deletes ─────────
   The dashboard's "where did X go?" panel. Lists every decommission
   report on this machine, grouped by entity kind. Reports are local
   to the machine (per ~/.wigamig/decommissions/) — there's no
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
              Stored at <code>~/.wigamig/decommissions/</code>.
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
          ~/.wigamig/decommissions/{report.file}
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
    if (typeof window.__wigamigFetchData === "function") {
      try { await window.__wigamigFetchData(window.DATA.persona); } catch (_) {}
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
    if (typeof window.__wigamigFetchData === "function") {
      try { await window.__wigamigFetchData(window.DATA.persona); } catch (_) {}
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
  return (
    <div className={"panel "+span}>
      <header>
        <h2>Oracle · personal</h2>
        <span className="meta">{block.entry_count} entries</span>
      </header>
      <div className="muted" style={{padding:"2px 14px 6px",
           fontSize:11, borderBottom:"1px solid var(--rule)"}}>
        <code className="mono">{block.folder}</code>
      </div>
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
            <code className="mono">wigamig publish &lt;path&gt; --to oracle</code>.
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
      if (typeof window.__wigamigFetchData === "function") {
        try { await window.__wigamigFetchData(window.DATA.persona); } catch (_) {}
      }
      setTimeout(() => setMsg(null), 2200);
    } catch (ex) {
      setMsg(String(ex.message || ex));
      console.warn("[wigamig] notebook edit failed", ex);
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
      if (typeof window.__wigamigFetchData === "function") {
        try { await window.__wigamigFetchData(window.DATA.persona); } catch (_) {}
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
      if (typeof window.__wigamigFetchData === "function") {
        try { await window.__wigamigFetchData(window.DATA.persona); } catch (_) {}
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
      const r = await fetch("/api/hosts/" + encodeURIComponent(name), { method: "DELETE" });
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
          Saved to <code>~/.wigamig/hosts.yaml</code>.
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
                    {h.name !== "local" && (
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
            <li>Run <code>bash scripts/install_remote.sh &lt;name&gt;</code> from the wigamig repo to install <code>uv</code> + <code>wigamig</code> on the host.</li>
            <li>Click <strong>test</strong> above — the four probes should all be ✓ or warn.</li>
            <li>Open <strong>New Project</strong> and pick the host from the dropdown.</li>
          </ol>
        </div>
      </div>
    </div>
  );
}

function HostAddForm({ onCancel, onAdded }) {
  const [form, setForm] = useState({
    name: "lab-server", ssh_host: "lab-server", remote_user: "",
    project_root: "~/repos", wigamig_base: "~/wigamig",
    vault_root: "~/Obsidian", description: "",
    scan_dirs_text: "",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr]   = useState(null);
  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    if (!form.name.trim() || !form.ssh_host.trim()) {
      setErr("name and ssh_host required"); return;
    }
    setBusy(true); setErr(null);
    try {
      const { scan_dirs_text, ...rest } = form;
      const scan_dirs = scan_dirs_text
        .split("\n").map(s => s.trim()).filter(Boolean);
      const r = await fetch("/api/hosts", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ ...rest, scan_dirs }),
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
        <strong style={{fontFamily:"var(--serif)"}}>Register SSH host</strong>
        <button type="button" className="btn sm ghost" onClick={onCancel}>cancel</button>
      </div>
      <div className="row" style={{gap:10, marginTop:6}}>
        <div style={{flex:1}}>
          <div style={lbl}>name (short id)</div>
          <input style={inp} value={form.name} onChange={set("name")} />
        </div>
        <div style={{flex:2}}>
          <div style={lbl}>ssh_host (alias in ~/.ssh/config or full hostname)</div>
          <input style={inp} value={form.ssh_host} onChange={set("ssh_host")} />
        </div>
      </div>
      <div className="row" style={{gap:10, marginTop:4}}>
        <div style={{flex:1}}>
          <div style={lbl}>remote_user (netname on host)</div>
          <input style={inp} value={form.remote_user} onChange={set("remote_user")}
                 placeholder="the_pi" />
        </div>
        <div style={{flex:1}}>
          <div style={lbl}>project_root</div>
          <input style={inp} value={form.project_root} onChange={set("project_root")} />
        </div>
      </div>
      <div className="row" style={{gap:10, marginTop:4}}>
        <div style={{flex:1}}>
          <div style={lbl}>wigamig_base (raw/ + refined/ + lab_notebooks/ live here; working clones go to ~/repos/)</div>
          <input style={inp} value={form.wigamig_base} onChange={set("wigamig_base")} />
        </div>
        <div style={{flex:1}}>
          <div style={lbl}>obsidian vault root (separate)</div>
          <input style={inp} value={form.vault_root} onChange={set("vault_root")} />
        </div>
      </div>
      <div style={lbl}>description (free text)</div>
      <input style={inp} value={form.description} onChange={set("description")} />
      <div style={lbl}>
        scan dirs (one per line; absolute paths used verbatim, others under <code>$HOME</code>;
        leave blank for default <code>~/repo</code> + <code>~/repos</code>)
      </div>
      <textarea style={{...inp, fontFamily:"var(--mono)", minHeight:54, resize:"vertical"}}
                value={form.scan_dirs_text} onChange={set("scan_dirs_text")}
                placeholder={"repos\nwork/clones\n/srv/projects"} />
      <div className="row" style={{justifyContent:"flex-end", gap:6, marginTop:10, alignItems:"baseline"}}>
        {err && <span style={{color:"var(--red)", fontSize:11, marginRight:"auto"}}>{err}</span>}
        <button type="submit" className="btn sm primary" disabled={busy}>
          {busy ? "…" : "register"}
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

   Storage: the current machine's settings live in ~/.wigamig/machine.yaml
   (loaded into window.DATA.machine_settings). Remote hosts live in
   ~/.wigamig/hosts.yaml and are fetched from /api/hosts on mount. */

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
  const [editingScan, setEditingScan] = useState(false);
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
          {onRemove && (
            <button type="button" className="btn sm" onClick={onRemove}
                    style={{color:"var(--red)"}}>remove</button>
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
      <div style={{marginTop:8, fontSize:12, lineHeight:1.55}}>
        <div><span style={labelStyle}>wigamig_base</span><code className="mono">{wb || "—"}</code></div>
        <div><span style={labelStyle}>raw</span><code className="mono">{_joinUnder(wb, "raw")}</code></div>
        <div><span style={labelStyle}>refined</span><code className="mono">{_joinUnder(wb, "refined")}</code></div>
        <div><span style={labelStyle}>lab_notebooks</span><code className="mono">{_joinUnder(wb, "lab_notebooks")}</code></div>
        {(machine.obsidian_vault_path || machine.obsidian_vault_name) && (
          <div style={{marginTop:4, paddingTop:4, borderTop:"1px dashed var(--rule)"}}>
            <span style={labelStyle}>obsidian vault</span>
            <code className="mono">
              {machine.obsidian_vault_path || machine.obsidian_vault_name}
            </code>
            <div style={{fontSize:10.5, color:"var(--muted)", marginLeft:120, marginTop:2}}>
              not under wigamig_base — typically in iCloud Drive
            </div>
          </div>
        )}
        {/* scan_dirs: where the Repo Inventory looks for git clones on
            this host. Empty = defaults (~/repo + ~/repos). Editable for
            any host whose parent passed onScanDirsSaved. */}
        <div style={{marginTop:4, paddingTop:4, borderTop:"1px dashed var(--rule)"}}>
          <div className="row" style={{alignItems:"baseline", gap:6}}>
            <span style={labelStyle}>scan dirs</span>
            <code className="mono" style={{flex:1}}>
              {scanDirs.length === 0
                ? <span className="muted">default (~/repo + ~/repos)</span>
                : scanDirs.join(", ")}
            </code>
            {onScanDirsSaved && !editingScan && (
              <button type="button" className="btn sm ghost"
                      onClick={() => setEditingScan(true)}>edit</button>
            )}
          </div>
          {editingScan && (
            <ScanDirsEditor
              hostName={machine.name}
              initial={scanDirs}
              onCancel={() => setEditingScan(false)}
              onSaved={async () => {
                setEditingScan(false);
                await onScanDirsSaved();
              }}
            />
          )}
        </div>
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
      setProbes(body.probes || []);
      setOverall(body.overall || "ok");
      setMsg("saved");
      if (typeof window.__wigamigFetchData === "function") {
        try { await window.__wigamigFetchData(window.DATA.persona); } catch (_) {}
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
        Saved to <code>~/.wigamig/machine.yaml</code>.
      </p>

      <div style={labelStyle}>wigamig_base (root for raw/refined/lab_notebooks; working clones go to ~/repos/)</div>
      <input style={inputStyle} value={form.wigamig_base}
             onChange={update("wigamig_base")} placeholder="~/wigamig" />

      <div style={labelStyle}>raw</div>
      <div style={derivedStyle}>{_joinUnder(form.wigamig_base, "raw")}</div>
      <div style={labelStyle}>refined</div>
      <div style={derivedStyle}>{_joinUnder(form.wigamig_base, "refined")}</div>
      <div style={labelStyle}>lab_notebooks</div>
      <div style={derivedStyle}>{_joinUnder(form.wigamig_base, "lab_notebooks")}</div>

      <div style={{borderTop:"1px solid var(--rule)", marginTop:10, paddingTop:6}}>
        <div style={labelStyle}>obsidian vault path (full)</div>
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
      const r = await fetch("/api/hosts/" + encodeURIComponent(name), { method: "DELETE" });
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
          in <code>~/.wigamig/machine.yaml</code> and <code>~/.wigamig/hosts.yaml</code>.
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
function MachinesPanel({ span = "c-5" }) {
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
      const r = await fetch("/api/hosts/" + encodeURIComponent(name), { method: "DELETE" });
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
          <div style={{color:"var(--red)", fontSize:12, marginBottom:8}}>
            load failed: {loadErr}
          </div>
        )}
        {remoteCards.map(m => (
          <MachineCard key={m.name} machine={m} isCurrent={false}
                       onRemove={() => removeHost(m.name)}
                       onScanDirsSaved={refreshHosts} />
        ))}
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
      if (typeof window.__wigamigFetchData === "function") {
        try { await window.__wigamigFetchData(window.DATA.persona); } catch (_) {}
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
    "local-bare": "target = absolute server-side dir (e.g. /data/lab_vm/wigamig/repos)",
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
              <div style={labelStyle}>label (optional)</div>
              <input style={inputStyle} value={p.label || ""}
                     placeholder="GitHub (hallettmiket)"
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

function LabSettingsModal({ onClose }) {
  const ls = window.DATA.lab_settings || {};
  const [form, setForm] = useState({
    display_name:      ls.display_name      || "",
    website:           ls.website           || "",
    lab_base:          ls.lab_base          || "",
    github_org:        ls.github_org        || "hallettmiket",
    git_repos_subpath: ls.git_repos_subpath || "repos",
    admins:            (ls.admins || []).join(", "),
    // Phase 2: editable list of git providers. Seed from server-side
    // value; on save we send the full list back, so the user can
    // add/edit/remove without coordinating with the rest of the form.
    git_providers:     ls.git_providers || [],
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
        lab_base:          form.lab_base,
        github_org:        form.github_org,
        git_repos_subpath: form.git_repos_subpath,
        admins:            form.admins.split(",").map(s => s.trim()).filter(Boolean),
        git_providers:     form.git_providers,
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
      if (typeof window.__wigamigFetchData === "function") {
        try { await window.__wigamigFetchData(window.DATA.persona); } catch (_) {}
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
  const derivedStyle = {
    padding:"5px 8px", border:"1px dashed var(--rule)",
    borderRadius:2, fontFamily:"var(--mono)", fontSize:12,
    background:"var(--paper-2)", color:"var(--ink-2)",
  };
  const sectionHeader = {
    margin:0, fontFamily:"var(--mono)", fontSize:10, letterSpacing:1.5,
    textTransform:"uppercase", color:"var(--purple-deep)",
  };
  const sectionStyle = {
    borderTop:"1px solid var(--rule)", paddingTop:10, marginTop:6,
  };

  const subpath = (form.git_repos_subpath || "repos").replace(/^\/+|\/+$/g, "");
  const githubOrg = (form.github_org || "hallettmiket").trim();
  const labMgmtUrl = githubOrg ? `https://github.com/${githubOrg}/lab_mgmt` : "";

  return (
    <div onClick={onClose} style={{
      position:"fixed", inset:0, background:"rgba(32,20,54,0.55)",
      display:"flex", alignItems:"flex-start", justifyContent:"center",
      zIndex:200, padding:"40px 20px", overflowY:"auto",
    }}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} style={{
        background:"var(--card)", border:"1px solid var(--rule-strong)",
        borderRadius:2, padding:18, width:"min(680px, 96vw)",
        display:"flex", flexDirection:"column", gap:4,
      }}>
        <div className="row" style={{justifyContent:"space-between", alignItems:"baseline"}}>
          <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:20, color:"var(--purple-deep)"}}>
            Lab settings
          </h2>
          <button type="button" className="btn sm ghost" onClick={onClose}>✕ close</button>
        </div>
        <p className="muted" style={{fontSize:12, margin:"4px 0 8px"}}>
          Lab-wide parameters. Edits save to <code>lab_mgmt/lab.md</code> on
          this machine; commit + push to GitHub afterwards. Only the PI and
          designated admins can save changes.
        </p>

        {/* Identity */}
        <div style={sectionStyle}>
          <h4 style={sectionHeader}>Identity</h4>
          <div className="row" style={{flexWrap:"wrap", gap:14, marginTop:6, fontSize:13}}>
            <div><span className="muted">lab id</span> <code className="mono">{ls.name}</code></div>
            <div><span className="muted">PI</span> <code className="mono">{ls.pi_handle}</code></div>
          </div>
          <div style={labelStyle}>display name</div>
          <input style={inputStyle} value={form.display_name} onChange={update("display_name")}
                 placeholder="e.g. Hallett Lab" />
          <div style={labelStyle}>lab website</div>
          <input style={inputStyle} value={form.website} onChange={update("website")}
                 placeholder="https://mikehallett.science" />
        </div>

        {/* Server storage */}
        <div style={sectionStyle}>
          <h4 style={sectionHeader}>Server storage</h4>
          <div style={labelStyle}>lab_base (host:/path to the wigamig umbrella)</div>
          <input style={inputStyle} value={form.lab_base} onChange={update("lab_base")}
                 placeholder="lab-server.example.edu:/data/lab_vm/wigamig" />
          <div style={{fontSize:11, color:"var(--muted)", marginTop:4, lineHeight:1.5}}>
            All lab data lives under <code>lab_base/</code>. Projects are
            subfolders of <code>raw/</code> and <code>refined/</code>; users
            are subfolders of <code>notebooks/</code> and <code>lab_oracle/</code>.
          </div>

          <div style={labelStyle}>Server raw data</div>
          <div style={derivedStyle}>{_underLabBase(form.lab_base, "raw")}</div>
          <div style={labelStyle}>Server refined data</div>
          <div style={derivedStyle}>{_underLabBase(form.lab_base, "refined")}</div>
          <div style={labelStyle}>Server lab notebooks</div>
          <div style={derivedStyle}>{_underLabBase(form.lab_base, "notebooks")}</div>
          <div style={labelStyle}>Server lab oracle</div>
          <div style={derivedStyle}>{_underLabBase(form.lab_base, "lab_oracle")}</div>

          <MasterFoldersPanel labBase={form.lab_base} />
        </div>

        {/* Git */}
        <div style={sectionStyle}>
          <h4 style={sectionHeader}>Git providers</h4>
          <div style={{fontSize:11, color:"var(--muted)", marginTop:3, marginBottom:6, lineHeight:1.5}}>
            The menu of git origin servers this lab supports. Each project picks
            one; each member registers a username per provider in Member Profile.
            Empty list falls back to a single GitHub entry derived from the
            legacy <code>github_org</code> field below.
          </div>
          <GitProvidersEditor
            value={form.git_providers}
            onChange={(next) => setForm((p) => ({ ...p, git_providers: next }))}
          />

          <div style={{...sectionStyle, paddingTop:8, marginTop:14}}>
            <div style={labelStyle}>Lab GitHub org (legacy fallback)</div>
            <input style={inputStyle} value={form.github_org} onChange={update("github_org")}
                   placeholder="hallettmiket" />
            <div style={{fontSize:11, color:"var(--muted)", marginTop:3}}>
              Used only when <code>git_providers</code> is empty. Keep set for
              backwards-compat with lab.md files that pre-date the providers
              refactor.
              {githubOrg
                ? <> Lab GitHub: <a href={`https://github.com/${githubOrg}`} target="_blank" rel="noopener">https://github.com/{githubOrg}</a></>
                : null}
            </div>

            <div style={labelStyle}>Local bare-repo subpath under lab_base</div>
            <input style={inputStyle} value={form.git_repos_subpath} onChange={update("git_repos_subpath")}
                   placeholder="repos" />
            <div style={{fontSize:11, color:"var(--muted)", marginTop:4, lineHeight:1.5}}>
              Used by the <code>local-bare</code> provider kind (if declared
              above). Default <code>repos</code> resolves to
              <code>{" "}{_underLabBase(form.lab_base, subpath)}</code>.
            </div>
          </div>
        </div>

        {/* Lab parameters source */}
        <div style={sectionStyle}>
          <h4 style={sectionHeader}>Lab parameters source</h4>
          <div style={{fontSize:12, marginTop:6, lineHeight:1.6}}>
            <div>
              <span className="muted" style={{display:"inline-block", width:160}}>GitHub (source of truth)</span>
              {labMgmtUrl
                ? <a href={labMgmtUrl} target="_blank" rel="noopener" className="mono">{labMgmtUrl}</a>
                : <span className="muted">— (set GitHub org above)</span>}
            </div>
            <div>
              <span className="muted" style={{display:"inline-block", width:160}}>Local clone</span>
              <code className="mono">~/repos/lab_mgmt</code>
            </div>
            <div>
              <span className="muted" style={{display:"inline-block", width:160}}>Local cache</span>
              <code className="mono">~/.wigamig/</code>
            </div>
          </div>
          <div style={{fontSize:11, color:"var(--muted)", marginTop:6, lineHeight:1.55}}>
            <code>lab_mgmt</code> is the versioned source of truth (shared via
            GitHub). <code>~/.wigamig/</code> is a per-machine materialised
            view plus machine-local state (this machine's <code>machine.yaml</code>,
            <code> installations/</code>, <code>workspaces/</code>) and is not
            pushed back to GitHub.
          </div>
        </div>

        {/* Admins */}
        <div style={sectionStyle}>
          <h4 style={sectionHeader}>Settings admins</h4>
          <div style={labelStyle}>handles with PI-level settings edit rights (comma-separated)</div>
          <input style={inputStyle} value={form.admins} onChange={update("admins")}
                 placeholder="e.g. jsmith, admin_asst" />
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
        <div className="links">
          <a href="mailto:michael.hallett@example.edu" target="_blank" rel="noopener">Contact</a>
          <a href="https://hallettmiket.github.io" target="_blank" rel="noopener">Join Us</a>
        </div>
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

        {/* Installations: always-visible — open workspace or install from here. */}
        <div className="grid" style={{marginBottom:14}}>
          <InstallationsBox span="c-12" />
        </div>

        {/* Where you work: Projects + Machines (conceptually paired —
            installations live at the intersection of the two). */}
        <div className="grid" style={{marginBottom:14}}>
          <ProjectsPanel projects={D.projects} span="c-7" />
          <MachinesPanel span="c-5" />
        </div>

        {/* Activity feed sits below — context for the action zone. */}
        <div className="grid" style={{marginBottom:14}}>
          <ActivityPanel span="c-12" />
        </div>

        {/* Daily action zone (order: Requests → Receptionist → All SEAs). */}
        <div className="grid" style={{marginBottom:14}}>
          <RequestsPanel
            pending={D.requests_pending}
            mine={D.requests_mine}
            span="c-12"
          />
        </div>

        {persona === "pi" && (
          <div className="grid" style={{marginBottom:14}}>
            <ReceptionistPanel inbound={D.inbound_requests} span="c-12" />
          </div>
        )}

        <div className="grid" style={{marginBottom:14}}>
          <CollaborationsPanel span="c-12" />
        </div>

        <div className="grid" style={{marginBottom:14}}>
          <SeasPanel seas={D.seas} span="c-12" />
        </div>

        <div className="grid" style={{marginBottom:14}}>
          <PersonalOraclePanel data={D.personal_oracle} span="c-3" />
          <NotebookPanel span="c-5" />
          <LabOraclePanel entries={D.oracle_recent} drafts={D.oracle_drafts}
                          labFolder={D.lab_oracle_folder} span="c-4" />
        </div>

        {/* Lab members + inventory: things you check, but not every day. */}
        <div className="grid" style={{marginBottom:14}}>
          <LabMembersPanel peers={D.peers} span="c-6" />
          <InventoryPanel inv={D.inventory} span="c-6" />
        </div>

        {/* Repo inventory: cross-machine + GitHub audit. Cached weekly,
            on-demand refresh. Per-row "Install on <machine>" pre-fills
            the install wizard for repos that exist on GitHub but
            aren't cloned/initialized on a chosen host. Sits below
            Lab Members + Inventory — same "things you check, but not
            every day" tier. */}
        <div className="grid" style={{marginBottom:14}}>
          <RepoInventoryPanel span="c-12" />
        </div>

        {/* SEAs we offer (catalog) - every member sees; PI edits. */}
        <div className="grid" style={{marginBottom:14}}>
          <SeaCatalogPanel entries={D.sea_catalog} span="c-12" />
        </div>

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
