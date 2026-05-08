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
  // The persona is derived from lab.md (the PI handle), not chosen by the
  // user. The role badge below the search is informational, not interactive.
  const persona = window.DATA.persona || "member";
  return (
    <div className="cmdbar">
      <div className="home">wigamig <small>v0.7</small></div>
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
          <div className="big num">{s.closedThisWeek}<span className="delta up num">▲ {s.deltaPct}%</span></div>
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
          <div className="big num">{nb.entriesThisWeek}<span className="mono muted" style={{fontSize:11,fontWeight:400,marginLeft:4}}>/5</span></div>
          <div className="muted mono" style={{fontSize:11}}>entries</div>
        </div>
        <div className="sub">last written {nb.lastWritten}</div>
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
        <h2>SEAs</h2>
        <div className="row">
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
              <th style={{width:90}}>state</th>
              <th style={{width:100}}>kind</th>
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

/* ───────── projects panel ───────── */
function ProjectsPanel({ projects, span="c-5" }) {
  const [openProj, setOpenProj] = useState(null);
  return (
    <div className={"panel "+span}>
      <header>
        <h2>Projects</h2>
        <span className="meta">{projects.length} active · {projects.reduce((a,p)=>a+p.openSeas,0)} open SEAs</span>
      </header>
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
                  <td className="mono" style={{fontSize:12}}>{p.lead}</td>
                  <td className="num">{p.members}</td>
                  <td className="num"><strong>{p.openSeas}</strong></td>
                  <td className="muted" style={{fontSize:12}}>{p.lastActivity}</td>
                </tr>
                {openProj === p.name && (
                  <tr>
                    <td colSpan={6} style={{
                      background:"var(--paper-2)",
                      padding:"10px 12px",
                      fontSize:12, fontFamily:"var(--mono)",
                      borderBottom:"1px solid var(--rule)",
                    }}>
                      {p.github_repo && (
                        <div>
                          <span className="muted">github</span>{" "}
                          <a href={"https://github.com/" + p.github_repo} target="_blank" rel="noopener">
                            {p.github_repo}
                          </a>
                        </div>
                      )}
                      {p.slack_channel && (
                        <div>
                          <span className="muted">slack</span>{" "}
                          {p.slack_url ? (
                            <a href={p.slack_url} target="_blank" rel="noopener">#{p.slack_channel}</a>
                          ) : (
                            <span>#{p.slack_channel}</span>
                          )}
                        </div>
                      )}
                      {p.refined_path && (
                        <div><span className="muted">refined</span> <code>{p.refined_path}</code></div>
                      )}
                      {p.raw_path && (
                        <div><span className="muted">raw</span> <code>{p.raw_path}</code></div>
                      )}
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

/* ───────── group panel ───────── */
function GroupPanel({ peers, span="c-6" }) {
  const tcpsTone = { ok:"green", expiring:"amber", missing:"red" };
  const persona = window.DATA.persona || "member";
  return (
    <div className={"panel "+span}>
      <header>
        <h2>Group</h2>
        <span className="meta">
          {peers.length} {persona === "pi" ? "members lab-wide" : "shared-project peers"}
        </span>
      </header>
      <div className="body" style={{padding:"6px 0"}}>
        {peers.map(p => (
          <div key={p.handle} style={{padding:"9px 14px", borderBottom:"1px solid var(--rule)"}}>
            <div style={{display:"flex", justifyContent:"space-between", alignItems:"baseline"}}>
              <div>
                <span style={{fontWeight:500}}>{p.name}</span>
                <span className="mono muted" style={{fontSize:11, marginLeft:6}}>@{p.handle} · {p.role}</span>
              </div>
              <Pill tone={tcpsTone[p.tcps]}>tcps {p.tcps}</Pill>
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
            <div className="mono muted" style={{fontSize:11, marginTop:5, display:"flex", gap:14}}>
              <span><strong style={{color:"var(--ink-2)"}}>{p.open_seas}</strong> open SEAs</span>
              <span><strong style={{color:"var(--ink-2)"}}>{p.experiments}</strong> experiments</span>
            </div>
          </div>
        ))}
        {peers.length === 0 && (
          <div className="muted" style={{padding:"14px", fontSize:13}}>
            No peers in your projects.
          </div>
        )}
      </div>
    </div>
  );
}

/* ───────── agents panel ───────── */
async function postAgentToggle(name, action) {
  const res = await fetch(
    "/api/agents/" + encodeURIComponent(name) + "/" + encodeURIComponent(action),
    { method: "POST", headers: { Accept: "application/json" } }
  );
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
  const target = agent.disabled ? "enable" : "disable";
  const onClick = async () => {
    setBusy(true); setErr(null);
    try {
      await postAgentToggle(agent.name, target);
      if (typeof window.__wigamigFetchData === "function") {
        await window.__wigamigFetchData(window.DATA.persona);
      }
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
      <button className="btn sm" disabled={busy} onClick={onClick}>
        {busy ? "…" : target}
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
  const [members, setMembers] = useState("");
  const [sensitivity, setSensitivity] = useState("standard");
  const [justification, setJustification] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const submit = async (e) => {
    e.preventDefault();
    if (!name.trim()) { setErr("project name is required"); return; }
    setBusy(true); setErr(null);
    try {
      const proposed_members = members.split(",").map(s => s.trim()).filter(Boolean);
      await postCreateProjectRequest({
        project: name.trim(),
        proposed_members,
        sensitivity,
        justification: justification.trim(),
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
          Propose new project
        </h2>
        <p className="muted" style={{fontSize:12, margin:0}}>
          PI approval required. On approval, wigamig scaffolds the project repo
          and adds the proposed members to MEMBERS.
        </p>
        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase", marginTop:6}}>name (snake_case)</label>
        <input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. dcis_imaging_genomics"
               style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2, fontFamily:"var(--mono)"}}/>
        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase"}}>proposed members (comma-separated handles)</label>
        <input value={members} onChange={e => setMembers(e.target.value)} placeholder="@allie, @bob"
               style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2, fontFamily:"var(--mono)"}}/>
        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase"}}>sensitivity</label>
        <select value={sensitivity} onChange={e => setSensitivity(e.target.value)}
                style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2, fontFamily:"var(--mono)"}}>
          <option value="standard">standard</option>
          <option value="restricted">restricted</option>
          <option value="clinical">clinical</option>
        </select>
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
  const showMine  = (mine || []).filter(r => r.state !== "approved" || true);
  const [showNewProj, setShowNewProj] = useState(false);

  const headerLabel = isPI
    ? `${(pending || []).length} pending`
    : `${(mine || []).filter(r => r.state === "pending").length} pending · ${
        (mine || []).filter(r => r.state !== "pending").length} resolved`;

  return (
    <div className={"panel "+span}>
      <header>
        <h2>Requests</h2>
        <div className="row" style={{gap:6}}>
          <span className="meta">{headerLabel}</span>
          <NewJoinRequestButton />
          <button className="btn sm" onClick={() => setShowNewProj(true)}>＋ new project</button>
        </div>
      </header>
      {showNewProj && <NewProjectModal onClose={() => setShowNewProj(false)} />}
      <div className="body" style={{padding:"6px 0"}}>
        {isPI && showQueue.length === 0 && (
          <div className="muted" style={{padding:"14px", fontSize:13}}>
            No pending requests. Members will appear here when they ask to join a project.
          </div>
        )}
        {isPI && showQueue.map(r => (
          <RequestActionRow key={r.id} req={r} isPI={true} />
        ))}
        {!isPI && showMine.length === 0 && (
          <div className="muted" style={{padding:"14px", fontSize:13}}>
            You haven't filed any join requests. Click <code>＋ join project</code> above.
          </div>
        )}
        {!isPI && showMine.map(r => (
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

/* ───────── group oracle panel ───────── */
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

function GroupOraclePanel({ entries, drafts, span="c-6" }) {
  const list = entries || [];
  const pendingDrafts = drafts || [];
  const persona = window.DATA.persona || "member";
  const isPI = persona === "pi";
  return (
    <div className={"panel "+span}>
      <header>
        <h2>Group oracle · recent</h2>
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
            <code className="mono">~/{path}</code> · {words} words
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

/* ───────── footer ───────── */
/* FooterMeta reads everything from window.DATA.member — the API merges the
   member's frontmatter (`contact:` / `location:`) on top of the lab defaults,
   so postdocs in a different building see their own office while inheriting
   the lab address. See snapshot._merge_contact / _merge_location. */
function FooterMeta() {
  const m = window.DATA.member;
  const loc = m.location || {};
  const c = m.contact || {};

  // Build the office/dry-lab/wet-labs line, dropping any blank pieces.
  const officeBits = [
    loc.office     ? "Office: "   + loc.office   : null,
    loc.dry_lab    ? "Dry lab: "  + loc.dry_lab  : null,
    loc.wet_labs   ? "Wet labs: " + loc.wet_labs : null,
  ].filter(Boolean).join(" · ");

  return (
    <div className="footer-meta">
      <div className="grid">
        <div>
          <h5>Location</h5>
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
          <a href="mailto:michael.hallett@example.edu">Contact</a>
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
        <Strip persona={persona} />

        <div className="grid" style={{marginBottom:14}}>
          <SeasPanel seas={D.seas} span="c-12" />
        </div>

        {/* Projects + Project-join requests sit together: requests are
            the membership-side of projects so they belong adjacent. */}
        <div className="grid" style={{marginBottom:14}}>
          <ProjectsPanel projects={D.projects} />
          <RequestsPanel
            pending={D.requests_pending}
            mine={D.requests_mine}
            span="c-7"
          />
        </div>

        {/* Activity + Notebook + Group oracle row. (3 + 5 + 4 = 12) */}
        <div className="grid" style={{marginBottom:14}}>
          <ActivityPanel span="c-3" />
          <NotebookPanel span="c-5" />
          <GroupOraclePanel entries={D.oracle_recent} drafts={D.oracle_drafts} span="c-4" />
        </div>

        {/* Receptionist: PI-only inbound cross-group SEA queue. Sits up
            here in the action zone so the PI can clear it daily.
            Hidden entirely for non-PI members. */}
        {persona === "pi" && (
          <div className="grid" style={{marginBottom:14}}>
            <ReceptionistPanel inbound={D.inbound_requests} span="c-12" />
          </div>
        )}

        {/* Group + inventory: things you check, but not every day. */}
        <div className="grid" style={{marginBottom:14}}>
          <GroupPanel peers={D.peers} span="c-6" />
          <InventoryPanel inv={D.inventory} span="c-6" />
        </div>

        {/* SEAs we offer (catalog) — every member sees; PI edits. */}
        <div className="grid" style={{marginBottom:14}}>
          <SeaCatalogPanel entries={D.sea_catalog} span="c-12" />
        </div>

        {/* Agents (large, low-frequency) lives toward the bottom. */}
        <div className="grid" style={{marginBottom:14}}>
          <AgentsPanel agents={D.agents} span="c-12" />
        </div>

        {/* Compliance — most sporadic; lives at the bottom. */}
        <div className="grid">
          <Heatmap data={D.heatmap} persona={persona} span="c-12" />
        </div>
      </div>
      <FooterMeta />
      <Footer />
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
