/* Hi-fi app — Command Bridge layout, Western brand applied. */

const { useState, useEffect, useMemo, useReducer } = React;
const D = window.DATA;

/* ───────── shared atoms ───────── */
function Pill({ tone="", children }) { return <span className={"pill "+tone}>{children}</span>; }
function K({ children }) { return <kbd className="kbd">{children}</kbd>; }

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
          {persona === "pi" ? "PI VIEW" : "MEMBER VIEW"}
        </span>
      </div>
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

  const cols = (persona === "pi" ? 2 : 1) + 3; // member? + project + machine + status + launch

  const launchRow = async (inst, i) => {
    setLaunchingIdx(i);
    setRowMsg(m => ({ ...m, [i]: null }));
    try {
      const r = await postWorkspaceLaunch({
        project: inst.project,
        agents:  inst.agents || [],
      });
      setRowMsg(m => ({ ...m, [i]: `opened ${r.agents.length} pane(s)` }));
      setTimeout(() => setRowMsg(m => ({ ...m, [i]: null })), 3000);
    } catch (ex) {
      setRowMsg(m => ({ ...m, [i]: String(ex.message || ex) }));
    } finally {
      setLaunchingIdx(null);
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
                    <td style={{fontSize:12, cursor:"pointer"}}
                        onClick={() => setOpenRow(openRow === i ? null : i)}>
                      {inst.project}
                    </td>
                    <td className="mono" style={{fontSize:11, cursor:"pointer"}}
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
                          <div><span className="muted" style={{display:"inline-block",width:90}}>raw/</span>{inst.raw_path}</div>
                          <div><span className="muted" style={{display:"inline-block",width:90}}>refined/</span>{inst.refined_path}</div>
                          <div><span className="muted" style={{display:"inline-block",width:90}}>notebook/</span>{inst.notebook_path}</div>
                          <div><span className="muted" style={{display:"inline-block",width:90}}>components</span>{(inst.components||[]).join(", ")}</div>
                          <div><span className="muted" style={{display:"inline-block",width:90}}>agents</span>{(inst.agents||[]).join(", ")}</div>
                          {inst.issues?.length > 0 && (
                            <div style={{gridColumn:"span 2", color:"var(--red)", marginTop:4}}>
                              <span style={{display:"inline-block",width:90}}>issues</span>{inst.issues.join("; ")}
                            </div>
                          )}
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
    </div>
  );
}

/* ── InstallModal: 5-step wizard to install Wigamig for a member on a machine ── */
function InstallModal({ initialProject, onClose }) {
  const [step, setStep]                     = useState(1);
  /* step 1 */
  const [who, setWho]                       = useState("@" + ((window.DATA.member || {}).handle || ""));
  const [project, setProject]               = useState(initialProject || window.DATA.projects?.[0]?.name || "");
  /* step 2 */
  const [machineType, setMachineType]       = useState("lab_server");
  const [hostname, setHostname]             = useState("");
  const [username, setUsername]             = useState("");
  // Detected OS account name on the machine running the dashboard.
  // Used to prefill the laptop case — the dashboard runs locally on
  // the user's laptop, so this is exactly the right value.
  const [detectedLocalUser, setDetectedLocalUser] = useState("");
  useEffect(() => {
    fetch("/api/environment/local_user")
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d && d.local_user) setDetectedLocalUser(d.local_user); })
      .catch(() => {});
  }, []);
  // Auto-fill username when switching to laptop, but only if the user
  // hasn't typed anything yet. Don't clobber their input.
  useEffect(() => {
    if (machineType === "laptop" && !username && detectedLocalUser) {
      setUsername(detectedLocalUser);
    }
  }, [machineType, detectedLocalUser]);  // intentionally not on `username`
  /* step 3 */
  const [hasDirectAccess, setHasDirectAccess] = useState(true);
  const [labBase, setLabBase]               = useState("/data/lab_vm");
  const [rawPath, setRawPath]               = useState("/data/lab_vm/raw");
  const [refinedPath, setRefinedPath]       = useState("/data/lab_vm/refined");
  const [notebookPath, setNotebookPath]     = useState("/data/lab_vm/lab-notebook");
  const [sshRemote, setSshRemote]           = useState("");
  const [mountPoint, setMountPoint]         = useState("~/mnt/lab_vm");
  /* step 4 */
  const [infra, setInfra]                   = useState(INFRA_ITEMS.map(x => x.id));
  const [pickedAgents, setPickedAgents]     = useState(() => {
    const all = (window.DATA.agents || []).filter(a => !a.disabled).map(a => a.name);
    const p = window.DATA.persona || "member";
    return p === "pi" ? all : all.filter(n => n !== "receptionist");
  });
  /* ui */
  const [busy, setBusy]                     = useState(false);
  const [err, setErr]                       = useState(null);
  const [done, setDone]                     = useState(false);

  const peers     = window.DATA.peers     || [];
  const projects  = window.DATA.projects  || [];
  const allAgents = (window.DATA.agents   || []).filter(a => !a.disabled);

  const syncPaths = (base) => {
    setLabBase(base);
    setRawPath(base + "/raw");
    setRefinedPath(base + "/refined");
    setNotebookPath(base + "/lab-notebook");
  };

  const toggleInfra  = (id)   => setInfra(f       => f.includes(id)   ? f.filter(x => x !== id)   : [...f, id]);
  const toggleAgent  = (name) => setPickedAgents(a => a.includes(name) ? a.filter(x => x !== name) : [...a, name]);

  const canProceed = () => {
    if (step === 1) return !!project;
    if (step === 2) return (machineType === "laptop" || hostname.trim()) && username.trim();
    if (step === 3) return labBase.trim() && rawPath.trim() && refinedPath.trim() && notebookPath.trim();
    if (step === 4) return infra.length > 0;
    return true;
  };

  const provision = async () => {
    setBusy(true); setErr(null);
    try {
      const res = await fetch("/api/workspace/initialize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          member: who, project, machine_type: machineType,
          hostname: machineType === "lab_server" ? hostname : null,
          username, has_direct_access: hasDirectAccess,
          lab_base: labBase, raw_path: rawPath,
          refined_path: refinedPath, notebook_path: notebookPath,
          ssh_remote: !hasDirectAccess ? sshRemote : null,
          mount_point: !hasDirectAccess ? mountPoint : null,
          infra_components: infra, agents: pickedAgents,
        }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || ("HTTP " + res.status));
      }
      // Force a fresh fetch so the new Installation row shows up below.
      if (typeof window.__wigamigFetchData === "function") {
        try { await window.__wigamigFetchData(window.DATA.persona); } catch (_) {}
      }
      setDone(true);
    } catch (ex) { setErr(String(ex.message || ex)); }
    finally { setBusy(false); }
  };

  const STEP_LABELS = ["Who & What", "Target Machine", "Lab-base Paths", "Infrastructure", "Review"];

  /* shared input styles */
  const INP = { style:{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2,
    fontFamily:"var(--mono)", fontSize:12, width:"100%", boxSizing:"border-box"} };
  const SEL = { style:{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2,
    fontFamily:"var(--mono)", fontSize:12, width:"100%"} };
  const LBL = { style:{fontSize:10.5, letterSpacing:1, textTransform:"uppercase",
    fontFamily:"var(--mono)", color:"var(--muted)", marginBottom:3, display:"block"} };

  const MachineCard = ({ id, label, desc }) => (
    <button type="button" onClick={() => setMachineType(id)} style={{
      flex:1, padding:"10px 12px", border:"1px solid", borderRadius:2,
      textAlign:"left", cursor:"pointer",
      background: machineType === id ? "rgba(79,38,131,0.08)" : "var(--paper-2)",
      borderColor: machineType === id ? "var(--purple)" : "var(--rule-strong)",
    }}>
      <div style={{fontFamily:"var(--mono)", fontSize:12, fontWeight:500,
                   color: machineType === id ? "var(--purple)" : "var(--ink)"}}>
        {label}
      </div>
      <div style={{fontSize:10.5, color:"var(--muted)", marginTop:3}}>{desc}</div>
    </button>
  );

  const AccessCard = ({ id, label, desc }) => (
    <button type="button" onClick={() => setHasDirectAccess(id)} style={{
      flex:1, padding:"10px 12px", border:"1px solid", borderRadius:2,
      textAlign:"left", cursor:"pointer",
      background: hasDirectAccess === id ? "rgba(79,38,131,0.08)" : "var(--paper-2)",
      borderColor: hasDirectAccess === id ? "var(--purple)" : "var(--rule-strong)",
    }}>
      <div style={{fontFamily:"var(--mono)", fontSize:12, fontWeight:500,
                   color: hasDirectAccess === id ? "var(--purple)" : "var(--ink)"}}>
        {label}
      </div>
      <div style={{fontSize:10.5, color:"var(--muted)", marginTop:3}}>{desc}</div>
    </button>
  );

  return (
    <div onClick={onClose} style={{
      position:"fixed", inset:0, background:"rgba(32,20,54,0.55)",
      display:"flex", alignItems:"center", justifyContent:"center", zIndex:100,
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        background:"var(--card)", border:"1px solid var(--rule-strong)",
        borderRadius:2, width:"min(600px, 95vw)",
        display:"flex", flexDirection:"column", maxHeight:"92vh",
      }}>

        {/* header + step tabs */}
        <div style={{background:"var(--paper-2)", borderBottom:"1px solid var(--rule)", padding:"12px 16px 0"}}>
          <div style={{display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:10}}>
            <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:17, color:"var(--purple-deep)"}}>
              Install Wigamig Environment
            </h2>
            <button type="button" onClick={onClose}
                    style={{background:"none", border:0, cursor:"pointer", color:"var(--muted)", fontSize:20, lineHeight:1}}>
              ×
            </button>
          </div>
          <div style={{display:"flex", overflowX:"auto"}}>
            {STEP_LABELS.map((label, i) => {
              const s = i + 1;
              return (
                <div key={s} onClick={() => s < step && setStep(s)} style={{
                  padding:"5px 12px 8px", fontSize:10.5, fontFamily:"var(--mono)",
                  letterSpacing:0.8, textTransform:"uppercase", whiteSpace:"nowrap",
                  borderBottom: s === step ? "2px solid var(--purple)" : "2px solid transparent",
                  color: s === step ? "var(--purple)" : s < step ? "var(--ink-2)" : "var(--muted)",
                  cursor: s < step ? "pointer" : "default",
                }}>
                  {s}. {label}
                </div>
              );
            })}
          </div>
        </div>

        {/* body */}
        <div style={{padding:"16px", overflowY:"auto", flex:1, display:"flex", flexDirection:"column", gap:12}}>
          {done ? (
            <div style={{textAlign:"center", padding:"28px 0"}}>
              <div style={{fontSize:30, marginBottom:8, color:"var(--green)"}}>✓</div>
              <div style={{fontFamily:"var(--serif)", fontSize:16, color:"var(--purple-deep)", marginBottom:6}}>
                Provisioning checklist generated
              </div>
              <p className="muted" style={{fontSize:12, maxWidth:380, margin:"0 auto"}}>
                Share the checklist with <strong>{who}</strong>. Once completed,
                their environment will appear in the Installations panel below.
              </p>
            </div>
          ) : (
            <>
              {/* ── step 1: who & what ── */}
              {step === 1 && (
                <>
                  <p className="muted" style={{fontSize:12, margin:0}}>
                    Which project do you want to install on this machine?
                  </p>
                  <div>
                    <label {...LBL}>Project to install</label>
                    <select value={project} onChange={e => setProject(e.target.value)} style={SEL.style}>
                      {projects.map(p => <option key={p.name} value={p.name}>{p.name}</option>)}
                    </select>
                    <div style={{fontSize:11, color:"var(--muted)", marginTop:3}}>
                      The project repo will be cloned to ~/repos/{project || "…"} on the target machine.
                    </div>
                  </div>
                  <div style={{
                    background:"var(--paper-2)", borderRadius:2, padding:"8px 12px",
                    fontSize:11, color:"var(--ink-2)", borderLeft:"3px solid var(--purple)",
                  }}>
                    Installation provisions: repo clone · Wigamig CC config · agent definitions ·
                    Obsidian vault · lab-base path access. Slack membership assumed.
                  </div>
                </>
              )}

              {/* ── step 2: target machine ── */}
              {step === 2 && (
                <>
                  <p className="muted" style={{fontSize:12, margin:0}}>
                    Which machine will this Wigamig environment run on?
                  </p>
                  <div>
                    <label {...LBL}>Machine type</label>
                    <div style={{display:"flex", gap:8}}>
                      <MachineCard id="lab_server" label="Lab server"
                        desc="e.g. biodatadci — direct or SSH to lab-base; login via username" />
                      <MachineCard id="laptop" label="Laptop / personal machine"
                        desc="SSH key required to reach lab-base; local or SSH-mount storage" />
                    </div>
                  </div>
                  {machineType === "lab_server" && (
                    <div>
                      <label {...LBL}>Hostname</label>
                      <input value={hostname} onChange={e => setHostname(e.target.value)}
                             placeholder="e.g. biodatadci  or  biodatadci.uwo.ca" {...INP} />
                    </div>
                  )}
                  <div>
                    <label {...LBL}>Local OS account on this target machine</label>
                    <input value={username} onChange={e => setUsername(e.target.value)}
                           placeholder={machineType === "laptop"
                             ? (detectedLocalUser || "e.g. mike-laptop")
                             : "e.g. mhallet"} {...INP} />
                    <div style={{fontSize:11, color:"var(--muted)", marginTop:3}}>
                      The OS account you log into the machine with — <strong>not</strong> your
                      Western netname. On a laptop it's what <code>whoami</code> returns
                      ({detectedLocalUser ? <>detected: <code>{detectedLocalUser}</code></> : "auto-detecting…"});
                      on a lab server it usually matches your Western netname but doesn't have to.
                      All lab-base communication uses SSH key auth — no passwords stored.
                    </div>
                  </div>
                </>
              )}

              {/* ── step 3: lab-base paths ── */}
              {step === 3 && (
                <>
                  <p className="muted" style={{fontSize:12, margin:0}}>
                    Where do raw/, refined/, and lab-notebook/ live on{" "}
                    {machineType === "lab_server" ? hostname || "the lab server" : "this laptop"}?
                    {machineType === "laptop" && " Laptops can store data locally or via SSH mount."}
                  </p>
                  {machineType === "laptop" && (
                    <div>
                      <label {...LBL}>Lab-base access on this laptop</label>
                      <div style={{display:"flex", gap:8}}>
                        <AccessCard id={true}  label="Local copy"
                          desc="raw/, refined/, lab-notebook/ sit on the laptop itself" />
                        <AccessCard id={false} label="SSH mount"
                          desc="Access lab-base remotely via sshfs — needs network to lab server" />
                      </div>
                    </div>
                  )}
                  {!hasDirectAccess && machineType === "laptop" && (
                    <>
                      <div>
                        <label {...LBL}>SSH remote (host where lab-base lives)</label>
                        <input value={sshRemote} onChange={e => setSshRemote(e.target.value)}
                               placeholder="e.g. biodatadci.uwo.ca" {...INP} />
                      </div>
                      <div>
                        <label {...LBL}>Local mount point</label>
                        <input value={mountPoint} onChange={e => setMountPoint(e.target.value)}
                               placeholder="~/mnt/lab_vm" {...INP} />
                        <div style={{fontSize:11, color:"var(--muted)", marginTop:3}}>
                          macOS: <code>brew install sshfs</code> then <code>sshfs {sshRemote || "host"}:{labBase} {mountPoint}</code>
                        </div>
                      </div>
                    </>
                  )}
                  <div>
                    <label {...LBL}>
                      Lab-base root{(!hasDirectAccess && machineType === "laptop") ? " (path on remote)" : ""}
                    </label>
                    <input value={labBase} onChange={e => syncPaths(e.target.value)}
                           placeholder="/data/lab_vm" {...INP} />
                    <div style={{fontSize:11, color:"var(--muted)", marginTop:3}}>
                      Editing this auto-fills the paths below.
                    </div>
                  </div>
                  <div style={{display:"grid", gridTemplateColumns:"1fr 1fr", gap:10}}>
                    <div>
                      <label {...LBL}>raw/ path</label>
                      <input value={rawPath} onChange={e => setRawPath(e.target.value)} {...INP} />
                    </div>
                    <div>
                      <label {...LBL}>refined/ path</label>
                      <input value={refinedPath} onChange={e => setRefinedPath(e.target.value)} {...INP} />
                    </div>
                  </div>
                  <div>
                    <label {...LBL}>lab-notebook/ path (Obsidian vault root)</label>
                    <input value={notebookPath} onChange={e => setNotebookPath(e.target.value)} {...INP} />
                  </div>
                </>
              )}

              {/* ── step 4: infrastructure ── */}
              {step === 4 && (
                <>
                  <p className="muted" style={{fontSize:12, margin:0}}>
                    Which software and agents should be installed?
                    Slack is assumed present in the lab workspace.
                  </p>
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
                      {allAgents.map(a => (
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
                  <div style={{
                    background:"var(--paper-2)", borderRadius:2, padding:"8px 12px",
                    fontSize:11, color:"var(--ink-2)", borderLeft:"3px solid var(--tiger)",
                  }}>
                    <strong>Post-install steps:</strong> CC needs a Claude API key in the shell env.
                    Obsidian vault must be created at <code>{notebookPath}</code>.
                    Run <code>gh auth login</code> after GitHub CLI install.
                  </div>
                </>
              )}

              {/* ── step 5: review ── */}
              {step === 5 && (
                <>
                  <p className="muted" style={{fontSize:12, margin:0}}>
                    Review the plan then click <strong>provision</strong> to generate the setup checklist.
                  </p>
                  <table style={{width:"100%", borderCollapse:"collapse", fontSize:12}}>
                    <tbody>
                      {[
                        ["Member",        who],
                        ["Project",       project],
                        ["Machine",       machineType === "lab_server"
                          ? `${username}@${hostname} (lab server)`
                          : `${username} · laptop`],
                        ["Lab-base",      !hasDirectAccess && machineType === "laptop"
                          ? `SSH mount ${sshRemote} → ${mountPoint}`
                          : labBase + " (direct)"],
                        ["raw/",          rawPath],
                        ["refined/",      refinedPath],
                        ["lab-notebook/", notebookPath],
                        ["Infrastructure",infra.join(", ")],
                        ["Agents",        pickedAgents.join(", ")],
                      ].map(([k, v]) => (
                        <tr key={k} style={{borderBottom:"1px solid var(--rule)"}}>
                          <td style={{padding:"5px 8px", fontFamily:"var(--mono)",
                                      color:"var(--muted)", width:130, whiteSpace:"nowrap"}}>{k}</td>
                          <td style={{padding:"5px 8px", fontFamily:"var(--mono)"}}>{v}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div style={{
                    background:"var(--paper-2)", borderRadius:2, padding:"8px 12px",
                    fontSize:11, color:"var(--ink-2)", borderLeft:"3px solid var(--purple)",
                  }}>
                    <strong>New project?</strong> If <code>{project}</code> has no GitHub repo,
                    Slack channel, or raw/refined directories yet, those will be scaffolded
                    as part of provisioning.
                  </div>
                </>
              )}
            </>
          )}
        </div>

        {/* footer */}
        {!done ? (
          <div style={{
            padding:"10px 16px", borderTop:"1px solid var(--rule)",
            display:"flex", justifyContent:"space-between", alignItems:"center",
            background:"var(--paper-2)",
          }}>
            {err
              ? <span style={{fontSize:11, color:"var(--red)"}}>{err}</span>
              : <span style={{fontSize:11, color:"var(--muted)"}}>step {step} of {STEP_LABELS.length}</span>
            }
            <div style={{display:"flex", gap:8}}>
              {step > 1 && (
                <button className="btn sm" onClick={() => setStep(s => s - 1)}>← back</button>
              )}
              {step < 5 && (
                <button className="btn sm primary" disabled={!canProceed()}
                        onClick={() => setStep(s => s + 1)}>
                  next →
                </button>
              )}
              {step === 5 && (
                <button className="btn sm primary" disabled={busy} onClick={provision}>
                  {busy ? "provisioning…" : "provision"}
                </button>
              )}
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

  const provision = async (resource) => {
    setBusy(b => ({...b, [resource]: true}));
    setErrs(e => ({...e, [resource]: null}));
    try {
      const q = userParam ? "?user=" + encodeURIComponent(userParam) : "";
      const r = await fetch("/api/project/" + encodeURIComponent(p.name) + "/provision/" + resource + q,
        {method: "POST"});
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || r.statusText);
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
          <button className="btn sm" disabled={busy.slack}
            onClick={() => provision("slack")}>
            {busy.slack ? "…" : (errs.slack ? "Retry Slack setup" : "Create Slack channel")}
          </button>
        )}
        {done.slack && <Pill tone="green">done — refresh to see channel</Pill>}
        {errs.slack && <span style={{color:"var(--red)", fontSize:11}}>{errs.slack}</span>}
      </div>
    </div>
  );
}

/* ───────── projects panel ───────── */
function ProjectsPanel({ projects, span="c-5" }) {
  const [openProj, setOpenProj] = useState(null);
  const [showNewProj, setShowNewProj] = useState(false);
  const persona = window.DATA.persona || "member";
  const isPI = persona === "pi";
  // Pending project-create requests — shown as an approval queue for the PI.
  const pendingCreate = (window.DATA.requests_pending || []).filter(
    r => r.kind === "project-create"
  );
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
          </tr></thead>
          <tbody>
            {projects.map(p => (
              <React.Fragment key={p.name}>
                <tr style={{cursor:"pointer"}} onClick={() => setOpenProj(openProj === p.name ? null : p.name)}>
                  <td>
                    <div style={{fontWeight:500}}>{p.name}</div>
                    <div className="mono muted" style={{fontSize:11}}>{p.choreo}</div>
                  </td>
                  <td><Pill tone={p.sens==="clinical"?"red":""}>{p.sens}</Pill></td>
                  <td className="mono" style={{fontSize:12, paddingLeft:14}}>{p.lead}</td>
                  <td className="num">{p.members}</td>
                  <td className="num"><strong>{p.open_seas}</strong></td>
                  <td className="muted" style={{fontSize:12}}>{p.last_activity}</td>
                </tr>
                {openProj === p.name && (
                  <tr>
                    <td colSpan={6} style={{
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
      `Deactivate @${peer.handle}? They'll be unable to run wigamig actions but their history stays. ` +
      `You can reactivate any time.`)) return;
    setBusyHandle(peer.handle);
    try { await postMemberStatus(peer.handle, action); await refresh(); }
    catch (ex) { alert(ex.message || ex); }
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
        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase"}}>repo destination</label>
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
  const refresh = async () => {
    if (typeof window.__wigamigFetchData === "function") {
      try { await window.__wigamigFetchData(window.DATA.persona); } catch (_) {}
    }
  };
  const onApprove = async () => {
    setBusy(true); setErr(null);
    try { await postRequestAction(req.id, "approve"); await refresh(); }
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
  });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg]   = useState(null);

  const update = (k) => (e) =>
    setForm((prev) => ({ ...prev, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setMsg(null);
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
      setMsg("saved");
      if (typeof window.__wigamigFetchData === "function") {
        try { await window.__wigamigFetchData(window.DATA.persona); } catch (_) {}
      }
      setTimeout(onClose, 800);
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
            <div><span className="muted">Western username</span> <code className="mono">{m.handle}</code></div>
            <div><span className="muted">name</span> {m.name}</div>
            <div><span className="muted">role</span> {m.role}</div>
            <div><span className="muted">lab</span> <code className="mono">{m.lab}</code></div>
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
          <div style={labelStyle}>city</div>
          <input style={inputStyle} value={form.city} onChange={update("city")} />
          <div style={labelStyle}>department</div>
          <input style={inputStyle} value={form.department} onChange={update("department")} />
        </div>

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

/* ───────── Machine settings modal (per-machine: Obsidian paths) ───────── */
/* These four fields live in ~/.wigamig/machine.yaml because they differ
   between a user's laptop and the lab server. Editing happens here so
   non-IT users don't need to hand-edit YAML. */
function MachineSettingsModal({ onClose }) {
  const initial = window.DATA.machine_settings || {};
  const [form, setForm] = useState({
    obsidian_vault_path: initial.obsidian_vault_path || "",
    obsidian_vault_name: initial.obsidian_vault_name || "",
    notebook_subfolder:  initial.notebook_subfolder  || "lab-notebook",
    oracle_subfolder:    initial.oracle_subfolder    || "oracle",
  });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg]   = useState(null);

  const update = (k) => (e) => setForm((prev) => ({ ...prev, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setMsg(null);
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

  return (
    <div onClick={onClose} style={{
      position:"fixed", inset:0, background:"rgba(32,20,54,0.55)",
      display:"flex", alignItems:"flex-start", justifyContent:"center",
      zIndex:200, padding:"40px 20px", overflowY:"auto",
    }}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} style={{
        background:"var(--card)", border:"1px solid var(--rule-strong)",
        borderRadius:2, padding:18, width:"min(560px, 96vw)",
        display:"flex", flexDirection:"column", gap:4,
      }}>
        <div className="row" style={{justifyContent:"space-between", alignItems:"baseline"}}>
          <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:20, color:"var(--purple-deep)"}}>
            Machine settings
          </h2>
          <button type="button" className="btn sm ghost" onClick={onClose}>✕ close</button>
        </div>
        <p className="muted" style={{fontSize:12, margin:"4px 0 0"}}>
          Per-machine paths — saved to <code>~/.wigamig/machine.yaml</code>.
          These don't sync to other machines; each install (laptop, lab server,
          …) has its own values.
        </p>

        <div style={{borderTop:"1px solid var(--rule)", paddingTop:10, marginTop:10}}>
          <div style={labelStyle}>vault path (full)</div>
          <input style={inputStyle} value={form.obsidian_vault_path}
                 onChange={update("obsidian_vault_path")}
                 placeholder="/Users/you/.../obsidian-lab" />
          <div style={labelStyle}>vault name (for obsidian:// URLs)</div>
          <input style={inputStyle} value={form.obsidian_vault_name}
                 onChange={update("obsidian_vault_name")}
                 placeholder="obsidian-lab" />
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

        <div className="row" style={{justifyContent:"flex-end", gap:6, marginTop:14, alignItems:"center"}}>
          {msg && (
            <span className="muted" style={{fontSize:11, marginRight:"auto",
              color: msg === "saved" ? "var(--green)" : "var(--red)"}}>
              {msg}
            </span>
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

/* ───────── Lab settings modal (PI + admins only) ───────── */
function LabSettingsModal({ onClose }) {
  const ls = window.DATA.lab_settings || {};
  const [form, setForm] = useState({
    display_name:              ls.display_name              || "",
    website:                   ls.website                   || "",
    notebook_large_files_path: ls.notebook_large_files_path || "",
    lab_oracle_vault:          ls.lab_oracle_vault          || "",
    admins:                    (ls.admins || []).join(", "),
  });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg]   = useState(null);

  const update = (k) => (e) => setForm((prev) => ({ ...prev, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setMsg(null);
    try {
      const payload = { ...form, admins: form.admins.split(",").map(s => s.trim()).filter(Boolean) };
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
  const roStyle = { ...inputStyle, background:"var(--paper-2)", color:"var(--muted)", cursor:"default" };

  return (
    <div onClick={onClose} style={{
      position:"fixed", inset:0, background:"rgba(32,20,54,0.55)",
      display:"flex", alignItems:"flex-start", justifyContent:"center",
      zIndex:200, padding:"40px 20px", overflowY:"auto",
    }}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} style={{
        background:"var(--card)", border:"1px solid var(--rule-strong)",
        borderRadius:2, padding:18, width:"min(600px, 96vw)",
        display:"flex", flexDirection:"column", gap:4,
      }}>
        <div className="row" style={{justifyContent:"space-between", alignItems:"baseline"}}>
          <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:20, color:"var(--purple-deep)"}}>
            Lab settings
          </h2>
          <button type="button" className="btn sm ghost" onClick={onClose}>✕ close</button>
        </div>
        <p className="muted" style={{fontSize:12, margin:"4px 0 8px"}}>
          Lab-wide parameters. Edits POST to <code>/api/lab/settings</code> and update
          <code> &lt;lab-mgmt&gt;/lab.md</code>. Only the PI and designated admins can save changes.
        </p>

        {/* Read-only identity */}
        <div style={{borderTop:"1px solid var(--rule)", paddingTop:10}}>
          <h4 style={{margin:0, fontFamily:"var(--mono)", fontSize:10, letterSpacing:1.5,
                      textTransform:"uppercase", color:"var(--purple-deep)"}}>Identity (read-only)</h4>
          <div className="row" style={{flexWrap:"wrap", gap:14, marginTop:6, fontSize:13}}>
            <div><span className="muted">lab id</span> <code className="mono">{ls.name}</code></div>
            <div><span className="muted">PI</span> <code className="mono">{ls.pi_handle}</code></div>
          </div>
          <div style={labelStyle}>display name</div>
          <input style={inputStyle} value={form.display_name} onChange={update("display_name")}
                 placeholder="e.g. Hallett Lab" />
        </div>

        {/* Web presence */}
        <div style={{borderTop:"1px solid var(--rule)", paddingTop:10, marginTop:6}}>
          <h4 style={{margin:0, fontFamily:"var(--mono)", fontSize:10, letterSpacing:1.5,
                      textTransform:"uppercase", color:"var(--purple-deep)"}}>Web presence</h4>
          <div style={labelStyle}>lab website</div>
          <input style={inputStyle} value={form.website} onChange={update("website")}
                 placeholder="https://mikehallett.science" />
        </div>

        {/* Storage paths */}
        <div style={{borderTop:"1px solid var(--rule)", paddingTop:10, marginTop:6}}>
          <h4 style={{margin:0, fontFamily:"var(--mono)", fontSize:10, letterSpacing:1.5,
                      textTransform:"uppercase", color:"var(--purple-deep)"}}>Storage paths</h4>
          <div style={labelStyle}>notebook large files (figures, data — on lab base)</div>
          <input style={inputStyle} value={form.notebook_large_files_path}
                 onChange={update("notebook_large_files_path")}
                 placeholder="/data/lab_vm/obsidian-lab/notebooks" />
          <div style={labelStyle}>lab oracle vault (on lab base)</div>
          <input style={inputStyle} value={form.lab_oracle_vault}
                 onChange={update("lab_oracle_vault")}
                 placeholder="wigamig-vault-hallett/" />
        </div>

        {/* Admins */}
        <div style={{borderTop:"1px solid var(--rule)", paddingTop:10, marginTop:6}}>
          <h4 style={{margin:0, fontFamily:"var(--mono)", fontSize:10, letterSpacing:1.5,
                      textTransform:"uppercase", color:"var(--purple-deep)"}}>Settings admins</h4>
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
      {showMachine    && <MachineSettingsModal onClose={() => setShowMachine(false)} />}
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
              <button
                type="button"
                title="Machine settings — paths on this computer"
                onClick={() => setShowMachine(true)}
                style={{
                  background:"transparent", border:"1px solid var(--rule-strong)",
                  borderRadius:2, padding:"1px 6px", cursor:"pointer",
                  fontSize:11, color:"var(--purple)",
                }}>
                ⚙ machine
              </button>
              {canEditLab && (
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
            @{m.handle} · {m.role}
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
              <a href={"mailto:" + c.email}>{c.email}</a>
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
            <a href="https://www.schulich.uwo.ca/biochem/" target="_blank" rel="noopener">
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
        <a href="https://www.schulich.uwo.ca/biochem/" target="_blank" rel="noopener">
          <img className="schulich-mini" src="assets/Schulich_horizontal_CMYK.png" alt="Schulich School of Dentristy and Medicine" />
        </a>
        <a href="https://www.uwo.ca/" target="_blank" rel="noopener">
          <img className="western-mini" src="assets/western_longWhite.png" alt="Western University" />
        </a>
        <span className="dept">Department of Biochemistry · London, ON, Canada</span>
        <div className="links">
          <a href="mailto:michael.hallett@uwo.ca">Contact</a>
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

        {/* Reference zone: projects + activity (sit high — context for the action zone below). */}
        <div className="grid" style={{marginBottom:14}}>
          <ProjectsPanel projects={D.projects} span="c-7" />
          <ActivityPanel span="c-5" />
        </div>

        {/* Daily action zone: SEAs > Requests > Receptionist (PI). */}
        <div className="grid" style={{marginBottom:14}}>
          <SeasPanel seas={D.seas} span="c-12" />
        </div>

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

        {/* SEAs we offer (catalog) - every member sees; PI edits. */}
        <div className="grid" style={{marginBottom:14}}>
          <SeaCatalogPanel entries={D.sea_catalog} span="c-12" />
        </div>

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
