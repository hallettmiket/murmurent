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

// A path is "unset" when empty or an explicit NA marker (matches the vault
// editor's convention). Used to decide whether to render a subfolder tree or a
// single "no <thing> on this machine" line (issue #99 §4).
function _pathUnset(p) {
  if (!p) return true;
  const s = String(p).trim().toLowerCase();
  return s === "" || s === "na" || s === "n/a" || s === "none" || s === "n.a.";
}

// Render a directory ROOT once (by the caller), then its children as bare,
// indented folder NAMES under a light tree glyph (issue #99). The repeated
// full-path lines the maintainer flagged as "a mess" are replaced by this:
// show the root once, then ``├─ oracle`` / ``└─ murmurent_data`` extensions.
// The full resolved path stays available on hover (title=) for copy-paste,
// per the #80 design. ``children`` is a list of bare folder names; the full
// path is _joinPath(root, name).
function PathTree({ root, children, indent = 120 }) {
  const kids = (children || []).filter(Boolean);
  if (kids.length === 0) return null;
  return (
    <div style={{marginLeft:indent, fontSize:11, color:"var(--muted)",
                 fontFamily:"var(--mono)", lineHeight:1.6}}>
      {kids.map((name, i) => {
        const last = i === kids.length - 1;
        const full = _joinPath(root, name);
        return (
          <div key={name}>
            <span style={{opacity:0.55}}>{last ? "└─ " : "├─ "}</span>
            <span title={full}>{name}</span>
          </div>
        );
      })}
    </div>
  );
}

// One-line "no <thing> on this machine" fallback (issue #99 §4) — shown in
// place of a tree when a root is unset / NA.
function NoRootLine({ label, indent = 120 }) {
  return (
    <div style={{marginLeft:indent, fontSize:11, color:"var(--muted)",
                 fontStyle:"italic"}}>
      No {label} on this machine
    </div>
  );
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
// Group-kind noun (issue #18): a core's dashboard is the SAME page as a
// lab's — it just says "Core members", "Core settings", … Kind comes from
// lab_settings.kind ("lab" | "core"), derived server-side from the group's
// lab.md (a core scaffold declares ``core: <name>``).
function groupNoun() {
  return ((window.DATA.lab_settings || {}).kind === "core") ? "Core" : "Lab";
}

// "Murmurent update available" banner (issue #41 pt 1).
// Detects when this install (the checkout the dashboard runs from) is behind
// upstream and offers a
// one-click update: `git pull --ff-only` + restart the dashboard. Only the code
// repo is touched — never ~/.murmurent, the roster clone, or the data root (all
// outside it), and --ff-only refuses rather than overwrite.
// NOTE(versioning): once we have official versions, replace the "may lose build
// progress" confirm below with a simple "Update to vX.Y.Z?" confirm (issue #41).
function UpdateBanner() {
  const [st, setSt] = useState(null);
  const [dismissed, setDismissed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");   // simple failure notice (e.g. ff refused)
  useEffect(() => {
    let alive = true;
    fetch("/api/murmurent/update-status?fetch=1", { headers: { Accept: "application/json" } })
      .then(r => r.json()).then(d => { if (alive) setSt(d); })
      .catch(() => {});
    return () => { alive = false; };
  }, []);
  if (!st || !st.ok || st.behind <= 0 || dismissed) return null;
  const diverged = !st.can_ff;
  // Say it in words (#185 follow-up): which copy, and a new release number if
  // there is one. Between releases the number does not change, so a
  // development copy is described by its new changes instead.
  const copy = st.name || "Murmurent";
  const newRelease = st.latest_version && st.current_version
    && st.latest_version !== st.current_version;
  const n = st.behind;
  const updateTitle = newRelease
    ? "Murmurent " + st.latest_version + " is available"
    : copy + " update available";
  const updateLine = newRelease
    ? "You have " + st.current_version + " in " + copy + "."
    : copy + " has " + n + " new change" + (n === 1 ? "" : "s") + " on GitHub"
      + (st.current_version ? " (still version " + st.current_version + ")" : "") + ".";
  // Version skew: the JSX is served fresh from disk, so it can be newer than the
  // running server. `can_self_update` is returned only by servers that also have
  // POST /api/murmurent/update — gate the button on it so we never offer a click
  // that would 404. An older (skewed) server gets restart guidance instead.
  const canSelfUpdate = !!st.can_self_update;

  // The server's process id, from /healthz. It changes on restart, so we can
  // tell the new server from the old one, which keeps answering for about a
  // second after the update (#185). Older servers send no id: fall back to
  // "answers at all".
  const bootId = async () => {
    const h = await fetch("/healthz", { cache: "no-store" });
    if (!h.ok) throw new Error("HTTP " + h.status);
    return (await h.json()).boot || null;
  };

  // After the server restarts, poll /healthz until a NEW process answers,
  // then hard-reload.
  const waitForRestartAndReload = async (before) => {
    for (let i = 0; i < 60; i++) {
      await new Promise(r => setTimeout(r, 1000));
      try {
        const now = await bootId();
        if (!before || (now && now !== before)) { window.location.reload(); return; }
      } catch (_) { /* still restarting */ }
    }
    setBusy(false);
    setMsg("Update pulled, but the dashboard did not restart. Restart it with: murmurent dashboard --hifi");
  };

  const doUpdate = async () => {
    if (!window.confirm(
      "Update murmurent and restart the dashboard?\n\n" +
      "This pulls the latest code and restarts. You may lose any unsaved " +
      "progress on your current build.")) return;
    setBusy(true); setMsg("");
    try {
      let before = null;
      try { before = await bootId(); } catch (_) {}
      const r = await fetch("/api/murmurent/update", { method: "POST", headers: { Accept: "application/json" } });
      const d = await r.json();
      if (d.restart) { await waitForRestartAndReload(before); return; }
      // Didn't restart → ff refused / diverged / already current: simple notice.
      setBusy(false);
      setMsg(d.detail || "Update did not run.");
    } catch (e) {
      setBusy(false);
      setMsg("Update request failed: " + (e.message || e));
    }
  };

  const failed = !!msg;
  return (
    <div role="status" style={{
      display:"flex", alignItems:"center", gap:10, flexWrap:"wrap",
      padding:"8px 16px", fontSize:13,
      background: (diverged || failed) ? "rgba(198,40,40,0.09)" : "rgba(90,60,160,0.10)",
      borderBottom:"1px solid var(--rule-strong)",
    }}>
      <span style={{fontWeight:600}}>
        {(diverged || failed) ? "⚠ " + updateTitle : "⬆ " + updateTitle}
      </span>
      <span className="muted"
            title={(st.root ? "checked " + st.root + " · " : "") + "commit " + st.current + " → " + st.latest}>
        {updateLine}
      </span>
      {(st.changes || []).length > 0 && (
        <details style={{fontSize:12}}>
          <summary style={{cursor:"pointer"}}>what changed</summary>
          <ul style={{margin:"4px 0 0 18px", padding:0}}>
            {st.changes.map((c, i) => <li key={i}>{c}</li>)}
          </ul>
        </details>
      )}
      {failed
        ? <span className="muted" style={{color:"var(--tiger-deep)"}}>{msg}</span>
        : diverged
          ? <span className="muted">Your install has local changes. Bring <code>{st.root || "your murmurent folder"}</code> up to date by hand first.</span>
          : !canSelfUpdate
            ? <span className="muted">Your dashboard is running older code than what's on disk — restart it to enable one-click update: <code className="mono">murmurent dashboard --hifi</code>, then reload.</span>
            : <>
                <button type="button" className="btn sm primary" disabled={busy} onClick={doUpdate}>
                  {busy ? "updating…" : "update & restart"}
                </button>
                <span className="muted" style={{fontSize:11}}>pulls latest + restarts — you may lose unsaved build progress.</span>
              </>}
      <button type="button" className="btn sm ghost" style={{marginLeft:"auto"}}
        onClick={() => setDismissed(true)}>dismiss</button>
    </div>
  );
}

// Which murmurent code this dashboard runs: the development copy (folder,
// branch, commit) or an installed release. The release number alone hid that
// a laptop was running murmurent_dev (#185 follow-up).
function RunningCodeBadge() {
  const b = window.DATA.build || {};
  if (!b.label) return null;
  const isDev = b.kind === "dev";
  const tip = (isDev ? "Development copy" : (b.kind === "checkout" ? "Git checkout" : "Installed release"))
    + " · running from " + (b.folder || "?")
    + (b.dirty ? " · has uncommitted changes" : "");
  return (
    <span title={tip} style={{
      marginLeft:14, fontFamily:"var(--mono)", fontSize:11, padding:"1px 8px",
      borderRadius:10, whiteSpace:"nowrap",
      color: isDev ? "#7a3fb0" : "var(--muted)",
      border: "1px solid " + (isDev ? "#7a3fb0" : "var(--rule-strong)"),
    }}>
      running {b.label}
    </span>
  );
}

// Stop the dashboard program itself. Closing the browser window leaves it
// running, and the dashboard icon starts it with no terminal to stop it from.
function StopDashboardButton() {
  const b = window.DATA.build || {};
  const [stopped, setStopped] = useState(false);
  if (b.stoppable === false) return null;   // run by a system service
  const stop = async () => {
    if (!window.confirm(
      "Stop the dashboard?\n\nThis page stops working until you start it again: " +
      "click the Murmurent Dashboard icon, or run  murmurent dashboard --hifi")) return;
    try {
      const r = await fetch("/api/dashboard/stop", { method: "POST", headers: { Accept: "application/json" } });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { alert(d.detail || ("Could not stop the dashboard (HTTP " + r.status + ").")); return; }
      setStopped(true);
    } catch (e) { setStopped(true); }  // the server may close the connection as it stops
  };
  if (stopped) {
    return (
      <div style={{position:"fixed", inset:0, background:"var(--paper)", zIndex:1000,
                   display:"flex", alignItems:"center", justifyContent:"center",
                   flexDirection:"column", gap:8, fontSize:15}}>
        <strong>The dashboard has stopped.</strong>
        <span className="muted">Start it again with the Murmurent Dashboard icon, or
          run <code>murmurent dashboard --hifi</code>. You can close this window.</span>
      </div>
    );
  }
  return (
    <button type="button" onClick={stop} className="btn sm ghost"
            title="Stop the dashboard program on this machine (closing the window does not)"
            style={{marginLeft:10, fontSize:11}}>
      ⏻ stop dashboard
    </button>
  );
}

function TopBar() {
  const m = window.DATA.member || {};
  const ls = window.DATA.lab_settings || {};
  // Institution-agnostic: show THIS install's lab, never a hardcoded one.
  const labLabel = ls.display_name || ls.name || m.lab || "";
  const kindLabel = (ls.kind === "core") ? "core" : "lab";
  return (
    <div className="topbar">
      <span className="uwo" style={{fontWeight:600}}>{labLabel}</span>
      <a href="https://mikehallett.science/murmurent/" target="_blank" rel="noopener"
         title="Murmurent documentation — getting started, projects, identity, CLI reference"
         style={{marginLeft:14, fontFamily:"var(--mono)", fontSize:12,
                 color:"var(--purple)", textDecoration:"none",
                 borderBottom:"1px dotted var(--purple)"}}>
        📖 docs
      </a>
      <RunningCodeBadge />
      <StopDashboardButton />
      <span className="who">
        signed in as <code>@{m.handle}</code> · {kindLabel}: <code>{m.lab || ls.name}</code>
      </span>
    </div>
  );
}

/* ───────── machine-identity badge (issue #80) ─────────
   Always-visible in the header so that, with a laptop dashboard and a tunneled
   server dashboard both open in browser tabs, each tab plainly says WHICH
   machine it is. Sourced from /api/environment/this_machine (machine_name +
   id from machine.yaml, falling back to the hostname). Visually distinct
   (icon + colored pill) so it is hard to miss. */
function MachineBadge() {
  const [env, setEnv] = useState(null);
  useEffect(() => {
    fetch("/api/environment/this_machine", { headers: { Accept: "application/json" } })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setEnv(d); })
      .catch(() => {});
  }, []);
  const name = env ? (env.machine_name || env.short_hostname || env.machine_id || "this machine") : "…";
  const isLaptop = env && env.kind === "laptop";
  const roleHint = env ? (isLaptop ? "laptop" : "host") : "";
  const tip = env
    ? `You are on "${name}" (${env.hostname || env.machine_id || "?"}) · ${roleHint}`
      + " — this dashboard drives THIS machine."
    : "Identifying this machine…";
  return (
    <div title={tip} style={{
      display:"inline-flex", alignItems:"center", gap:6, marginLeft:10,
      padding:"3px 11px", borderRadius:14, fontWeight:700, fontSize:12,
      fontFamily:"var(--mono)", letterSpacing:0.2, whiteSpace:"nowrap",
      color:"var(--paper)",
      background: isLaptop
        ? "linear-gradient(90deg,#4f2683,#7a3fb0)"
        : "linear-gradient(90deg,#0f766e,#0ea5a0)",
      border:"1px solid rgba(0,0,0,0.15)",
      boxShadow:"0 1px 3px rgba(32,20,54,0.28)",
    }}>
      <span aria-hidden="true" style={{fontSize:13}}>{isLaptop ? "💻" : "🖥"}</span>
      <span>{name}</span>
      {roleHint && (
        <span style={{
          fontSize:9, letterSpacing:1, textTransform:"uppercase", opacity:0.85,
          borderLeft:"1px solid rgba(255,255,255,0.4)", paddingLeft:6,
        }}>{roleHint}</span>
      )}
    </div>
  );
}

function CmdBar({ query, setQuery }) {
  // The persona arrives via ?persona= from the /login landing page; the
  // role badge below the search is informational (it reflects the lens
  // the user picked at sign-in).
  const persona = window.DATA.persona || "member";
  // This top-bar button is a copy of the footer "⚙ lab" control so the PI can
  // reach Lab settings without scrolling. PI only: only the PI can push lab.md
  // to the lab management repo, so a listed admin's save would fail to share
  // (#185, #34).
  const canEditLab = persona === "pi";
  const [showLabTop, setShowLabTop] = useState(false);
  return (
    <div className="cmdbar">
      {showLabTop && <LabSettingsModal onClose={() => setShowLabTop(false)} />}
      {/* murmurent logo — the murmuration wordmark animation, served at
          /murmuration (?logo = chrome-free, auto-play, muted). The animation
          fills its own viewport, and the flock density + murmuration ribbons
          only read in a LARGE world; a 120px iframe crams ~260 birds into a
          swarm. So we render it in a 720px world and CSS-scale it down into a
          ~156px box (overflow-clipped) — real murmuration density, shown small,
          and the scale-down slows the on-screen motion too. */}
      {/* Logo widget: the murmuration animation with the "Murmurent" wordmark
          overlaid top-right (dark purple) and the version bottom-left. The
          separate ".home" brand title was removed — the wordmark IS the title. */}
      <div style={{position:"relative", width:156, height:156, flexShrink:0}}>
        <div style={{
          width:156, height:156, overflow:"hidden", borderRadius:8,
          background:"#f4f1ea", boxShadow:"0 1px 5px rgba(32,20,54,0.15)",
        }}>
          <iframe
            src="/murmuration?logo"
            title="murmurent"
            scrolling="no"
            style={{
              width:720, height:720, border:"none",
              transform:"scale(0.2167)", transformOrigin:"top left",
            }}
          />
        </div>
        <div style={{
          position:"absolute", top:7, left:9, fontSize:20, fontWeight:800,
          color:"#4a1e70", letterSpacing:"0.2px", lineHeight:1,
          textShadow:"0 1px 2px rgba(244,241,234,0.92)", pointerEvents:"none",
        }}>Murmurent</div>
        {window.DATA.version ? <div style={{
          position:"absolute", bottom:7, right:9, fontSize:11, fontWeight:600,
          color:"#4a1e70", opacity:0.9, lineHeight:1, pointerEvents:"none",
          textShadow:"0 1px 2px rgba(244,241,234,0.92)",
        }}>v{window.DATA.version}</div> : null}
      </div>
      <div className="search">
        <span className="mono muted" style={{fontSize:12}}>›</span>
        <input
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="search SEAs, experiments, projects, people, notebook…"
        />
        <K>⌘K</K>
      </div>
      <MachineBadge />
      {canEditLab && (
        <button
          type="button"
          onClick={() => setShowLabTop(true)}
          title={groupNoun() + " settings — set your group's parameters (PI / admin)"}
          style={{
            marginLeft: 10, fontFamily: "var(--mono)", fontSize: 11,
            letterSpacing: 1, textTransform: "uppercase",
            color: "var(--paper)", background: "var(--purple)",
            border: "1px solid var(--purple)", borderRadius: 2,
            padding: "3px 10px", cursor: "pointer", fontWeight: 600,
          }}>
          ⚙ {groupNoun()} settings
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
          title="Open the security audit: file permissions, secrets and setup checks (/security)"
          target="_blank" rel="noopener"
          style={{
            marginLeft: 10, fontFamily: "var(--mono)", fontSize: 11,
            letterSpacing: 1, textTransform: "uppercase",
            color: "var(--tiger)", textDecoration: "none",
            border: "1px solid var(--tiger)", borderRadius: 2,
            padding: "3px 8px",
          }}>
          ⚿ security audit ↗
        </a>
      )}
      {/* /space link: the lab's weekly space report (#151), PI only, and only
          when the PI turned the audit on in Lab settings (#185). */}
      {persona === "pi" && (window.DATA.lab_settings || {}).space_audit === "on" && (
        <a
          href={`/space?user=${encodeURIComponent((window.DATA.member && window.DATA.member.handle) || "")}`}
          title="Open the space audit: how much disk each project and member uses (/space)"
          target="_blank" rel="noopener"
          style={{
            marginLeft: 10, fontFamily: "var(--mono)", fontSize: 11,
            letterSpacing: 1, textTransform: "uppercase",
            color: "var(--tiger)", textDecoration: "none",
            border: "1px solid var(--tiger)", borderRadius: 2,
            padding: "3px 8px",
          }}>
          ▤ space audit ↗
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

/* Launch a bare Claude Code CLI session in a native terminal — no repo
   required. Pass { project } to start the session in that repo's dir, or
   {} for a scratch session in $HOME. POST /api/workspace/claude-session. */
async function postClaudeSession(body) {
  const params = new URLSearchParams(window.location.search);
  const userParam = params.get("user");
  const url = "/api/workspace/claude-session" + (userParam ? "?user=" + encodeURIComponent(userParam) : "");
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

/* CCLaunchBar: prominent top-level "launch Claude Code" entry point, placed
   ABOVE the repos list. Opens a bare CC session (no repo) — the "just launch
   Claude Code from the dashboard" flow. Per-repo sessions live in the repos
   list below (each row's "▶ CC" button). */
function CCLaunchBar({ span = "c-12" }) {
  const [busy, setBusy] = useState(false);
  const [msg,  setMsg]  = useState(null);
  const launch = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await postClaudeSession({});
      setMsg(r.already_open
        ? "already open — brought to front"
        : "opened Claude Code — check your terminal");
      setTimeout(() => setMsg(null), 4000);
    } catch (ex) {
      setMsg(String(ex.message || ex));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className={"card " + span}
         style={{display:"flex", alignItems:"center", justifyContent:"space-between",
                 gap:14, padding:"12px 16px"}}>
      <div style={{display:"flex", flexDirection:"column", gap:2}}>
        <strong style={{fontSize:14}}>Claude Code</strong>
        <span className="muted" style={{fontSize:11}}>
          Launch a Claude Code CLI session in a new terminal — no repo needed.
          Per-repo sessions are in the list below.
        </span>
      </div>
      <div style={{display:"flex", alignItems:"center", gap:10}}>
        {msg && (
          <span style={{fontSize:11, color:/open/i.test(msg) ? "var(--muted)" : "var(--red)"}}>
            {msg}
          </span>
        )}
        <button className="btn primary" onClick={launch} disabled={busy}
          title="Open a Claude Code CLI session in a new terminal">
          {busy ? "launching…" : "▶ Launch Claude Code"}
        </button>
      </div>
    </div>
  );
}

/* ── RepoInventoryPanel: this machine's repos + the lab's GitHub org,
   grouped by project (#185).

   Loads /api/inventory/repos (cached) on mount; the dashboard's
   startup hook runs a fresh scan weekly. Refresh button forces a live
   re-scan (one ``gh repo list`` + one local ``find .git``). */
function RepoInventoryPanel({ span = "c-12" }) {
  const [report, setReport] = useState(null);
  const [busy, setBusy] = useState(true);
  const [err, setErr] = useState(null);
  const [showAllGithub, setShowAllGithub] = useState(false);
  // murmurent-infra repos (murmurent, murmurent_*) are pinned to the top of the
  // list but hidden by default — they're infrastructure, not working repos the
  // user manages day-to-day. This toggle reveals them.
  const [showInfra,  setShowInfra]  = useState(false);
  const [removeCtx,  setRemoveCtx]  = useState(null);  // {name, path} for the remove modal
  const [adoptCtx,   setAdoptCtx]   = useState(null);  // {name, path, origin}
  const [upgrading,  setUpgrading]  = useState(null);  // clone_path being upgraded
  const [upgraded,   setUpgraded]   = useState(null);  // {name, verdict, version}
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

  // Re-wire an already-ready repo against the current murmurent release. No
  // modal: unlike adopt there's nothing to choose — the repo already records
  // its lab + agents, and `all_agents` would silently widen that set.
  const doUpgrade = async (ctx) => {
    setUpgrading(ctx.path); setErr(null); setUpgraded(null);
    try {
      const r = await fetch("/api/inventory/upgrade", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ clone_path: ctx.path }),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail || ("HTTP " + r.status));
      setUpgraded({ name: ctx.name, verdict: j.verdict,
                    version: j.bootstrap_version });
      await load(true);
    } catch (ex) {
      setErr(String(ex.message || ex));
    } finally { setUpgrading(null); }
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

  const infraCount = report ? (report.rows || []).filter(rowIsMurmurentInfra).length : 0;

  // Display order:
  //   1. murmurent-infra rows FIRST, but only when showInfra is on (hidden by
  //      default — they're infrastructure, not day-to-day working repos).
  //   2. then working repos: cloned rows, plus GitHub-only rows when toggled.
  const visibleRows = (() => {
    if (!report) return [];
    const rows = report.rows || [];
    const infra = rows.filter(rowIsMurmurentInfra);
    const rest  = rows.filter(r => !rowIsMurmurentInfra(r));
    const restVisible = showAllGithub ? rest : rest.filter(r => r.clones && r.clones.length > 0);
    const infraVisible = showInfra ? infra : [];
    return [...infraVisible, ...restVisible];  // infra pinned to the top
  })();

  // Group the visible rows by project (#185 item 12): one heading per project
  // with its repos under it. A repo in two projects is listed under both;
  // repos in no project come last. murmurent's own repos keep their own group.
  const groups = (() => {
    const projects = (window.DATA.projects || []).filter(pr => pr.status !== "archived");
    const out = [];
    const placed = new Set();
    if (showInfra) {
      const infraRows = visibleRows.filter(rowIsMurmurentInfra);
      if (infraRows.length) out.push({ title: "Murmurent's own repos", rows: infraRows });
      infraRows.forEach(r => placed.add(r));
    }
    for (const pr of projects) {
      const names = new Set((pr.repos || []).map(r => r.name));
      const rows = visibleRows.filter(r => !rowIsMurmurentInfra(r) && names.has(r.name));
      if (rows.length) out.push({ title: pr.name, isProject: true, rows });
      rows.forEach(r => placed.add(r));
    }
    const loose = visibleRows.filter(r => !placed.has(r));
    if (loose.length) out.push({ title: "Not in any project", rows: loose });
    return out;
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
            <span className="mono muted" style={{fontSize:10.5}}
                  title={`scan timestamp (${report.generated_at})`}>
              scanned {_fmtLocalStamp(report.generated_at)}
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
          <label style={{fontSize:11, display:"inline-flex", alignItems:"center", gap:4}}
                 title="murmurent's own repos (murmurent, murmurent_*) — infrastructure, pinned to the top when shown">
            <input type="checkbox" checked={showInfra}
                   onChange={e => setShowInfra(e.target.checked)} />
            show Murmurent repos
          </label>
        </div>
      </header>
      <div className="body" style={{padding:0}}>
        <div style={{
          padding:"10px 14px", fontSize:11.5, lineHeight:1.55,
          background:"var(--paper-2)", borderBottom:"1px solid var(--rule)",
          color:"var(--ink-2)",
        }}>
          Repo states — each host cell shows whether the repo is on that machine,
          and whether murmurent is wired into it:
          <ul style={{margin:"4px 0 0 18px", padding:0}}>
            <li>
              Not cloned — the repo isn't on this machine.
            </li>
            <li>
              Cloned · not ready — the repo is here, but murmurent isn't wired
              into it. The Make ready button writes the readiness marker and links
              the commons agents.
            </li>
            <li>
              Cloned · ready — Claude Code sessions opened here have the murmurent
              agents and rules. The Upgrade button re-wires the repo to the current
              murmurent release (a new agent, or a changed marker format); agent
              edits arrive on their own, so you only need Upgrade for structural changes.
            </li>
          </ul>
          <div style={{marginTop:6}}>
            Repos are grouped by the project they belong to. A project is a named
            set of repos and members, made with ＋ new project in the Projects
            panel; the repos you pick there are made ready for you.
          </div>
          <div style={{marginTop:6}}>
            <strong>▶ Claude Code</strong> opens a new terminal window running
            Claude Code inside that repo, so the session starts with the repo's
            files, agents and rules.
          </div>
        </div>
        {err && (
          <div style={{padding:"10px 14px", color:"var(--red)", fontSize:12}}>
            {err}
          </div>
        )}
        {upgraded && (
          <div style={{padding:"8px 14px", fontSize:11.5, color:"var(--green)"}}>
            <strong>{upgraded.name}</strong> upgraded — {upgraded.verdict}
            {upgraded.version ? ` (murmurent ${upgraded.version})` : ""}.
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
          // width:auto + table-layout:auto override the .dt defaults
          // (100% + fixed), so columns size to their content instead of the
          // repo column hogging all the slack and the host cells being crushed
          // to 120px (which shattered "Make ready" into vertical letters).
          <table className="dt" style={{
            width:"auto", tableLayout:"auto",
            minWidth:"min(100%, 720px)", margin:"0 auto",
          }}>
            <thead><tr>
              <th style={{minWidth:260, whiteSpace:"nowrap", paddingRight:32}}>repo</th>
              <th style={{whiteSpace:"nowrap", paddingRight:32}}>github</th>
              {knownHosts.map(h => (
                <th key={h} style={{textAlign:"left", whiteSpace:"nowrap"}}>{h}</th>
              ))}
              <th style={{width:28}}></th>
            </tr></thead>
            <tbody>
              {groups.map(g => (
                <React.Fragment key={"g:" + g.title}>
                  <tr>
                    <td colSpan={3 + knownHosts.length}
                        style={{paddingTop:12, fontWeight:600, fontSize:12.5,
                                color: g.isProject ? "var(--purple-deep)" : "var(--muted)",
                                borderBottom:"1px solid var(--rule-strong)"}}>
                      {g.isProject ? "project: " : ""}{g.title}
                      <span className="mono muted" style={{fontWeight:400, fontSize:10.5, marginLeft:8}}>
                        {g.rows.length} repo{g.rows.length === 1 ? "" : "s"}
                      </span>
                    </td>
                  </tr>
                  {g.rows.map((r, i) => (
                    <RepoInventoryRow
                      key={g.title + ":" + r.key + ":" + i}
                      row={r}
                      knownHosts={knownHosts}
                      onAdopt={(ctx) => setAdoptCtx(ctx)}
                      onUpgrade={doUpgrade}
                      upgrading={upgrading}
                      onRemove={(ctx) => setRemoveCtx(ctx)}
                    />
                  ))}
                </React.Fragment>
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
      {removeCtx && (
        <RemoveRepoModal
          repo={removeCtx}
          onClose={(removed) => {
            setRemoveCtx(null);
            if (removed) load(true);
          }}
        />
      )}
    </div>
  );
}

// Server stamps are UTC ISO ("2026-07-15T21:35:40+00:00"). Render them in the
// VIEWER's timezone — slicing the string printed UTC while labelling it like
// local time, so an Eastern reader saw a clock four hours ahead of their own.
function _fmtLocalStamp(iso) {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso).slice(0, 16).replace("T", " ");
  return d.toLocaleString([], {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

/* Frontend mirror of core.repo_inventory.is_murmurent_infra_repo(): murmurent's
   OWN repos — the commons clone ``murmurent`` + the ``murmurent_*`` family
   (lab_mgmt, vault, public, manuscript, …) — are infrastructure, never a
   project, so they can never be "made ready". Duplicated here (not only trusted
   from the server's is_murmurent_infra flag) so the button is suppressed even
   when the panel is showing a STALE cached report scanned before that flag
   existed — which is exactly what left the button active in #55. */
function isMurmurentInfraName(name) {
  const n = String(name || "").trim().split("/").pop();
  return n === "murmurent" || n.startsWith("murmurent_");
}

/* Is this whole inventory row a murmurent-infra repo? True if the server flagged
   any clone, OR the repo/clone name matches the classifier (covers stale caches
   and GitHub-only rows that have no clone to carry the flag). */
function rowIsMurmurentInfra(row) {
  if (isMurmurentInfraName(row.name)) return true;
  for (const c of (row.clones || [])) {
    if (c.is_murmurent_infra) return true;
    if (isMurmurentInfraName((c.path || "").split("/").pop())) return true;
  }
  return false;
}

function RepoInventoryRow({ row, knownHosts, onAdopt, onUpgrade, upgrading, onRemove }) {
  const gh = row.github;
  const cloneByHost = {};
  for (const c of (row.clones || [])) cloneByHost[c.host] = c;
  const rowInfra = rowIsMurmurentInfra(row);
  // Remove is offered only for a NON-infra repo that has a LOCAL clone to
  // remove. murmurent infrastructure is never removable here.
  const localClone = cloneByHost["local"];
  const canRemove = !rowInfra && localClone && onRemove;

  // Per-repo launch: open a Claude Code CLI session in this repo's LOCAL clone
  // (localClone above). Only offered when the repo is cloned on this machine.
  const [ccBusy, setCcBusy] = useState(false);
  const [ccMsg,  setCcMsg]  = useState(null);
  const launchCC = async () => {
    if (!localClone) return;
    setCcBusy(true);
    setCcMsg(null);
    try {
      const r = await postClaudeSession({ cwd: localClone.path });
      setCcMsg(r.already_open ? "already open" : "opened");
      setTimeout(() => setCcMsg(null), 3000);
    } catch (ex) {
      setCcMsg(String(ex.message || ex));
    } finally {
      setCcBusy(false);
    }
  };

  // GitHub cell: a link to the repo, labelled with its visibility.
  // (Was "✓ {visibility[0]}" — the first letter of "public" and "private" is
  // the same "p", so every repo rendered an identical, meaningless "✓ p".)
  const ghCell = gh ? (
    <a href={`https://github.com/${gh.full_name}`} target="_blank" rel="noopener"
       className="mono" style={{fontSize:11}}
       title={`Open ${gh.full_name} on GitHub (${gh.visibility})`}>
      {gh.visibility === "private" ? "🔒 private" : "public"} ↗
    </a>
  ) : (
    <span className="muted" style={{fontSize:11}}>—</span>
  );

  // Per-host cell. Three states, named the way the legend names them:
  //   Cloned · murmurent-ready      + Upgrade    (re-wire to current release)
  //   Cloned · not murmurent-ready  + Make ready (adopt; local or over SSH)
  //   Not cloned
  // "ready" is about THIS REPO only — it never implies a project.
  const hostCell = (host) => {
    const c = cloneByHost[host];
    if (!c) {
      return (
        <span className="muted" style={{fontSize:11, fontFamily:"var(--mono)"}}>
          Not cloned
        </span>
      );
    }
    // murmurent's OWN repos (the commons clone, lab-mgmt, vault, …) are
    // infrastructure — they are never "made ready" (a repo can't adopt itself;
    // lab-mgmt is governance, not a project). Mark them distinctly and offer no
    // make-ready button, so they don't read as ready-buttons that are broken
    // (#41 pt 5). This wins over the ready/not-ready branches below. We also
    // fall back to the name classifier so a stale cached report (one scanned
    // before the is_murmurent_infra flag existed) still suppresses the button
    // instead of leaving it active — the bug in #55.
    if (c.is_murmurent_infra || rowInfra
        || isMurmurentInfraName((c.path || "").split("/").pop())) {
      return (
        <span title={c.path + " — murmurent infrastructure — not a project; "
                     + "cannot be made ready"}
              style={{fontSize:11, color:"var(--purple)", fontFamily:"var(--mono)",
                      whiteSpace:"nowrap"}}>
          ◆ murmurent
        </span>
      );
    }
    // A plain project folder that isn't a git repo yet (#49). It shows up so it
    // doesn't silently vanish from the manager; but "make ready" needs a git
    // repo, so we surface it with a git-init hint rather than a broken button.
    if (c.is_git === false) {
      return (
        <span title={c.path + " — a folder here, but not a git repo. Run "
                     + "`git -C " + c.path + " init` (and add a remote) to make it "
                     + "a repo, then it can be made murmurent-ready."}
              style={{fontSize:11, color:"var(--muted)", fontFamily:"var(--mono)",
                      whiteSpace:"nowrap"}}>
          ○ folder · not a git repo
        </span>
      );
    }
    if (c.is_murmurent_ready) {
      return (
        <span style={{display:"inline-flex", alignItems:"center", gap:8, whiteSpace:"nowrap"}}>
          <span title={c.path} style={{
            fontSize:11, color:"var(--green)", fontFamily:"var(--mono)", whiteSpace:"nowrap",
          }}>
            ● Cloned · ready
          </span>
          {/* Upgrade is local-only: repo_ready works on the filesystem, and the
              remote bootstrap still writes the legacy CHARTER shape. */}
          {onUpgrade && host === "local" && (
            <button className="btn sm" style={{fontSize:11, padding:"3px 9px", whiteSpace:"nowrap"}}
                    disabled={upgrading === c.path}
                    title={"Re-wire this repo against the current murmurent release "
                         + "(new agents, marker format). Agent edits arrive on their "
                         + "own — this is for structural changes."}
                    onClick={() => onUpgrade({
                      name: row.name, path: c.path, host: host,
                    })}>
              {upgrading === c.path ? "…" : "Upgrade"}
            </button>
          )}
        </span>
      );
    }
    // Cloned but not murmurent-ready — offer it regardless of host. The
    // endpoint branches local vs SSH; the modal passes `host` through.
    return (
      <span style={{display:"inline-flex", alignItems:"center", gap:8, whiteSpace:"nowrap"}}>
        <span title={c.path} style={{
          fontSize:11, color:"var(--muted)", fontFamily:"var(--mono)", whiteSpace:"nowrap",
        }}>
          ○ Cloned · not ready
        </span>
        {onAdopt && (
          <button className="btn sm" style={{fontSize:11, padding:"3px 9px", whiteSpace:"nowrap"}}
                  title={host === "local"
                    ? "Wire murmurent into this repo (marker + commons agents). Creates no project."
                    : `Wire murmurent into this repo on ${host}, over SSH. Creates no project.`}
                  onClick={() => onAdopt({
                    name: row.name,
                    path: c.path,
                    origin: c.origin_url || "",
                    host: host,
                  })}>
            Make ready
          </button>
        )}
      </span>
    );
  };

  return (
    <tr>
      <td style={{fontSize:12}}>
        <strong>{row.name}</strong>
        {rowInfra && (
          <span title="murmurent infrastructure — not a project; cannot be made ready"
                style={{fontSize:10, marginLeft:6, padding:"1px 6px", borderRadius:4,
                        color:"var(--purple)", border:"1px solid var(--purple)",
                        fontFamily:"var(--mono)", whiteSpace:"nowrap"}}>
            ◆ murmurent infra
          </span>
        )}
        {row.local_only && (
          <span className="muted" style={{fontSize:10, marginLeft:6}}>
            (local-only — no GitHub origin)
          </span>
        )}
        {gh && gh.archived && (
          <span className="muted" style={{fontSize:10, marginLeft:6}}>(archived)</span>
        )}
        {localClone && (
          <button className="btn sm"
            style={{marginLeft:8, fontSize:11, padding:"2px 8px", whiteSpace:"nowrap"}}
            disabled={ccBusy}
            title={"Open a terminal running Claude Code in " + localClone.path}
            onClick={launchCC}>
            {ccBusy ? "…" : "▶ Claude Code"}
          </button>
        )}
        {ccMsg && (
          <span style={{marginLeft:6, fontSize:10,
                        color:/open/i.test(ccMsg) ? "var(--muted)" : "var(--red)"}}>
            {ccMsg}
          </span>
        )}
      </td>
      <td>{ghCell}</td>
      {knownHosts.map(h => <td key={h}>{hostCell(h)}</td>)}
      <td style={{textAlign:"right", width:28, paddingRight:8}}>
        {canRemove && (
          <button
            title={"Remove the local clone of " + row.name + " (" + localClone.path + ")"}
            onClick={() => onRemove({ name: row.name, path: localClone.path })}
            style={{background:"none", border:0, cursor:"pointer", color:"var(--muted)",
                    fontSize:15, lineHeight:1, padding:"0 2px"}}
            onMouseOver={e => (e.currentTarget.style.color = "var(--red)")}
            onMouseOut={e => (e.currentTarget.style.color = "var(--muted)")}>
            ×
          </button>
        )}
      </td>
    </tr>
  );
}

/* ── AdoptCloneModal: make a plain git clone murmurent-READY.
   Pops from the Repo Inventory's "↑ adopt" button on • clone rows.
   POSTs /api/inventory/adopt, which writes the .murmurent.yaml
   readiness marker + the CC bootstrap (commons agent symlinks,
   CLAUDE.md stub). Creates NO project — a project is a set of repos +
   members, made via New Project, which attaches ready repos. */
function AdoptCloneModal({ clone, onClose }) {
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
  const [busy, setBusy] = useState(false);
  const [err, setErr]   = useState(null);
  const [probes, setProbes] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr(null); setProbes(null);
    try {
      const r = await fetch("/api/inventory/adopt", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          clone_path: clone.path,
          agents:     pickedAgents,
          host:       clone.host || "local",
        }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(body.detail || ("HTTP " + r.status));
      setProbes(body.probes || []);
      if (typeof window.__murmurentFetchData === "function") {
        try { await window.__murmurentFetchData(window.DATA.persona); } catch (_) {}
      }
      // Auto-close on success after a beat so the user sees what landed.
      setTimeout(() => onClose(true), 1400);
    } catch (ex) {
      setErr(String(ex.message || ex));
    } finally { setBusy(false); }
  };

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
        borderRadius:2, padding:18, width:"min(560px, 96vw)",
        display:"flex", flexDirection:"column", gap:2,
      }}>
        <div className="row" style={{justifyContent:"space-between", alignItems:"baseline"}}>
          <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:18,
                      color:"var(--purple-deep)"}}>
            Make repo murmurent-ready
          </h2>
          <button type="button" className="btn sm ghost"
                  onClick={() => onClose(false)}>✕ close</button>
        </div>
        <p className="muted" style={{fontSize:12, margin:"4px 0 6px"}}>
          Bootstraps <code className="mono">{clone.name}</code>
          {clone.host && clone.host !== "local" ? <> on <strong>{clone.host}</strong> (one SSH session)</> : null}
          {" "}— writes the readiness marker and symlinks the picked commons agents into
          {" "}<code>.claude/agents/</code>.
        </p>

        <div className="muted" style={{fontSize:12, marginTop:8, marginBottom:2}}>
          Click agents to de-select.
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
            {busy ? "bootstrapping…" : "make ready"}
          </button>
        </div>
      </form>
    </div>
  );
}

/* RemoveRepoModal — danger-zone removal of a repo's LOCAL clone.
   Mirrors GitHub's "type the name to confirm" gate: the delete button stays
   disabled until the typed text exactly matches the repo name. Server-side the
   clone is MOVED to ~/.murmurent/trash/repos/ (recoverable), murmurent-infra
   repos are refused, and only the local clone is ever touched. */
function RemoveRepoModal({ repo, onClose }) {
  const [typed, setTyped] = useState("");
  const [busy,  setBusy]  = useState(false);
  const [err,   setErr]   = useState(null);
  const [done,  setDone]  = useState(null);   // {trash, note} on success
  const match = typed.trim() === repo.name;

  const submit = async (e) => {
    e.preventDefault();
    if (!match) return;
    setBusy(true); setErr(null);
    try {
      const params = new URLSearchParams(window.location.search);
      const userParam = params.get("user");
      const url = "/api/inventory/repos/" + encodeURIComponent(repo.name)
                + "?confirm=" + encodeURIComponent(typed.trim())
                + "&host=local"
                + (userParam ? "&user=" + encodeURIComponent(userParam) : "");
      const r = await fetch(url, { method: "DELETE", headers: { Accept: "application/json" } });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(body.detail || ("HTTP " + r.status));
      setDone({ trash: body.trash, note: body.note });
      setTimeout(() => onClose(true), 1800);
    } catch (ex) {
      setErr(String(ex.message || ex));
    } finally { setBusy(false); }
  };

  return (
    <div onClick={() => onClose(false)} style={{
      position:"fixed", inset:0, background:"rgba(32,20,54,0.55)",
      display:"flex", alignItems:"flex-start", justifyContent:"center",
      zIndex:200, padding:"40px 20px", overflowY:"auto",
    }}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} style={{
        background:"var(--card)", border:"1px solid var(--red)",
        borderRadius:2, padding:18, width:"min(520px, 96vw)",
        display:"flex", flexDirection:"column", gap:8,
      }}>
        <div className="row" style={{justifyContent:"space-between", alignItems:"baseline"}}>
          <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:18, color:"var(--red)"}}>
            Remove repo
          </h2>
          <button type="button" onClick={() => onClose(false)}
            style={{background:"none", border:0, fontSize:18, cursor:"pointer", color:"var(--muted)"}}>×</button>
        </div>

        {done ? (
          <div style={{fontSize:12.5, color:"var(--green)"}}>
            Removed <strong>{repo.name}</strong>. {done.note}
          </div>
        ) : (
          <>
            <p style={{margin:0, fontSize:12.5, lineHeight:1.5}}>
              This removes the <strong>local clone</strong> of{" "}
              <strong>{repo.name}</strong> at{" "}
              <span className="mono" style={{fontSize:11}}>{repo.path}</span>.
              It is <strong>moved to trash</strong> (~/.murmurent/trash/repos/),
              not permanently deleted — recoverable — and GitHub is untouched.
            </p>
            <label style={{fontFamily:"var(--mono)", fontSize:10, letterSpacing:1,
                           textTransform:"uppercase", color:"var(--muted)", marginTop:4}}>
              Type{" "}
              {/* textTransform:none so the repo name shows its REAL casing — the
                  uppercased label made a lowercase name look like it needed caps. */}
              <span style={{color:"var(--red)", textTransform:"none"}}>{repo.name}</span>
              {" "}to confirm
            </label>
            <input autoFocus value={typed} onChange={e => setTyped(e.target.value)}
              placeholder={repo.name}
              style={{fontFamily:"var(--mono)", fontSize:13, padding:"7px 9px",
                      border:"1px solid var(--rule-strong)", borderRadius:2}} />
            {err && <div style={{color:"var(--red)", fontSize:12}}>{err}</div>}
            <div className="row" style={{justifyContent:"flex-end", gap:8, marginTop:6}}>
              <button type="button" className="btn sm" onClick={() => onClose(false)}>Cancel</button>
              <button type="submit" className="btn sm"
                disabled={!match || busy}
                style={{background: match ? "var(--red)" : "var(--rule)",
                        color: match ? "white" : "var(--muted)", borderColor:"var(--red)"}}>
                {busy ? "removing…" : "Remove repo"}
              </button>
            </div>
          </>
        )}
      </form>
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
  const [enrollFor, setEnrollFor] = React.useState(null);  // handle needing enrollment JSON
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
        // before pubkey recording, or external). Open a modal with a COPYABLE
        // enroll command + a paste box (native window.prompt text can't be
        // selected/copied — the thing the user asked to fix).
        setBusy(null);
        setEnrollFor(handle);
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

  return (
    <div style={{marginBottom:8, paddingBottom:8, borderBottom:"1px solid var(--rule)"}}>
      <div style={{display:"flex", alignItems:"center", gap:8, flexWrap:"wrap"}}>
        <span style={{fontFamily:"var(--mono)", fontSize:10, letterSpacing:1,
              textTransform:"uppercase", color:"var(--muted)"}}>members</span>
        {/* The viewer is shown once — as their own "@handle (you)" entry in the
            cert list below — so there's no separate "you: <cert>" chip that
            duplicated the same person (e.g. "you: lead" + "@the_pi · lead"). */}
        {certMembers.map(m => {
          const h = m.replace(/^@/, "");
          const isMe = h.toLowerCase() === viewer;
          return (
            <span key={m} className="mono"
                  style={{fontSize:11, padding:"2px 6px", borderRadius:2,
                          background:"rgba(79,38,131,0.08)", color:"var(--purple)",
                          display:"inline-flex", alignItems:"center", gap:4}}>
              🔑 @{h}{isMe ? " (you)" : ""}{h.toLowerCase() === leadNorm ? " · lead" : ""}
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
      {enrollFor && (
        <EnrollHelpModal
          handle={enrollFor}
          project={p.name}
          onClose={() => setEnrollFor(null)}
          onSubmit={(obj) => { setEnrollFor(null); addMember(enrollFor, obj); }}
        />
      )}
    </div>
  );
}

/* EnrollHelpModal — shown when adding a member who has no attested key yet.
   Replaces a native window.prompt (whose text can't be selected) with a modal
   that has a COPYABLE enroll command + a paste box for the JSON they send back. */
function EnrollHelpModal({ handle, project, onClose, onSubmit }) {
  const cmd = "murmurent enroll --project " + project;
  const [json, setJson] = React.useState("");
  const [copied, setCopied] = React.useState(false);
  const [err, setErr] = React.useState(null);
  const copy = () => {
    (navigator.clipboard ? navigator.clipboard.writeText(cmd) : Promise.reject())
      .then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); })
      .catch(() => { setErr("couldn't copy — select the text and ⌘C"); });
  };
  const submit = () => {
    const t = json.trim();
    if (!t) { onClose(); return; }
    let obj = null;
    try { obj = JSON.parse(t); }
    catch (_) { setErr("that wasn't valid enrollment JSON"); return; }
    onSubmit(obj);
  };
  const h = String(handle).replace(/^@/, "");
  return (
    <div onClick={onClose} style={{
      position:"fixed", inset:0, background:"rgba(32,20,54,0.55)",
      display:"flex", alignItems:"flex-start", justifyContent:"center",
      zIndex:220, padding:"48px 20px", overflowY:"auto",
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        background:"var(--card)", border:"1px solid var(--rule-strong)",
        borderRadius:2, padding:18, width:"min(560px, 96vw)",
      }}>
        <div className="row" style={{justifyContent:"space-between", alignItems:"baseline"}}>
          <strong style={{fontFamily:"var(--serif)", fontSize:16, color:"var(--purple-deep)"}}>
            Enroll @{h} in {project}
          </strong>
          <button type="button" className="btn sm ghost" onClick={onClose}>✕ close</button>
        </div>
        <p className="muted" style={{fontSize:12, margin:"6px 0 8px"}}>
          @{h} has no attested key on the roster yet. Send them this command; they run
          it and send back the JSON it prints, which you paste below.
        </p>
        <div className="row" style={{gap:6, alignItems:"center"}}>
          <input readOnly value={cmd} onFocus={e => e.target.select()} className="mono"
                 style={{flex:1, minWidth:0, fontSize:12, padding:"5px 8px",
                         border:"1px solid var(--rule-strong)", borderRadius:2,
                         background:"var(--paper-2)"}} />
          <button type="button" className="btn sm" onClick={copy}>
            {copied ? "copied ✓" : "copy"}
          </button>
        </div>
        <div style={{fontFamily:"var(--mono)", fontSize:10, letterSpacing:1,
                     textTransform:"uppercase", color:"var(--muted)", margin:"10px 0 2px"}}>
          paste their enrollment JSON
        </div>
        <textarea value={json} onChange={e => setJson(e.target.value)}
                  placeholder={'{"handle": "@' + h + '", "project": "' + project + '", ...}'}
                  style={{width:"100%", minHeight:120, boxSizing:"border-box",
                          fontFamily:"var(--mono)", fontSize:12, padding:"6px 8px",
                          border:"1px solid var(--rule-strong)", borderRadius:2,
                          resize:"vertical"}} />
        {err && <div style={{color:"var(--red)", fontSize:11, marginTop:4}}>{err}</div>}
        <div className="row" style={{justifyContent:"flex-end", gap:6, marginTop:10}}>
          <button type="button" className="btn sm ghost" onClick={onClose}>cancel</button>
          <button type="button" className="btn sm primary" onClick={submit}>add @{h}</button>
        </div>
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
  const [removing, setRemoving] = React.useState(null);  // repo name in flight
  const [err, setErr] = React.useState(null);
  const q = userParam ? "?user=" + encodeURIComponent(userParam.replace(/^@/, "")) : "";
  const refresh = async () => {
    if (typeof window.__murmurentFetchData === "function") {
      try { await window.__murmurentFetchData(window.DATA.persona); } catch (_) {}
    }
  };
  const submit = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await fetch("/api/project/" + encodeURIComponent(p.name) + "/repos" + q,
        { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(f) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error((typeof j.detail === "string" ? j.detail : null) || r.statusText);
      setShow(false); setF({ repo_name: "", role: "manuscript", path: "", overleaf: true });
      await refresh();
    } catch (ex) { setErr(String(ex.message || ex)); } finally { setBusy(false); }
  };
  const removeRepo = async (name) => {
    if (!window.confirm("Remove repo '" + name + "' from " + p.name + "?\n\n" +
        "This only detaches it from the project — the clone on disk is left alone.")) return;
    setRemoving(name); setErr(null);
    try {
      const r = await fetch("/api/project/" + encodeURIComponent(p.name) +
                            "/repos/" + encodeURIComponent(name) + q,
        { method: "DELETE", headers: { Accept: "application/json" } });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error((typeof j.detail === "string" ? j.detail : null) || r.statusText);
      await refresh();
    } catch (ex) { setErr(String(ex.message || ex)); } finally { setRemoving(null); }
  };
  return (
    <div style={{marginBottom:8, paddingBottom:8, borderBottom:"1px solid var(--rule)"}}>
      <div style={{display:"flex", alignItems:"center", gap:8, flexWrap:"wrap"}}>
        <span style={{fontFamily:"var(--mono)", fontSize:10, letterSpacing:1,
              textTransform:"uppercase", color:"var(--muted)"}}>repos</span>
        {repos.map((r, i) => (
          <span key={i} title={(r.host && r.host !== "local" ? r.host + ":" : "") + (r.path || "")}
                style={{fontFamily:"var(--mono)", fontSize:11, padding:"1px 7px",
                borderRadius:3, color:"#fff", background:REPO_ROLE_COLOUR[r.role] || "#555",
                display:"inline-flex", alignItems:"center", gap:4}}>
            {r.role}: {r.name}{r.overleaf ? " · OL" : ""}
            {isPI && (
              <button type="button" disabled={removing === r.name}
                      onClick={() => removeRepo(r.name)}
                      title={"Detach " + r.name + " from this project (leaves the clone on disk)"}
                      style={{background:"none", border:0, cursor:"pointer",
                              color:"#fff", opacity:0.85, fontSize:13, padding:0, lineHeight:1}}>
                {removing === r.name ? "…" : "×"}
              </button>
            )}
          </span>
        ))}
        {repos.length === 0 && <span className="muted" style={{fontSize:11}}>none assigned</span>}
        {err && <span style={{color:"var(--red)", fontSize:11}}>{err}</span>}
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
  // flexWrap so a wide row (the Slack provision input + two buttons) wraps
  // within the Projects panel instead of overflowing into the Machines panel
  // beside it. rowGap keeps wrapped lines readable.
  const row = {marginBottom:4, display:"flex", alignItems:"center", gap:8,
               flexWrap:"wrap", rowGap:4};

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
              // Grow to fill the row but shrink to fit the panel — never force
              // horizontal overflow into the Machines panel beside it.
              flex:"1 1 220px", minWidth:0, maxWidth:"100%", boxSizing:"border-box",
            }}
            title="Override the default proj-<project> name. Leave blank to use the default."
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
            {projects.length} active
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
            <th style={{width:60}} className="num">team</th><th style={{width:80}}>activity</th>
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
                  <td className="muted" style={{fontSize:12}}>
                    {p.last_activity}
                    {(p.activity === "quiet" || p.activity === "dormant") && (
                      <span style={{marginLeft:6}}
                            title={p.activity === "dormant"
                              ? "Not used for the lab's dormant period: worth mothballing what is large"
                              : "Not used for the lab's quiet period"}>
                        <Pill tone={p.activity === "dormant" ? "amber" : ""}>{p.activity}</Pill>
                      </span>
                    )}
                  </td>
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
                    <td colSpan={isPI ? 6 : 5} style={{
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
// Personal-vault (murmurent_vault) freshness + refresh: the personal vault is
// single-writer per person but multi-machine; "update" = git pull --ff-only
// server-side, then refetch. Mirrors the roster helpers above.
async function getVaultInfo() {
  const res = await fetch("/api/vault/info", { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}
async function postVaultRefresh() {
  const res = await fetch("/api/vault/refresh", { method: "POST", headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}
// One-click "Sync vault" for THIS machine (issue #80 Wave 3): push local edits
// then ff-pull what other machines pushed. Returns {pushed, pulled, diverged,
// message, as_of}. Never auto-merges: diverged=true means "reconcile on the
// other machine first". Never a 5xx.
async function postVaultSync() {
  const res = await fetch("/api/vault/sync", { method: "POST", headers: { Accept: "application/json" } });
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

  // Save the bundle as a real bundle.json file (the member imports the file,
  // not copied-out text). Blob → object URL → synthetic click, revoke after.
  const downloadBundle = () => {
    try {
      const blob = new Blob([bundleText], {type:"application/json"});
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = "bundle.json";
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    } catch (_) {}
  };

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
              {/* Enrollment payloads store the handle WITH a leading @
                  (idcert._norm) — strip before prefixing or it renders @@. */}
              <div><span className="muted">handle</span> <code className="mono">@{String(parsed.handle).replace(/^@+/,"")}</code> <span className="muted" style={{fontSize:11}}>(murmurent netname, not Slack)</span></div>
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
              ? <>The card bundle was <strong>DM'd to them on Slack</strong> as a <code>bundle.json</code> file attachment. They download it and run the command below.</>
              : <>Send them this bundle (Slack DM couldn't be sent{result.dm && result.dm.detail ? `: ${result.dm.detail}` : ""}). Download it as <code>bundle.json</code> and they run:</>}
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
            <button type="button" className="btn sm ghost" onClick={downloadBundle}>
              download bundle.json
            </button>
            <button type="button" className="btn sm primary" onClick={onClose}>done</button>
          </div>
        </>}
      </div>
    </div>
  );
}

function LabMembersPanel({ peers, span="c-6" }) {
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
        <h2>{groupNoun()} members</h2>
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
      {roster && !roster.is_git && !roster.ok && (
        <div style={{margin:"0 14px 8px", padding:"8px 10px", borderRadius:2, fontSize:12.5,
             lineHeight:1.5, border:"1px solid var(--amber, #b8860b)",
             background:"rgba(184,134,11,0.07)"}}>
          <strong>This machine has no clone of the governance repository for
          your {groupNoun().toLowerCase()}, so the roster below is incomplete.</strong>
          <div className="muted" style={{marginTop:4}}>
            Members are read from <code className="mono">members/</code> in that
            repo, not from local state. Clone it at{" "}
            <code className="mono">{roster.path}</code> — ask your PI for the
            repository name — then press <em>update</em>.
          </div>
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
              <span />
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
  const spaceAudit = (window.DATA.lab_settings || {}).space_audit || "";
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
      `Revoke security audit access for @${peer.handle}?\n\n` +
      "They will no longer be able to open the security audit. You can grant it again later."
    )) return;
    setBusy(peer.handle);
    try {
      await postLabSudo(peer.handle, grant);
      if (typeof window.__murmurentFetchData === "function") {
        try { await window.__murmurentFetchData(window.DATA.persona); } catch (_) {}
      }
    } catch (ex) { alert("Security audit access update failed: " + (ex.message || ex)); }
    finally { setBusy(null); }
  };
  return (
    <div className={"panel " + span}>
      <header>
        <h2>Lab audits</h2>
        <div className="row" style={{gap:8}}>
          <a className="btn sm" href={`/security?user=${encodeURIComponent(me.handle || "")}`}
             target="_blank" rel="noopener">open security audit ↗</a>
          {spaceAudit === "on" && (
            <a className="btn sm" href={`/space?user=${encodeURIComponent(me.handle || "")}`}
               target="_blank" rel="noopener">open space audit ↗</a>
          )}
        </div>
      </header>
      <div className="body" style={{padding:"10px 14px", fontSize:12, lineHeight:1.55}}>
        <p className="muted" style={{margin:"0 0 6px 0"}}>
          The <strong>security audit</strong> checks a lab machine for files that
          should not be readable or writable by others (for example original data
          that can still be changed, or results anyone on the server can read),
          secrets committed to repositories, and your own Claude Code setup. Pick a
          machine, then press refresh to run a fresh check. It only reads; it
          never changes a file.
        </p>
        <p className="muted" style={{margin:"0 0 6px 0"}}>
          {spaceAudit === "on" && (<>The <strong>space audit</strong> is the
            millwright's weekly report of how much disk each project uses on the
            lab's data server, with suggestions for what could be tidied. </>)}
          {spaceAudit === "" && (<>A <strong>space audit</strong> is also available:
            a weekly report of how much disk each project uses, with suggestions
            for what could be tidied. It needs a one-time setup on the lab's data
            server and is optional; choose on or off in ⚙ Lab settings. </>)}
          {spaceAudit === "off" && (<>The space audit is turned off in ⚙ Lab
            settings. </>)}
        </p>
        <p className="muted" style={{margin:"0 0 10px 0"}}>
          You always have access to the security audit. Below, you can let a
          member open it too. This is a murmurent permission only; it does not
          give them administrator rights on the server.
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

/* ───────── contributions + choreographies (#38 Phases B/C) ───────── */
async function postJSON(url, body) {
  const opts = { method: "POST", headers: { Accept: "application/json" } };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

async function getJSON(url) {
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

async function refreshDashboard() {
  if (typeof window.__murmurentFetchData === "function") {
    try { await window.__murmurentFetchData(window.DATA.persona); } catch (_) {}
  }
}

function NewChoreographyModal({ onClose }) {
  const [form, setForm] = useState({ title:"", question:"", candidate_key:"", criteria:"" });
  const [busy, setBusy] = useState(false);
  const [err, setErr]   = useState(null);
  const set = k => e => setForm({ ...form, [k]: e.target.value });
  const submit = async () => {
    setBusy(true); setErr(null);
    try {
      await postJSON("/api/choreography", form);
      await refreshDashboard();
      onClose();
    } catch (ex) { setErr(String(ex.message || ex)); setBusy(false); }
  };
  const KEYS = ["inchikey", "smiles", "gene_symbol", "uniprot"];
  const field = (label, k, ph) => (
    <label style={{display:"block", marginBottom:10}}>
      <div className="mono muted" style={{fontSize:11, marginBottom:3}}>{label}</div>
      <input value={form[k]} onChange={set(k)} placeholder={ph}
             style={{width:"100%", padding:"6px 8px", border:"1px solid var(--rule-strong)",
                     borderRadius:2, fontFamily:"var(--sans)", fontSize:13}} />
    </label>
  );
  return (
    <div onClick={onClose} style={MODAL_BACKDROP_STYLE}>
      <div onClick={e => e.stopPropagation()} style={{...MODAL_PANEL_STYLE, maxWidth:520}}>
        <div style={{background:"var(--paper-2)", borderBottom:"1px solid var(--rule)", padding:"12px 16px"}}>
          <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:17, color:"var(--purple-deep)"}}>
            Pose a choreography
          </h2>
          <div className="muted" style={{fontSize:12, marginTop:3}}>
            Advertise a target. Members contribute contributions that join on the candidate key.
          </div>
        </div>
        <div style={{padding:16}}>
          {field("Title", "title", "e.g. Target X binders")}
          {field("Question", "question", "the compositional question being posed")}
          <label style={{display:"block", marginBottom:10}}>
            <div className="mono muted" style={{fontSize:11, marginBottom:3}}>
              Candidate key <span style={{textTransform:"none"}}>(the join/identity space)</span>
            </div>
            <input value={form.candidate_key} onChange={set("candidate_key")} list="ck-list"
                   placeholder="inchikey | smiles | gene_symbol | uniprot | other:<text>"
                   style={{width:"100%", padding:"6px 8px", border:"1px solid var(--rule-strong)",
                           borderRadius:2, fontFamily:"var(--mono)", fontSize:12}} />
            <datalist id="ck-list">{KEYS.map(k => <option key={k} value={k} />)}</datalist>
          </label>
          {field("Criteria", "criteria", "how the judge should present + rank candidates")}
          {err && <div style={{color:"var(--red)", fontSize:12, marginBottom:8}}>{err}</div>}
          <div style={{display:"flex", justifyContent:"flex-end", gap:8, marginTop:6}}>
            <button className="btn sm" onClick={onClose} disabled={busy}>cancel</button>
            <button className="btn sm primary" onClick={submit}
                    disabled={busy || !form.title || !form.question || !form.candidate_key || !form.criteria}>
              {busy ? "posing…" : "pose choreography"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// Start a choreography from nothing (POST /api/choreography/init). The CLI twin
// is `murmurent choreography init`; both run core.choreography_init, which
// creates the repository, declares it, poses the question, commits, and files
// the project request the PI approves.
function StartChoreographyModal({ onClose }) {
  const [form, setForm] = useState({
    name:"", title:"", summary:"", mode:"compositional", approaches:"",
    pose:true, candidate_key:"", criteria:"", request_project:true, members:"",
  });
  const [busy, setBusy]     = useState(false);
  const [err, setErr]       = useState(null);
  const [result, setResult] = useState(null);
  const set = k => e => setForm({ ...form,
    [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const csv = t => String(t || "").split(",").map(x => x.trim()).filter(Boolean);
  const posing = form.mode === "compositional" && form.pose;
  const ready = form.name && form.title && form.summary
    && (!posing || (form.candidate_key && form.criteria));
  const submit = async () => {
    setBusy(true); setErr(null);
    try {
      const res = await postJSON("/api/choreography/init", {
        name: form.name.trim(), title: form.title, summary: form.summary,
        mode: form.mode, approaches: csv(form.approaches),
        candidate_key: posing ? form.candidate_key : "",
        criteria: posing ? form.criteria : "",
        request_project: form.request_project, members: csv(form.members),
      });
      setResult(res);
      await refreshDashboard();
    } catch (ex) { setErr(String(ex.message || ex)); }
    finally { setBusy(false); }
  };
  const inputStyle = {width:"100%", padding:"6px 8px", border:"1px solid var(--rule-strong)",
                      borderRadius:2, fontFamily:"var(--sans)", fontSize:13};
  const label = (text, hint) => (
    <div className="mono muted" style={{fontSize:11, marginBottom:3}}>
      {text}{hint && <span style={{textTransform:"none"}}> ({hint})</span>}
    </div>
  );
  const field = (text, k, ph, hint) => (
    <label style={{display:"block", marginBottom:10}}>
      {label(text, hint)}
      <input value={form[k]} onChange={set(k)} placeholder={ph} style={inputStyle} />
    </label>
  );
  const MARK = { ok:"✓", warn:"!", fail:"✕" };
  const COLOUR = { ok:"var(--green,#2e7d32)", warn:"var(--amber,#b26a00)", fail:"var(--red)" };
  return (
    <div onClick={onClose} style={MODAL_BACKDROP_STYLE}>
      <div onClick={e => e.stopPropagation()} style={{...MODAL_PANEL_STYLE, maxWidth:600}}>
        <div style={{background:"var(--paper-2)", borderBottom:"1px solid var(--rule)", padding:"12px 16px"}}>
          <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:17, color:"var(--purple-deep)"}}>
            Start a choreography
          </h2>
          <div className="muted" style={{fontSize:12, marginTop:3}}>
            Creates its repository, poses its question, and asks your PI to make it a project.
          </div>
        </div>
        {!result && (
          <div style={{padding:16, maxHeight:"70vh", overflowY:"auto"}}>
            {field("Name", "name", "e.g. pin1_inhibition", "lowercase and underscores; also the repository name")}
            {field("Title", "title", "e.g. Dance with Inhibition")}
            <label style={{display:"block", marginBottom:10}}>
              {label("Summary", "what the approaches are and how they are combined")}
              <textarea value={form.summary} onChange={set("summary")} rows={3} style={inputStyle} />
            </label>
            <label style={{display:"block", marginBottom:10}}>
              {label("Mode", "compositional: several approaches, combined by the judge")}
              <select value={form.mode} onChange={set("mode")} style={inputStyle}>
                <option value="compositional">compositional</option>
                <option value="coordination">coordination</option>
              </select>
            </label>
            {field("Approaches", "approaches", "t1_docking, t2_assay", "comma-separated; can be added later")}
            {form.mode === "compositional" && (
              <div style={{border:"1px solid var(--rule)", padding:"10px 12px", marginBottom:10}}>
                <label style={{display:"flex", gap:6, alignItems:"center", fontSize:13, marginBottom: form.pose ? 10 : 0}}>
                  <input type="checkbox" checked={form.pose} onChange={set("pose")} />
                  Pose the question now
                </label>
                {form.pose && (<>
                  <label style={{display:"block", marginBottom:10}}>
                    {label("Candidate key", "what every approach reports on, so results line up")}
                    <input value={form.candidate_key} onChange={set("candidate_key")} list="ck-list-init"
                           placeholder="inchikey | smiles | gene_symbol | uniprot | other:<text>"
                           style={{...inputStyle, fontFamily:"var(--mono)", fontSize:12}} />
                    <datalist id="ck-list-init">
                      {["inchikey", "smiles", "gene_symbol", "uniprot"].map(k => <option key={k} value={k} />)}
                    </datalist>
                  </label>
                  <label style={{display:"block"}}>
                    {label("Criteria", "how the judge should rank and present results")}
                    <textarea value={form.criteria} onChange={set("criteria")} rows={3} style={inputStyle} />
                  </label>
                </>)}
              </div>
            )}
            <div style={{border:"1px solid var(--rule)", padding:"10px 12px", marginBottom:10}}>
              <label style={{display:"flex", gap:6, alignItems:"center", fontSize:13, marginBottom: form.request_project ? 10 : 0}}>
                <input type="checkbox" checked={form.request_project} onChange={set("request_project")} />
                Ask my PI to make it a project
              </label>
              {form.request_project && field("Members besides you", "members", "@bob, @carol", "comma-separated handles")}
            </div>
            {err && <div style={{color:"var(--red)", fontSize:12, marginBottom:8}}>{err}</div>}
            <div style={{display:"flex", justifyContent:"flex-end", gap:8, marginTop:6}}>
              <button className="btn sm" onClick={onClose} disabled={busy}>cancel</button>
              <button className="btn sm primary" onClick={submit} disabled={busy || !ready}>
                {busy ? "starting…" : "start choreography"}
              </button>
            </div>
          </div>
        )}
        {result && (
          <div style={{padding:16, maxHeight:"70vh", overflowY:"auto"}}>
            {result.probes.map((p, i) => (
              <div key={i} style={{fontSize:12, marginBottom:4, display:"flex", gap:6}}>
                <span style={{color: COLOUR[p.status] || "inherit"}}>{MARK[p.status] || "?"}</span>
                <span><b>{p.name}</b>: {p.detail}</span>
              </div>
            ))}
            {result.ok && (<>
              <div style={{fontSize:13, margin:"12px 0 6px"}}>
                The choreography is in <span className="mono">{result.repo_path}</span>. What is left:
              </div>
              <ol style={{fontSize:12, paddingLeft:20, margin:0}}>
                {result.next_steps.map((s, i) => <li key={i} style={{marginBottom:4}}>{s}</li>)}
              </ol>
            </>)}
            <div style={{display:"flex", justifyContent:"flex-end", marginTop:12}}>
              <button className="btn sm primary" onClick={onClose}>done</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ChoreographyCard({ c }) {
  const [busy, setBusy] = useState(null);
  const [err, setErr]   = useState(null);
  const attach = async (slug) => {
    setBusy(slug); setErr(null);
    try {
      await postJSON("/api/choreography/" + encodeURIComponent(c.id) + "/attach?contribution=" + encodeURIComponent(slug));
      await refreshDashboard();
    } catch (ex) { setErr(String(ex.message || ex)); }
    finally { setBusy(null); }
  };
  return (
    <div style={{padding:"11px 14px", borderBottom:"1px solid var(--rule)"}}>
      <div style={{display:"flex", justifyContent:"space-between", alignItems:"baseline", gap:8}}>
        <div style={{fontWeight:600, fontFamily:"var(--serif)"}}>{c.title}</div>
        <span className="mono muted" style={{fontSize:10}}>
          join on <span style={{color:"var(--purple-deep)"}}>{c.candidate_key || "—"}</span>
        </span>
      </div>
      {c.question && <div className="muted" style={{fontSize:12, marginTop:2}}>{c.question}</div>}
      {c.criteria && <div className="muted" style={{fontSize:11, marginTop:2, fontStyle:"italic"}}>criteria: {c.criteria}</div>}
      <div className="mono muted" style={{fontSize:10, marginTop:3}}>
        posed by {c.poser || "—"}
        {c.repo && <span style={{marginLeft:8}}>· repository {c.repo}</span>}
        {c.attached.length > 0 && (c.all_join
          ? <span style={{color:"var(--green,#2e7d32)", marginLeft:8}}>· all {c.attached.length} contribution(s) join — ready to compose</span>
          : <span style={{color:"var(--red)", marginLeft:8}}>· some attached contributions don't join</span>)}
      </div>

      {c.attached.length > 0 && (
        <div style={{marginTop:6}}>
          <div className="mono muted" style={{fontSize:10, letterSpacing:1}}>CONTRIBUTED</div>
          {c.attached.map((a, i) => (
            <div key={i} style={{fontSize:12, marginTop:2, display:"flex", gap:6, alignItems:"baseline"}}>
              <span style={{color: a.joins ? "var(--green,#2e7d32)" : "var(--red)"}}>{a.joins ? "✓" : "✕"}</span>
              <span>{a.contribution}</span>
              {a.author && <span className="mono muted" style={{fontSize:10}}>{a.author}</span>}
              {!a.joins && a.reason && <span className="mono" style={{fontSize:10, color:"var(--red)"}}>{a.reason}</span>}
            </div>
          ))}
        </div>
      )}

      {c.joinable.length > 0 && (
        <div style={{marginTop:6}}>
          <div className="mono muted" style={{fontSize:10, letterSpacing:1}}>JOINABLE — stated group contributions you can attach</div>
          {c.joinable.map((j, i) => (
            <div key={i} style={{fontSize:12, marginTop:2, display:"flex", justifyContent:"space-between", gap:8, alignItems:"baseline"}}>
              <span>{j.contribution} {j.author && <span className="mono muted" style={{fontSize:10}}>{j.author}</span>}</span>
              <button className="btn sm" disabled={busy === j.contribution}
                      onClick={() => attach(slugify(j.contribution))}>
                {busy === j.contribution ? "…" : "attach"}
              </button>
            </div>
          ))}
        </div>
      )}
      {err && <div style={{color:"var(--red)", fontSize:11, marginTop:4}}>{err}</div>}
    </div>
  );
}

// Client-side slug (mirrors core.contribution_contract.slugify closely enough for
// addressing a stated contribution by name).
function slugify(text) {
  return String(text || "").trim().toLowerCase()
    .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "contribution";
}

// Choreographies published in the public murmurent_public index (#185 item
// 15): list them and install one into the repositories folder.
function PublishedChoreographiesModal({ onClose }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const load = () => fetch("/api/choreographies/published").then(r => r.json())
    .then(setData).catch(e => setData({ rows: [], error: String(e) }));
  useEffect(() => { load(); }, []);
  const install = async (name) => {
    setBusy(name); setMsg("");
    try {
      const r = await fetch("/api/choreographies/install", { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) });
      const d = await r.json().catch(() => ({}));
      setMsg(d.detail || (r.ok ? "installed" : "HTTP " + r.status));
      load();
    } finally { setBusy(""); }
  };
  const rows = (data && data.rows) || [];
  return (
    <div onClick={onClose} style={{position:"fixed", inset:0, background:"rgba(32,20,54,0.55)",
         display:"flex", alignItems:"center", justifyContent:"center", zIndex:100}}>
      <div onClick={e => e.stopPropagation()} style={{background:"var(--card)", padding:18,
           border:"1px solid var(--rule-strong)", borderRadius:2, width:"min(560px, 92vw)",
           display:"flex", flexDirection:"column", gap:8, fontSize:13}}>
        <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:18, color:"var(--purple-deep)"}}>
          Published choreographies
        </h2>
        <div className="muted" style={{fontSize:12, lineHeight:1.5}}>
          From the public murmurent directory. Installing copies the repository
          into your repositories folder and makes it murmurent-ready; data is
          never included. Each choreography's README says what it does.
        </div>
        {!data && <div className="muted">Loading…</div>}
        {data && data.error && <div style={{color:"var(--red)"}}>{data.error}</div>}
        {data && !data.error && rows.length === 0 && <div className="muted">None published yet.</div>}
        {rows.map(r => (
          <div key={r.name} className="row" style={{justifyContent:"space-between", gap:8,
               borderBottom:"1px solid var(--rule)", padding:"4px 0"}}>
            <span><strong>{r.name}</strong>{" "}
              <a href={r.url.replace(/\.git$/, "")} target="_blank" rel="noopener"
                 className="mono muted" style={{fontSize:11}}>source ↗</a></span>
            {r.installed
              ? <span className="mono muted" style={{fontSize:11}} title={r.path}>installed</span>
              : <button className="btn sm" disabled={!!busy} onClick={() => install(r.name)}>
                  {busy === r.name ? "installing…" : "install"}
                </button>}
          </div>
        ))}
        {msg && <div style={{fontSize:12, lineHeight:1.5}}>{msg}</div>}
        <div className="row" style={{justifyContent:"flex-end"}}>
          <button className="btn sm ghost" onClick={onClose}>close</button>
        </div>
      </div>
    </div>
  );
}

function ChoreographiesPanel({ choreographies, span="c-12" }) {
  const list = choreographies || [];
  const [modal, setModal] = useState(false);
  const [starting, setStarting] = useState(false);
  const [browsing, setBrowsing] = useState(false);
  return (
    <div className={"panel "+span}>
      <header>
        <h2>Choreographies</h2>
        <span className="meta" style={{display:"flex", alignItems:"center", gap:8}}>
          {list.length} posed
          <button className="btn sm primary" onClick={() => setStarting(true)}
                  title="Create a choreography's repository, pose its question, and ask your PI to make it a project">
            + new choreography
          </button>
          <button className="btn sm" onClick={() => setModal(true)}
                  title="Pose a question on its own, with no repository behind it">
            + pose a question
          </button>
          <button className="btn sm" onClick={() => setBrowsing(true)}
                  title="Choreographies other labs published in the public murmurent directory">
            browse published
          </button>
        </span>
      </header>
      <div className="body" style={{padding:0}}>
        {list.length === 0 && (
          <div className="muted" style={{padding:"14px", fontSize:13}}>
            No choreographies yet. Start one to create its repository and pose its
            question; members then contribute approaches that report on the same
            candidates, and the judge combines them.
          </div>
        )}
        {list.map(c => <ChoreographyCard key={c.id || c.title} c={c} />)}
      </div>
      {modal && <NewChoreographyModal onClose={() => setModal(false)} />}
      {starting && <StartChoreographyModal onClose={() => setStarting(false)} />}
      {browsing && <PublishedChoreographiesModal onClose={() => setBrowsing(false)} />}
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
            core/personal_agents.py when models bump. */}
        <option value="fable">fable (5.1)</option>
        <option value="opus">opus (5.5)</option>
        <option value="sonnet">sonnet (5.5)</option>
        <option value="haiku">haiku (5.5)</option>
        <option value="inherit">inherit (same as the session)</option>
      </select>
      <button className="btn sm" disabled={busy} onClick={onToggle}>
        {busy ? "…" : (agent.disabled ? "enable" : "disable")}
      </button>
      {err && <span style={{fontSize:10, color:"var(--red)"}}>{err}</span>}
    </span>
  );
}

// Guardian agents can never be edited (mirrors core.personal_audit.GUARDIAN_AGENTS);
// keep in sync there. Frozen agents are also uneditable (flagged by a.freeze).
const GUARDIAN_AGENTS = ["security_guard", "adversary", "conscience"];

// Badge colours for "which version is in use" (#186 step 1). Problems
// (a broken link, nothing installed) stand out; the normal cases stay quiet.
const IN_USE_TONE = {
  "centre": "", "lab": "green", "yours": "purple", "person-project": "purple",
  "project": "green", "local-file": "amber", "broken-link": "red", "missing": "red",
};

// Versions of one agent per project (#186): which version you use there, and
// buttons to make your own for that project, switch it off there, or (PI)
// make yours the lab's. The levels are explained in docs/agent_versions.md.
function AgentVersionsModal({ name, onClose }) {
  const projects = (window.DATA.projects || []).filter(p => p.status !== "archived").map(p => p.name);
  const [project, setProject] = useState(projects[0] || "");
  const [view, setView] = useState(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const load = async (proj) => {
    setView(null);
    try {
      const r = await fetch("/api/agents/" + encodeURIComponent(name) + "/levels?project=" + encodeURIComponent(proj || ""));
      setView(await r.json());
    } catch (e) { setMsg("could not load: " + e); }
  };
  useEffect(() => { load(project); }, [project]);
  const act = async (path, body) => {
    setBusy(true); setMsg("");
    try {
      const r = await fetch("/api/agents/" + encodeURIComponent(name) + "/" + path, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}) });
      const d = await r.json().catch(() => ({}));
      setMsg(r.ok ? (d.detail || "done. Open a new Claude Code session for it to apply.")
                  : (d.detail || "HTTP " + r.status));
      await load(project);
      if (r.ok && typeof window.__murmurentFetchData === "function") {
        try { await window.__murmurentFetchData(window.DATA.persona); } catch (_) {}
      }
    } finally { setBusy(false); }
  };
  const v = view || {};
  return (
    <div onClick={onClose} style={{position:"fixed", inset:0, background:"rgba(32,20,54,0.55)",
         display:"flex", alignItems:"center", justifyContent:"center", zIndex:100}}>
      <div onClick={e => e.stopPropagation()} style={{background:"var(--card)", padding:18,
           border:"1px solid var(--rule-strong)", borderRadius:2, width:"min(520px, 92vw)",
           display:"flex", flexDirection:"column", gap:8, fontSize:13}}>
        <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:18, color:"var(--purple-deep)",
                    textTransform:"capitalize"}}>{name}: versions</h2>
        <div className="muted" style={{fontSize:12, lineHeight:1.5}}>
          Most specific wins: your version for one project, the project's, yours
          for all projects, the lab's, the centre's.
        </div>
        {v.everywhere && <div>Everywhere: <strong>{v.everywhere.label}</strong></div>}
        <label className="mono muted" style={{fontSize:11}}>project</label>
        <select value={project} onChange={e => setProject(e.target.value)}
                style={{padding:"5px 8px", border:"1px solid var(--rule-strong)"}}>
          {projects.length === 0 && <option value="">(no projects)</option>}
          {projects.map(n => <option key={n} value={n}>{n}</option>)}
        </select>
        {project && v.in_use && (
          <div>In {project}: <strong>{v.switched_off ? "switched off" : v.in_use.label}</strong>
            {!v.project_has_repo_here && (
              <span className="muted"> (none of its repos is on this machine, so this
                applies once one is)</span>
            )}
          </div>
        )}
        {v.locked ? (
          <div className="muted">This agent is centre-controlled: every lab, project
            and person uses the centre version{v.guardian ? ", and it cannot be switched off" : ""}.</div>
        ) : (
          <div className="row" style={{gap:6, flexWrap:"wrap"}}>
            <button className="btn sm" disabled={busy || !project}
                    onClick={() => act("fork_project", { project })}>
              my own for {project || "this project"}
            </button>
            {!v.guardian && (
              <button className="btn sm" disabled={busy || !project}
                      onClick={() => act("switch", { project, off: !v.switched_off })}>
                {v.switched_off ? "switch on in " : "switch off in "}{project || "this project"}
              </button>
            )}
            {v.is_pi && (
              <button className="btn sm" disabled={busy}
                      onClick={() => window.confirm("Make the version you use the lab's " + name +
                        "? Members use it unless they have their own.") && act("share_lab")}>
                make mine the lab's
              </button>
            )}
          </div>
        )}
        {msg && <div style={{fontSize:12, lineHeight:1.5}}>{msg}</div>}
        <div className="row" style={{justifyContent:"flex-end"}}>
          <button className="btn sm ghost" onClick={onClose}>close</button>
        </div>
      </div>
    </div>
  );
}

function AgentCard({ a }) {
  const [modify, setModify] = useState(false);
  const [versions, setVersions] = useState(false);
  // Show the Modify affordance only where an edit could land: not frozen, not a
  // guardian. The server re-checks (403) — this is just to avoid dead clicks.
  const canModify = a.freeze !== "frozen" && !GUARDIAN_AGENTS.includes(a.name);
  return (
    <div style={{
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
      {a.in_use_label && (
        <div style={{marginTop:4, fontSize:11}} title={a.in_use_detail}>
          <Pill tone={IN_USE_TONE[a.in_use_level] || ""}>in use: {a.in_use_label}</Pill>
          {a.upstream_changed && (
            <span className="muted" style={{marginLeft:6}}>centre version changed since you copied it</span>
          )}
          {(a.in_use_level === "broken-link" || a.in_use_level === "missing"
            || a.in_use_level === "local-file") && (
            <div className="muted" style={{marginTop:2, lineHeight:1.4}}>{a.in_use_detail}</div>
          )}
        </div>
      )}
      <div className="mono muted" style={{fontSize:10, marginTop:4, letterSpacing:1,
           display:"flex", alignItems:"center", gap:0}}>
        {a.model && <span>{a.model.toUpperCase()}</span>}
        {a.required_tools && a.required_tools.length > 0 && (
          <span style={{marginLeft:10}}>
            · {a.required_tools.length} tool{a.required_tools.length === 1 ? "" : "s"}
          </span>
        )}
        <span style={{marginLeft:"auto"}}>
          <button className="btn sm ghost" onClick={() => setVersions(true)}
                  title="Which version you use in each project; your own for one project; switch off per project">
            versions
          </button>
          {canModify ? (
            <button className="btn sm" onClick={() => setModify(true)}
                    title="Edit this agent — commons agents fork into your vault on first save">
              modify
            </button>
          ) : (
            <span title="frozen / guardian — not editable" style={{letterSpacing:1}}>🔒</span>
          )}
        </span>
      </div>
      {modify && <ModifyAgentModal name={a.name} onClose={() => setModify(false)} />}
      {versions && <AgentVersionsModal name={a.name} onClose={() => setVersions(false)} />}
    </div>
  );
}

// One labelled sub-section of the Agents panel (a commons category, or the
// personal section). Hidden when it has no agents.
function AgentGroup({ title, hint, agents }) {
  if (!agents || agents.length === 0) return null;
  return (
    <div>
      <div className="mono muted" style={{
        padding:"7px 14px", fontSize:10, letterSpacing:1, textTransform:"uppercase",
        borderBottom:"1px solid var(--rule)", background:"var(--paper-2, #faf9f7)",
      }}>
        {title} · {agents.length}
        {hint && <span style={{textTransform:"none", letterSpacing:0, marginLeft:8}}>{hint}</span>}
      </div>
      <div style={{display:"grid", gridTemplateColumns:"repeat(2, 1fr)"}}>
        {agents.map(a => <AgentCard key={a.name} a={a} />)}
      </div>
    </div>
  );
}

// Shared input styles for the DEFINE / MODIFY wizards.
const WIZ_INPUT = {width:"100%", padding:"6px 8px", border:"1px solid var(--rule-strong)",
                   borderRadius:2, fontFamily:"var(--sans)", fontSize:13, boxSizing:"border-box"};
const WIZ_MONO  = {...WIZ_INPUT, fontFamily:"var(--mono)", fontSize:12};
// Free-text boxes: readable line spacing and a drag handle, because the rows
// below are a floor rather than a cap — these fields are where an agent's
// behaviour actually gets described (issue #110).
const WIZ_TEXT  = {...WIZ_INPUT, lineHeight:1.5, resize:"vertical", minHeight:64};
const WIZ_LABEL = {display:"block", marginBottom:10};
const WIZ_CAP   = {fontSize:11, marginBottom:3};

function WizField({ label, hint, children }) {
  return (
    <label style={WIZ_LABEL}>
      <div className="mono muted" style={WIZ_CAP}>
        {label}{hint && <span style={{textTransform:"none"}}> — {hint}</span>}
      </div>
      {children}
    </label>
  );
}

// The shared wizard body (fields 2–12 of the bookworm's design). Used by both
// DEFINE (net-new) and MODIFY (edit existing). ``locked`` disables the name box
// (MODIFY can't rename). Everything but name + role defaults, so "name it and go"
// stays two boxes; the rest expand under a "more…" disclosure.
function AgentWizardFields({ form, set, locked }) {
  const [more, setMore] = useState(false);
  return (
    <div>
      {!locked && (
        <WizField label="Name" hint="lowercase, letters/digits/underscores">
          <input value={form.name} onChange={set("name")} placeholder="e.g. my_docking_helper"
                 style={WIZ_MONO} />
        </WizField>
      )}
      <WizField label="One-line role" hint="required — what is this agent for?">
        <input value={form.role} onChange={set("role")}
               placeholder="one line — the rest defaults, flesh it out below or later"
               style={WIZ_INPUT} />
      </WizField>
      <button className="btn sm" type="button" onClick={() => setMore(!more)}
              style={{marginBottom:10}}>
        {more ? "fewer options" : "more options (scope, tools, voice, guardrails…)"}
      </button>
      {more && (
        <div>
          <WizField label="Responsibilities" hint="one per line; defaults to the role">
            <textarea value={form.responsibilities} onChange={set("responsibilities")} rows={6}
                      placeholder={"load data\ntrain models\nreport metrics"} style={WIZ_TEXT} />
          </WizField>
          <WizField label="Scope & non-goals" hint="what it must NOT do — highest-leverage box">
            <textarea value={form.non_goals} onChange={set("non_goals")} rows={4}
                      placeholder="e.g. does not visualise — hand that to the artist"
                      style={WIZ_TEXT} />
          </WizField>
          <WizField label="Tools it MAY use" hint="comma-separated; blank inherits all">
            <input value={form.required_tools} onChange={set("required_tools")}
                   placeholder="Read, Bash, Grep" style={WIZ_MONO} />
          </WizField>
          <WizField label="Tools it must NOT use" hint="comma-separated">
            <input value={form.denied_tools} onChange={set("denied_tools")}
                   placeholder="WebFetch, WebSearch" style={WIZ_MONO} />
          </WizField>
          <WizField label="Persona / voice">
            <input value={form.persona} onChange={set("persona")}
                   placeholder="terse and skeptical; warm and pedagogical…" style={WIZ_INPUT} />
          </WizField>
          <WizField label="Output & communication format">
            <input value={form.output_format} onChange={set("output_format")}
                   placeholder="markdown report / HTML / slides / figures / tables" style={WIZ_INPUT} />
          </WizField>
          <WizField label="Headline-first verdict" hint="the verb vocabulary it leads every reply with">
            <input value={form.verdict} onChange={set("verdict")}
                   placeholder="Done / Failed / Partial" style={WIZ_MONO} />
          </WizField>
          <WizField label="Guardrails / safety" hint="always-do / ask-first / never-do">
            <textarea value={form.guardrails} onChange={set("guardrails")} rows={4}
                      placeholder="e.g. never write outside outputs/" style={WIZ_TEXT} />
          </WizField>
          <WizField label="Worked example" hint="one request + ideal response, to anchor behaviour">
            <textarea value={form.example} onChange={set("example")} rows={5}
                      placeholder="Request: … → Response: …" style={WIZ_TEXT} />
          </WizField>
          <WizField label="Model" hint="big model for hard reasoning, small for cheap/fast">
            <select value={form.model} onChange={set("model")}
                    style={{...WIZ_MONO, width:"auto", background:"#fff"}}>
              <option value="">default (inherit)</option>
              <option value="fable">fable (5.1)</option>
              <option value="opus">opus (5.5)</option>
              <option value="sonnet">sonnet (5.5)</option>
              <option value="haiku">haiku (5.5)</option>
              <option value="inherit">inherit (same as the session)</option>
            </select>
          </WizField>
        </div>
      )}
    </div>
  );
}

const EMPTY_WIZ = {
  name:"", role:"", responsibilities:"", non_goals:"", required_tools:"",
  denied_tools:"", persona:"", output_format:"", verdict:"", guardrails:"",
  example:"", model:"",
};

// Split a comma/space list string into an array for the API.
const wizTools = s => (s || "").split(/[,\s]+/).map(t => t.trim()).filter(Boolean);

function NewPersonalAgentModal({ onClose }) {
  const [form, setForm] = useState({ ...EMPTY_WIZ });
  const [busy, setBusy] = useState(false);
  const [err, setErr]   = useState(null);
  const set = k => e => setForm({ ...form, [k]: e.target.value });
  const submit = async () => {
    setBusy(true); setErr(null);
    try {
      const body = { name: form.name.trim(), description: form.role.trim() };
      if (form.model) body.model = form.model;
      if (form.required_tools.trim()) body.tools = wizTools(form.required_tools);
      if (form.denied_tools.trim()) body.denied_tools = wizTools(form.denied_tools);
      if (form.responsibilities.trim()) body.responsibilities = form.responsibilities;
      if (form.non_goals.trim()) body.non_goals = form.non_goals;
      if (form.persona.trim()) body.persona = form.persona;
      if (form.output_format.trim()) body.output_format = form.output_format;
      if (form.guardrails.trim()) body.guardrails = form.guardrails;
      if (form.example.trim()) body.example = form.example;
      if (form.verdict.trim()) body.verdict = form.verdict;
      await postJSON("/api/agents/new", body);
      await refreshDashboard();
      onClose();
    } catch (ex) { setErr(String(ex.message || ex)); setBusy(false); }
  };
  return (
    <div onClick={onClose} style={MODAL_BACKDROP_STYLE}>
      <div onClick={e => e.stopPropagation()} style={{...MODAL_PANEL_STYLE, maxWidth:640, maxHeight:"85vh", overflowY:"auto"}}>
        <div style={{background:"var(--paper-2)", borderBottom:"1px solid var(--rule)", padding:"12px 16px"}}>
          <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:17, color:"var(--purple-deep)"}}>
            New personal agent
          </h2>
          <div className="muted" style={{fontSize:12, marginTop:3}}>
            Yours alone — kept in your vault (backed up to your GitHub on{" "}
            <code className="mono">murmurent vault sync</code>) and loaded by Claude Code.
            Only name + role are required.
          </div>
        </div>
        <div style={{padding:16}}>
          <AgentWizardFields form={form} set={set} locked={false} />
          {err && <div style={{color:"var(--red)", fontSize:12, marginBottom:8}}>{err}</div>}
          <div style={{display:"flex", justifyContent:"flex-end", gap:8, marginTop:6}}>
            <button className="btn sm" onClick={onClose} disabled={busy}>cancel</button>
            <button className="btn sm primary" onClick={submit}
                    disabled={busy || !form.name.trim() || !form.role.trim()}>
              {busy ? "creating…" : "create agent"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// MODIFY an existing, editable agent (issue #84 item 3). Fetches the editability
// gate + current field values on open; a frozen / guardian agent shows a lock
// message instead of the form. Save forks-on-first-edit for a commons agent
// (transparent) and surfaces item-8 integrity warnings inline.
function ModifyAgentModal({ name, onClose }) {
  const [ctx, setCtx]     = useState(null);
  const [form, setForm]   = useState({ ...EMPTY_WIZ });
  const [busy, setBusy]   = useState(false);
  const [err, setErr]     = useState(null);
  const [warn, setWarn]   = useState([]);
  const set = k => e => setForm({ ...form, [k]: e.target.value });

  React.useEffect(() => {
    let live = true;
    getJSON("/api/agent_edit/" + encodeURIComponent(name)).then(c => {
      if (!live) return;
      setCtx(c);
      const f = c.fields || {};
      setForm({
        ...EMPTY_WIZ, name: c.name, role: f.role || "",
        required_tools: (f.required_tools || []).join(", "),
        denied_tools: (f.denied_tools || []).join(", "),
        model: f.model || "",
      });
    }).catch(ex => live && setErr(String(ex.message || ex)));
    return () => { live = false; };
  }, [name]);

  const submit = async () => {
    setBusy(true); setErr(null); setWarn([]);
    try {
      const body = { role: form.role, allow_warn: true };
      body.required_tools = wizTools(form.required_tools);
      body.denied_tools = wizTools(form.denied_tools);
      if (form.model) body.model = form.model;
      if (form.responsibilities.trim()) body.responsibilities = form.responsibilities;
      if (form.non_goals.trim()) body.non_goals = form.non_goals;
      if (form.persona.trim()) body.persona = form.persona;
      if (form.output_format.trim()) body.output_format = form.output_format;
      if (form.guardrails.trim()) body.guardrails = form.guardrails;
      if (form.example.trim()) body.example = form.example;
      if (form.verdict.trim()) body.verdict = form.verdict;
      const res = await postJSON("/api/agent_edit/" + encodeURIComponent(name), body);
      if (res.warnings && res.warnings.length) { setWarn(res.warnings); setBusy(false); return; }
      await refreshDashboard();
      onClose();
    } catch (ex) { setErr(String(ex.message || ex)); setBusy(false); }
  };

  const locked = ctx && !ctx.editable;
  return (
    <div onClick={onClose} style={MODAL_BACKDROP_STYLE}>
      <div onClick={e => e.stopPropagation()} style={{...MODAL_PANEL_STYLE, maxWidth:640, maxHeight:"85vh", overflowY:"auto"}}>
        <div style={{background:"var(--paper-2)", borderBottom:"1px solid var(--rule)", padding:"12px 16px"}}>
          <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:17, color:"var(--purple-deep)"}}>
            Modify agent · <code className="mono">{name}</code>
          </h2>
          {ctx && ctx.origin === "commons" && !locked && (
            <div className="muted" style={{fontSize:12, marginTop:3}}>
              Editing a commons agent forks it into your vault on first save, so
              your changes survive commons upgrades and sync across machines.
              <span style={{marginLeft:4}}>Locked: {(ctx.locked_fields||[]).join(", ")}.</span>
            </div>
          )}
        </div>
        <div style={{padding:16}}>
          {!ctx && !err && <div className="muted" style={{fontSize:13}}>loading…</div>}
          {locked && (
            <div style={{padding:"10px 12px", border:"1px solid var(--rule-strong)", borderRadius:3,
                         background:"var(--paper-2)", fontSize:13, color:"var(--red)"}}>
              🔒 {ctx.reason}
            </div>
          )}
          {ctx && !locked && (
            <div>
              <AgentWizardFields form={form} set={set} locked={true} />
              {ctx.diff_vs_commons && (
                <details style={{marginBottom:10}}>
                  <summary className="mono muted" style={{fontSize:11, cursor:"pointer"}}>
                    diff vs commons
                  </summary>
                  <pre className="mono" style={{fontSize:10, maxHeight:180, overflow:"auto",
                       background:"var(--paper-2)", padding:8, border:"1px solid var(--rule)"}}>
                    {ctx.diff_vs_commons}
                  </pre>
                </details>
              )}
              {warn.length > 0 && (
                <div style={{marginBottom:10, padding:"8px 10px", border:"1px solid var(--amber, #b8860b)",
                             borderRadius:3, fontSize:12}}>
                  <b>Integrity warnings</b> (saved anyway):
                  <ul style={{margin:"4px 0 0 16px", padding:0}}>
                    {warn.map((w, i) => <li key={i}><code className="mono">{w.rule}</code> — {w.detail}</li>)}
                  </ul>
                </div>
              )}
            </div>
          )}
          {err && <div style={{color:"var(--red)", fontSize:12, marginTop:8}}>{err}</div>}
          <div style={{display:"flex", justifyContent:"flex-end", gap:8, marginTop:10}}>
            <button className="btn sm" onClick={onClose} disabled={busy}>close</button>
            {ctx && !locked && (
              <button className="btn sm primary" onClick={submit} disabled={busy || !form.role.trim()}>
                {busy ? "saving…" : "save changes"}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function AgentsPanel({ agents, span="c-4" }) {
  const list = agents || [];
  const [modal, setModal] = useState(false);
  // Two axes (#38): origin (commons vs personal) and, for commons, category
  // (member / administrative / choreography-support). freeze stays orthogonal.
  const commons  = list.filter(a => (a.origin || "commons") === "commons");
  const personal = list.filter(a => a.origin === "personal");
  const byCat = c => commons.filter(a => (a.category || "member") === c);
  return (
    <div className={"panel "+span}>
      <header>
        <h2>Agents</h2>
        <span className="meta" style={{display:"flex", alignItems:"center", gap:8}}>
          {commons.length} commons · {personal.length} personal · {list.filter(a => a.disabled).length} disabled
          <button className="btn sm" onClick={() => setModal(true)}
                  title="Create your own agent — kept in your vault, loaded by Claude Code">
            + new
          </button>
        </span>
      </header>
      <div className="body" style={{padding:0}}>
        <AgentGroup title="Member" agents={byCat("member")} />
        <AgentGroup title="Administrative" agents={byCat("administrative")} />
        <AgentGroup title="Choreography support" agents={byCat("choreography-support")} />
        <AgentGroup title="Personal agents"
          hint="— yours; kept in your vault, backed to your GitHub"
          agents={personal} />
        {personal.length === 0 && list.length > 0 && (
          <div className="muted" style={{padding:"10px 14px", fontSize:12, borderTop:"1px solid var(--rule)"}}>
            No personal agents yet. Click <b>+ new</b> to create your own (or{" "}
            <code className="mono">murmurent agent new &lt;name&gt;</code>); fork a
            commons agent with <code className="mono">murmurent agent fork &lt;name&gt;</code>.
            Either way it lives in your vault only and is backed up to your GitHub.
          </div>
        )}
        {list.length === 0 && (
          <div className="muted" style={{padding:"14px", fontSize:13}}>
            No agents installed. Run <code className="mono">murmurent agent list</code>.
          </div>
        )}
      </div>
      {modal && <NewPersonalAgentModal onClose={() => setModal(false)} />}
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
  // Stored as the request's ``justification`` field; shown to the user as
  // "description" (#185 item 10).
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  // Approval results when the PI creates a project directly (#185 item 11).
  const [probes, setProbes] = useState(null);
  const isPI = (window.DATA.persona || "member") === "pi";
  const groupMembers = window.DATA.group_members || [];
  // Slack channel name override. Empty = murmurent default of
  // ``proj-<project>``. The placeholder updates live as the user types
  // the project name so it's obvious what will be created if they
  // leave this blank. Validation is server-side (normalize_channel_name).
  const [slackChannelName, setSlackChannelName] = useState("");
  // A project is a set of EXISTING repos + members. ``attachRepos`` is the
  // repo set, picked from the clones on this machine; creating a project never
  // scaffolds a new repo. The Machines picker was removed in #185: only this
  // machine was ever used. On approval each chosen repo is made
  // murmurent-ready automatically (core.requests._make_ready_quietly).
  const [repoOptions, setRepoOptions] = useState([]);
  const [repoScan, setRepoScan] = useState({ loading: true, errors: [] });
  const [attachRepos, setAttachRepos] = useState([]);
  useEffect(() => {
    let cancelled = false;
    // refresh=true: rescan this machine now. The cached report can be up to a
    // week old, which showed "no repos found" on a machine full of repos (#185).
    fetch("/api/inventory/repos?refresh=true", { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(r => r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status)))
      .then(j => {
        if (cancelled) return;
        setRepoScan({ loading: false, errors: (j.errors || []).map(String) });
        const opts = [];
        for (const row of (j.rows || [])) {
          const nm = (row && row.name) || "";
          const clones = (row && row.clones) || [];
          if (!nm || rowIsMurmurentInfra(row) || opts.some(o => o.name === nm)) continue;
          if (clones.length > 0) {
            opts.push({ name: nm, hosts: [...new Set(clones.map(c => c.host))] });
          } else if (row.github && row.github.full_name) {
            // On GitHub only (#185 item 8): copied to this machine when the
            // project is created.
            opts.push({ name: nm, hosts: [], github: row.github.full_name });
          }
        }
        setRepoOptions(opts);
      })
      .catch(ex => {
        if (!cancelled) setRepoScan({ loading: false, errors: [String(ex.message || ex)] });
      });
    return () => { cancelled = true; };
  }, []);
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
      const filed = await postCreateProjectRequest({
        project: name.trim(),
        proposed_members: selectedMembers,
        sensitivity,
        justification: description.trim(),
        host: "local",
        machines: ["local"],
        attach_repos: attachRepos,
        slack_channel_name: slackChannelName.trim() || null,
        slack_workspace: slackWorkspace.trim() || null,
      });
      // The PI's own project needs no approval step: approve it straight
      // away so "create" means create. A member's project still waits for
      // the PI (#185 item 11).
      let out = null;
      if (isPI && filed.request && filed.request.id != null) {
        out = await postRequestAction(filed.request.id, "approve");
      }
      if (typeof window.__murmurentFetchData === "function") {
        await window.__murmurentFetchData(window.DATA.persona);
      }
      // Stay open only when a step needs the PI's attention.
      if (out && out.probes && out.probes.some(pr => pr.status !== "ok")) {
        setProbes(out.probes);
        return;
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
      padding:"40px 20px", overflowY:"auto",
    }}>
      <form onSubmit={submit} onClick={e => e.stopPropagation()} style={{
        background:"var(--card)", border:"1px solid var(--rule-strong)",
        borderRadius:2, padding:18, width:"min(560px, 92vw)",
        display:"flex", flexDirection:"column", gap:8,
        maxHeight:"90vh", overflowY:"auto",
      }}>
        <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:18, color:"var(--purple-deep)"}}>
          Create new project
        </h2>
        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase", marginTop:6}}>name (snake_case)</label>
        <input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. new_project"
               style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2, fontFamily:"var(--mono)"}}/>

        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase"}}>description</label>
        <textarea value={description} onChange={e => setDescription(e.target.value)}
                  rows={3} placeholder="What the project is about."
                  style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2, fontFamily:"var(--serif)", fontSize:14}}/>

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
        {/* chips: already-selected handles. Bounded + scrolls so adding many
            members doesn't push the repo picker + lower sections out of view,
            and flexShrink:0 stops the flex-column form from collapsing it (#51). */}
        {selectedMembers.length > 0 && (
          <div className="row" style={{flexWrap:"wrap", gap:4, maxHeight:96,
                                       overflowY:"auto", flexShrink:0}}>
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
                   placeholder="e.g. lab_ws  (or a dedicated shared workspace id)"
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

        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase", marginTop:6}}>repos (select at least one)</label>
        <div className="muted" style={{fontSize:11, marginTop:-2, marginBottom:2, lineHeight:1.5}}>
          Pick the repos that belong to the project: on this machine, or in the
          lab's GitHub organisation (those are copied here when the project is
          created). Each one is made murmurent-ready for you. Creating a project
          never creates a new repo.
        </div>
        {repoScan.loading ? (
          <div className="muted" style={{fontSize:11}}>Looking for repos on this machine…</div>
        ) : repoOptions.length === 0 ? (
          <div className="muted" style={{fontSize:11, lineHeight:1.5}}>
            No repos found on this machine. murmurent looks in your repositories
            folder (<code>murmurent config repos-root</code> prints it) and any
            folders added under ⚙ Machines.
            {repoScan.errors.length > 0 && (
              <div style={{color:"var(--red)", marginTop:4}}>
                The search reported: {repoScan.errors.join("; ")}
              </div>
            )}
          </div>
        ) : (
          <div style={{display:"flex", flexWrap:"wrap", gap:6, maxHeight:140,
                       minHeight:64, overflowY:"auto", flexShrink:0}}>
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
                    {opt.github
                      ? "(on GitHub; copied here when the project is created)"
                      : "(" + ((opt.hosts || []).join(", ") || "?") + ")"}
                  </span>
                </label>
              );
            })}
          </div>
        )}

        {probes && (
          <div style={{fontSize:12, lineHeight:1.5, border:"1px solid var(--rule-strong)", padding:"6px 8px"}}>
            <div style={{fontWeight:600, marginBottom:2}}>Project created. Some steps need attention:</div>
            {probes.filter(pr => pr.status !== "ok").map((pr, i) => (
              <div key={i}><span className="mono">{pr.name}</span>: {pr.detail}</div>
            ))}
          </div>
        )}
        {err && <div style={{color:"var(--red)", fontSize:12}}>{err}</div>}
        <div className="row" style={{justifyContent:"flex-end", gap:6, marginTop:6}}>
          {!isPI && (
            <span className="muted" style={{fontSize:11, marginRight:"auto", alignSelf:"center"}}>
              Your PI confirms new projects before they are set up.
            </span>
          )}
          <button type="button" className="btn sm ghost" onClick={onClose}>
            {probes ? "close" : "cancel"}
          </button>
          {!probes && (
            <button type="submit" className="btn sm primary" disabled={busy}>
              {busy ? "…" : "create"}
            </button>
          )}
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
      {isCreate && (req.attach_repos && req.attach_repos.length > 0) && (
        <div className="mono muted" style={{fontSize:11, marginTop:2}}>
          repos: {req.attach_repos.join(", ")}
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
      padding:"40px 20px", overflowY:"auto",
    }}>
      <form onSubmit={submit} onClick={e => e.stopPropagation()} style={{
        background:"var(--card)", border:"1px solid var(--rule-strong)",
        borderRadius:2, padding:18, width:"min(560px, 92vw)",
        display:"flex", flexDirection:"column", gap:8,
        maxHeight:"90vh", overflowY:"auto",
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
               placeholder="Bulk RNA-seq alignment"
               style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2}}/>
        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase"}}>kind</label>
        <select value={kind} onChange={e => setKind(e.target.value)}
                style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2, fontFamily:"var(--mono)"}}>
          <option value="skill">skill</option>
          <option value="experiment">experiment</option>
          <option value="analysis">analysis</option>
        </select>
        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase"}}>contact (member who owns it)</label>
        <input value={contact} onChange={e => setContact(e.target.value)} placeholder="@handle"
               style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2, fontFamily:"var(--mono)"}}/>
        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase"}}>turnaround (days, optional)</label>
        <input value={turnaround} onChange={e => setTurnaround(e.target.value)} placeholder="7"
               type="number" min="0" style={{padding:"6px 8px", border:"1px solid var(--rule-strong)", borderRadius:2, fontFamily:"var(--mono)", width:120}}/>
        <label className="mono muted" style={{fontSize:11, letterSpacing:1, textTransform:"uppercase"}}>prerequisites (comma-separated)</label>
        <input value={prereqs} onChange={e => setPrereqs(e.target.value)} placeholder="reference genome, input files"
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

/* ───────── Centre projects (centre_millwright front door, item 0e) ─────────
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
  // Personal-vault git freshness ({is_git, ok, detail, as_of}) + ff-only pull.
  const [vault, setVault] = useState(null);
  const [vaultBusy, setVaultBusy] = useState(false);
  useEffect(() => { getVaultInfo().then(setVault).catch(() => {}); }, []);
  const onVaultUpdate = async () => {
    setVaultBusy(true);
    try {
      const r = await postVaultRefresh();
      setVault(r);
      if (r.is_git && !r.ok) {
        alert("Vault pull failed: " + (r.detail || "unknown error") +
              "\n\nShowing the cached vault from " + (r.as_of ? r.as_of.slice(0, 10) : "an unknown date") + ".");
      }
      if (typeof window.__murmurentFetchData === "function") {
        try { await window.__murmurentFetchData(window.DATA.persona); } catch (_) {}
      }
    } catch (ex) { alert(ex.message || ex); }
    finally { setVaultBusy(false); }
  };
  return (
    <div className={"panel "+span}>
      <header>
        <h2>Oracle · personal</h2>
        <div className="row" style={{gap:6, alignItems:"center"}}>
          {vault && vault.as_of && (
            <span className="meta" title={"personal vault from " + (vault.path || "murmurent_vault") + ", last commit " + vault.as_of}>
              {"as of " + vault.as_of.slice(0, 10)}
            </span>
          )}
          {vault && vault.is_git && (
            <button className="btn sm" disabled={vaultBusy} onClick={onVaultUpdate}
                    title="Pull your personal vault (--ff-only) from GitHub, then refresh this panel">
              {vaultBusy ? "…" : "update"}
            </button>
          )}
          <span style={{fontFamily:"var(--mono)", fontSize:10, letterSpacing:0.5,
                padding:"1px 6px", borderRadius:2, color:hs.color,
                background:hs.bg, border:"1px solid "+hs.bd}}
                title={vh.path ? "vault oracle dir: "+vh.path : "no vault registered"}>
            {hs.chip}
          </span>
        </div>
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
  const labProviders = (window.DATA.lab_settings || {}).git_providers || [];
  const [form, setForm] = useState({
    // Handles — per-person, machine-independent identities.
    official_handle: initial.official_handle || "",
    slack_handle:    initial.slack_handle    || "",
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
      // The Handles-section "github handle" is the single source of truth for
      // GitHub (issue #23 — the duplicate provider field was removed). Mirror
      // it into git_logins.github before saving, else the backend's git_logins
      // sync would overwrite contact.github with a stale value.
      const gh = (form.github || "").trim().replace(/^@/, "");
      const git_logins = { ...form.git_logins };
      if (gh) git_logins.github = gh; else delete git_logins.github;
      const payload = { ...form, github: gh, git_logins };
      // Keep the viewer's identity (?user=) so the save lands on the record
      // this page is showing, not the server user's (#185).
      const userParam = new URLSearchParams(window.location.search).get("user");
      const res = await fetch("/api/member/settings" + (userParam ? "?user=" + encodeURIComponent(userParam) : ""), {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || ("HTTP " + res.status));
      }
      const body = await res.json();
      setProbes(body.probes || []);
      // A member's edit is only staged on this computer; say so rather than
      // a bare "saved" (#185).
      setMsg(body.staged ? (body.message || "saved on this computer only") : "saved");
      if (body.staged) {
        if (typeof window.__murmurentFetchData === "function") {
          try { await window.__murmurentFetchData(window.DATA.persona); } catch (_) {}
        }
        return;
      }
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
            Personal Profile
          </h2>
          <button type="button" className="btn sm ghost" onClick={onClose}>✕ close</button>
        </div>
        <p className="muted" style={{fontSize:12, margin:"4px 0 0", lineHeight:1.5}}>
          <strong>You, on all your machines.</strong>{" "}
          {(window.DATA.persona || "member") === "pi"
            ? <>Saved to your entry in the lab roster
                (<code>&lt;lab-mgmt&gt;/members/&lt;handle&gt;.md</code>) and pushed,
                so your other machines and the lab see it.</>
            : <>Saved in your personal vault, so your other machines get it, and
                sent to your PI, who adds it to the lab roster with
                <code> murmurent reconcile</code>.</>}
          {" "}Folders on this computer are in <strong>Machine settings</strong>.
        </p>

        {/* Identity (read-only) */}
        <div style={sectionStyle}>
          <h4 style={sectionHeader}>Identity</h4>
          <div className="row" style={{flexWrap:"wrap", gap:14, marginTop:6, fontSize:13}}>
            <div><span className="muted">name</span> {_displayMemberName(m)}</div>
            <div><span className="muted">role</span> {_displayRole(m.role)}</div>
            <div><span className="muted">lab</span> {_displayLab(m.lab)}</div>
          </div>
        </div>

        {/* Handles — per-person, machine-independent identities. The
            username you log in with on a given computer is machine-dependent
            and lives in Machine settings, not here. */}
        <div style={sectionStyle}>
          <h4 style={sectionHeader}>Handles</h4>
          <div className="row" style={{gap:10, marginTop:4}}>
            <div style={{flex:1}}>
              <div style={labelStyle}>official handle</div>
              <input style={inputStyle} value={form.official_handle}
                     onChange={update("official_handle")}
                     placeholder="e.g. jdoe (your institutional netname)" />
            </div>
            <div style={{flex:1}}>
              <div style={labelStyle}>murmurent handle</div>
              <input style={{...inputStyle, background:"var(--paper-2)", color:"var(--muted)"}}
                     value={m.handle || ""} readOnly disabled />
            </div>
          </div>
          <div className="row" style={{gap:10, marginTop:4}}>
            <div style={{flex:1}}>
              <div style={labelStyle}>slack handle</div>
              <input style={inputStyle} value={form.slack_handle}
                     onChange={update("slack_handle")}
                     placeholder="your-slack-username" />
            </div>
            <div style={{flex:1}}>
              <div style={labelStyle}>github handle</div>
              <input style={inputStyle} value={form.github} onChange={update("github")}
                     placeholder="your-github-username" />
            </div>
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
              <div style={labelStyle}>OSF</div>
              <input style={inputStyle} value={form.osf} onChange={update("osf")} />
            </div>
            <div style={{flex:1}}></div>
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

        {/* Per-provider git logins for NON-github providers only. GitHub is
            set once in the Handles section above (issue #23) — excluded here so
            it isn't a duplicate field. The section hides entirely when the lab
            has no other providers (the common github-only case). */}
        {(() => {
          const others = labProviders.filter(p => p.kind !== "github");
          if (others.length === 0) return null;
          return (
            <div style={sectionStyle}>
              <h4 style={sectionHeader}>Other git logins</h4>
              <div style={{fontSize:11, color:"var(--muted)", marginTop:3, marginBottom:6, lineHeight:1.5}}>
                Your username on the lab's other git providers. The PI uses these
                to add you as a collaborator when you join a project.
              </div>
              {others.map((p) => (
                <div key={p.id} style={{marginTop:6}}>
                  <div style={labelStyle}>
                    {p.label || `${p.kind}${p.target ? " · " + p.target : ""}`}
                    <span style={{textTransform:"none", letterSpacing:0, color:"var(--muted)", marginLeft:6}}>
                      ({p.id})
                    </span>
                  </div>
                  <input style={inputStyle}
                         value={form.git_logins[p.id] || ""}
                         placeholder={p.kind === "gitea" ? "your-gitea-username" :
                                      "(local-bare: not needed)"}
                         disabled={p.kind === "local-bare"}
                         onChange={(e) => setForm(prev => ({
                           ...prev,
                           git_logins: { ...prev.git_logins, [p.id]: e.target.value },
                         }))} />
                </div>
              ))}
            </div>
          );
        })()}

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

/* Issue #94: HostsModal (the "Install hosts" register/probe/remove modal) and
   HostAddForm (its "Add SSH host" form) were removed with the retired "add
   machine / SSH repo scan" flow. They were the only callers of POST /api/hosts
   and POST /api/hosts/{name}/test. The repo manager is this-machine-only now;
   view another machine via its own dashboard (docs/remote_dashboard.md). */

/* ───────── Read-only cross-machine view (issue #80) ─────────
   Each machine mirrors its OWN config to <vault>/machines/<id>.yaml; the vault
   syncs those across the member's machines. This panel READS them (plus the
   repo-inventory SSH scan) so you can SEE your other machines — display only,
   never editing a foreign machine's params (those are edited on that machine's
   own dashboard). */
function OtherMachinesView() {
  const [machines, setMachines] = useState([]);
  const [thisId, setThisId] = useState("");
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    fetch("/api/machines/registry", { headers: { Accept: "application/json" } })
      .then(r => r.ok ? r.json() : { machines: [] })
      .then(d => { setMachines(d.machines || []); setThisId(d.this_machine_id || ""); })
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);
  const others = machines.filter(m => (m.machine_id || "") !== thisId);
  if (!loaded) return null;
  // Hide this section entirely when no other machines are mirrored yet — no
  // verbose empty-state placeholder (maintainer request).
  if (others.length === 0) return null;
  const lbl = {fontFamily:"var(--mono)", fontSize:10, letterSpacing:1,
               textTransform:"uppercase", color:"var(--muted)", width:96,
               display:"inline-block"};
  return (
    <div style={{marginTop:14}}>
      <div style={{fontFamily:"var(--serif)", fontSize:14, marginBottom:2}}>
        Your other machines <span className="muted" style={{fontSize:11}}>· synced, read-only</span>
      </div>
      {(
        <div style={{display:"flex", flexWrap:"wrap", gap:10}}>
          {others.map(m => (
            <div key={m.machine_id} style={{
              flex:"1 1 calc(50% - 5px)", minWidth:230,
              border:"1px solid var(--rule-strong)", borderRadius:2,
              padding:"10px 12px", background:"var(--paper-2)",
            }}>
              <div style={{fontFamily:"var(--serif)", fontSize:14}}>
                {m.machine_name || m.machine_id}
                {m.platform && <Pill tone="purple">{m.platform}</Pill>}
              </div>
              <div style={{marginTop:6, fontSize:11.5, lineHeight:1.7}}>
                <div><span style={lbl}>data root</span>
                  <code className="mono">{m.wigamig_base || "—"}</code></div>
                <div><span style={lbl}>vault</span>
                  <code className="mono">{m.obsidian_vault_path || "—"}</code></div>
                {m.updated && <div><span style={lbl}>updated</span>
                  <span className="muted">{String(m.updated).slice(0, 10)}</span></div>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ───────── Machines modal ─────────
   THIS-machine view (issue #94): shows the current machine as a card and lets
   the user edit its data-root + Obsidian vault. Other machines are shown
   read-only via the vault mirror (OtherMachinesView) — the retired "add
   machine / SSH repo scan" section is gone; view another machine on its own
   dashboard (docs/remote_dashboard.md).

   Storage: the current machine's settings live in ~/.murmurent/machine.yaml
   (loaded into window.DATA.machine_settings); its local row (scan_dirs) is
   fetched from /api/hosts on mount. */

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
          <strong style={{fontFamily:"var(--serif)", fontSize:15}}>{machine.display_name || machine.name}</strong>
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
      {/* Per-machine locations. Two vaults (issue #25):
            • PERSONAL vault — the member's own ``murmurent_vault`` clone;
              its oracle/ + lab-notebook/ subfolders are shown resolved.
            • LAB (group) vault — the lab-mgmt clone (``murmurent_lab_mgmt_<lab>``);
              its oracle/ + lab-notebook/ subfolders are shown resolved.
          Then Files (raw/ + refined/ live under it) and Repo location.
          The personal vault is editable here; the lab vault clone location is
          the lab-mgmt clone, managed at install / via the lab_mgmt pin. */}
      <div style={{marginTop:8, fontSize:12, lineHeight:1.7}}>
        {/* Personal vault — root shown ONCE, then oracle/ + lab-notebook/ +
            murmurent_data/ as bare indented extensions (issue #99 §1–2). */}
        <div><span style={labelStyle}>Personal vault</span>
          <code className="mono">{!_pathUnset(machine.obsidian_vault_path)
            ? machine.obsidian_vault_path
            : (machine.obsidian_vault_name || <span className="muted">—</span>)}</code></div>
        {_pathUnset(machine.obsidian_vault_path)
          ? <NoRootLine label="personal vault" />
          : <PathTree root={machine.obsidian_vault_path} children={[
              machine.oracle_subfolder || "oracle",
              machine.notebook_subfolder || "lab-notebook",
              machine.murmurent_data_subfolder || "murmurent_data",
            ]} />}
        {/* Lab (group) vault — the lab-mgmt clone; same root-once + tree. */}
        <div><span style={labelStyle}>Lab vault</span>
          <code className="mono">{!_pathUnset(machine.lab_vault_path)
            ? machine.lab_vault_path : <span className="muted">—</span>}</code>
          {!_pathUnset(machine.lab_vault_path) &&
            <span className="muted" style={{fontSize:10, marginLeft:6}}>(lab-mgmt clone)</span>}</div>
        {_pathUnset(machine.lab_vault_path)
          ? <NoRootLine label="lab vault" />
          : <PathTree root={machine.lab_vault_path} children={[
              "oracle", "lab-notebook",
              machine.murmurent_data_subfolder || "murmurent_data",
            ]} />}
        {/* Files (data root) — its two governed children (resolved
            immutable/append_only, or legacy raw/refined) nested underneath
            (issue #80 Part 1a). */}
        <div><span style={labelStyle}>Files</span>
          <code className="mono">{!_pathUnset(wb) ? wb : <span className="muted">—</span>}</code></div>
        {_pathUnset(wb)
          ? <NoRootLine label="data root" />
          : <PathTree root={wb} children={[
              machine.data_immutable_name || "immutable",
              machine.data_append_only_name || "append_only",
            ]} />}
        <div><span style={labelStyle}>Repo location</span>
          <code className="mono">{scanDirs.length === 0
            ? <span className="muted">default (~/repo + ~/repos)</span>
            : scanDirs.join(", ")}</code></div>
      </div>
    </div>
  );
}

// One-click "Sync vault" affordance for THIS machine (issue #80 Wave 3, Part A).
// Push local vault edits, then ff-pull what other machines pushed. Surfaces the
// "as of <date>" freshness stamp, and — crucially — turns a --ff-only refusal
// into a calm, non-alarming "vault diverged, reconcile there" banner rather
// than an error. Never auto-merges or forces. Degrades to a plain notice when
// no personal vault is adopted on this machine.
function VaultSyncControl({ vaultPath }) {
  const hasVault = vaultPath && String(vaultPath).trim() &&
                   String(vaultPath).trim().toLowerCase() !== "na";
  const [busy, setBusy] = useState(false);
  const [asOf, setAsOf] = useState("");
  const [result, setResult] = useState(null);   // {pushed, pulled, diverged, message, as_of}

  useEffect(() => {
    if (!hasVault) return;
    getVaultInfo().then(v => setAsOf(v && v.as_of ? v.as_of : "")).catch(() => {});
  }, [hasVault, vaultPath]);

  if (!hasVault) {
    return (
      <div style={{marginTop:8, fontSize:11, color:"var(--muted)"}}>
        No personal vault on this machine — nothing to sync. Set a vault path above (or run
        {" "}<code className="mono">murmurent vault init</code>) to enable one-click sync.
      </div>
    );
  }

  const sync = async () => {
    setBusy(true); setResult(null);
    try {
      const r = await postVaultSync();
      setResult(r);
      if (r && r.as_of) setAsOf(r.as_of);
    } catch (ex) {
      setResult({ diverged:false, pushed:false, pulled:false,
                  message:String(ex.message || ex) });
    } finally { setBusy(false); }
  };

  const diverged = result && result.diverged;
  const stamp = (result && result.as_of) || asOf;

  return (
    <div style={{marginTop:8}}>
      <div className="row" style={{gap:10, alignItems:"baseline"}}>
        <button type="button" className="btn sm" onClick={sync} disabled={busy}>
          {busy ? "syncing…" : "⇅ Sync vault"}
        </button>
        <span style={{fontSize:11, color:"var(--muted)"}}>
          push local edits, then ff-pull other machines
          {stamp && <span title={"last commit " + stamp}>{" · as of " + stamp.slice(0, 10)}</span>}
        </span>
      </div>
      {diverged && (
        // Non-alarming amber (not red): this is expected when you edit two
        // machines without pushing. We NEVER auto-merge; the fix is on the
        // other machine.
        <div style={{
          marginTop:8, padding:"8px 10px", borderRadius:2,
          background:"rgba(214,140,40,0.10)", border:"1px solid var(--tiger)",
          fontSize:12, color:"var(--ink)",
        }}>
          <strong>Vault diverged</strong> — you have unsynced edits on another machine.
          Reconcile there (push), then sync here. Murmurent will not auto-merge or force.
        </div>
      )}
      {result && !diverged && (
        <div style={{marginTop:6, fontSize:11, color:"var(--muted)", fontFamily:"var(--mono)"}}>
          {result.message}
        </div>
      )}
    </div>
  );
}

function ThisMachineEditor({ initial, onSaved, onCancel }) {
  const [form, setForm] = useState({
    machine_name:        initial.machine_name        || "",
    wigamig_base:        initial.wigamig_base        || "~/wigamig",
    obsidian_vault_path: initial.obsidian_vault_path || "",
    obsidian_vault_name: initial.obsidian_vault_name || "",
    notebook_subfolder:  initial.notebook_subfolder  || "lab-notebook",
    oracle_subfolder:    initial.oracle_subfolder    || "oracle",
    murmurent_data_subfolder: initial.murmurent_data_subfolder || "murmurent_data",
    repos_root:          initial.repos_root          || "",
  });
  // Repo location (scan_dirs) is stored on the host registry, not machine.yaml,
  // so it's a separate field + a second save call.
  const [repos, setRepos] = useState((initial.scan_dirs || []).join("\n"));
  // SSH host + username live on the host registry (hosts.yaml). For this
  // machine they're optional metadata — how OTHER machines reach it — and are
  // ignored when the machine talks to itself. Username defaults to the OS user.
  const [conn, setConn] = useState({
    ssh_host:    initial.ssh_host    || "",
    remote_user: initial.remote_user || initial.local_user || "",
  });
  const hostname = initial.hostname || "local";
  // Lab (group) vault clone = the lab-mgmt clone (issue #25). Read-only here:
  // its location is the resolved lab_mgmt_path, not a machine.yaml field.
  const labVaultPath = initial.lab_vault_path
    || ((window.DATA.lab_settings || {}).lab_mgmt_path || "");
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
      // Also persist the host-registry fields (connection + Repo locations) to
      // the local row. Same endpoint the remote-machine editor uses.
      try {
        const scan_dirs = repos.split("\n").map(s => s.trim()).filter(Boolean);
        await fetch("/api/hosts/local", {
          method: "PATCH",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({
            ssh_host: conn.ssh_host.trim(),
            remote_user: conn.remote_user.trim(),
            scan_dirs,
          }),
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

  const inputStyle = {
    padding:"5px 8px", border:"1px solid var(--rule-strong)",
    borderRadius:2, fontFamily:"var(--mono)", fontSize:12, width:"100%",
    boxSizing:"border-box",
  };
  const labelStyle = {
    fontFamily:"var(--mono)", fontSize:10, letterSpacing:1,
    textTransform:"uppercase", color:"var(--muted)", marginTop:6, marginBottom:2,
  };

  return (
    <form onSubmit={submit} style={{
      border:"1px solid var(--rule-strong)", borderRadius:2,
      padding:"10px 14px", background:"var(--paper)",
    }}>
      <div className="row" style={{justifyContent:"space-between", alignItems:"baseline"}}>
        <strong style={{fontFamily:"var(--serif)"}}>Edit this machine</strong>
        <button type="button" className="btn sm ghost" onClick={onCancel}>cancel</button>
      </div>

      <div style={labelStyle}>name (short id)</div>
      <input style={inputStyle} value={form.machine_name}
             onChange={update("machine_name")} placeholder={hostname} />

      <div style={labelStyle}>SSH host — optional; only if other machines reach this one over SSH</div>
      <input style={inputStyle} value={conn.ssh_host}
             onChange={e => setConn(c => ({...c, ssh_host: e.target.value}))}
             placeholder="(none — this is your local machine)" />

      <div style={labelStyle}>username on this machine</div>
      <input style={inputStyle} value={conn.remote_user}
             onChange={e => setConn(c => ({...c, remote_user: e.target.value}))}
             placeholder="jdoe" />

      <div style={labelStyle}>Large file location</div>
      <input style={inputStyle} value={form.wigamig_base}
             onChange={update("wigamig_base")} placeholder="~/wigamig" />
      {/* Files (data root) governed children, shown once as a tree (issue #80
          Part 1a). Names resolve server-side on save; the preview shows the
          canonical immutable/append_only. */}
      {!_pathUnset(form.wigamig_base) && (
        <div style={{marginTop:4}}>
          <PathTree indent={0} root={form.wigamig_base} children={[
            initial.data_immutable_name || "immutable",
            initial.data_append_only_name || "append_only",
          ]} />
        </div>
      )}

      <div style={labelStyle}>Repositories folder (where murmurent puts and finds your repositories)</div>
      <input style={inputStyle} value={form.repos_root}
             onChange={update("repos_root")} placeholder="~/repos   (or ~/repo, ~/repositories, ...)" />

      <div style={labelStyle}>Other places to look for repositories (one per line; optional)</div>
      <textarea style={{...inputStyle, minHeight:54, resize:"vertical"}} value={repos}
                onChange={e => setRepos(e.target.value)} placeholder={"~/repos\nwork/clones"} />

      <div style={{...labelStyle, marginTop:14, color:"var(--ink)", fontSize:11}}>
        Personal vault <span style={{textTransform:"none", letterSpacing:0, color:"var(--muted)"}}>
          — your own <code className="mono">murmurent_vault</code> clone on THIS machine (identity: your GitHub, set in Profile)
        </span>
      </div>
      <div style={labelStyle}>vault path (full path, or NA if none on this machine)</div>
      <input style={inputStyle} value={form.obsidian_vault_path}
             onChange={update("obsidian_vault_path")}
             placeholder="/Users/you/.../murmurent_vault   (or NA)" />

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
        <div style={{flex:1}}>
          <div style={labelStyle}>murmurent_data subfolder</div>
          <input style={inputStyle} value={form.murmurent_data_subfolder}
                 onChange={update("murmurent_data_subfolder")} />
        </div>
      </div>
      {/* Resolved personal-vault subfolders — the issue's #1 gripe was that
          these were invisible / repeated the full root on every line. Show the
          bare extensions as a tree (root is the input above); full path on
          hover. murmurent_data is included per issue #99 §2. */}
      {!_pathUnset(form.obsidian_vault_path) && (
        <div style={{marginTop:4}}>
          <PathTree indent={0} root={form.obsidian_vault_path} children={[
            form.oracle_subfolder || "oracle",
            form.notebook_subfolder || "lab-notebook",
            form.murmurent_data_subfolder || "murmurent_data",
          ]} />
        </div>
      )}
      {/* One-click sync + divergence banner (issue #80 Wave 3). Reads the live
          vault path from the form so it reflects an unsaved edit. */}
      <VaultSyncControl vaultPath={form.obsidian_vault_path} />

      {/* Lab (group) vault — read-only here. It IS the lab-mgmt clone
          (murmurent_lab_mgmt_<lab>); its location is managed at install /
          via the lab_mgmt pin, and every member gets read access + auto-pull.
          Issue #25: shown so the user sees where the group oracle + lab-notebook
          resolve, without a competing per-machine path field. */}
      <div style={{...labelStyle, marginTop:14, color:"var(--ink)", fontSize:11}}>
        Lab (group) vault <span style={{textTransform:"none", letterSpacing:0, color:"var(--muted)"}}>
          — the lab-mgmt clone <code className="mono">murmurent_lab_mgmt_&lt;lab&gt;</code> (identity: the lab's GitHub, set in Lab Settings)
        </span>
      </div>
      {labVaultPath ? (
        <div style={{
          fontSize:11, color:"var(--muted)", fontFamily:"var(--mono)",
          padding:"6px 8px", background:"var(--paper-2)",
          border:"1px solid var(--rule)", borderRadius:2,
        }}>
          {/* Clone root shown once, then its subfolders as bare extensions
              (issue #99 §1–2 — includes murmurent_data). */}
          <div title={labVaultPath}>{labVaultPath}</div>
          <PathTree indent={0} root={labVaultPath} children={[
            "oracle", "lab-notebook",
            initial.murmurent_data_subfolder || "murmurent_data",
          ]} />
        </div>
      ) : (
        <div style={{fontSize:11, color:"var(--muted)"}}>
          No lab-mgmt clone resolved on this machine — clone the lab vault per docs/lab_mgmt.md.
        </div>
      )}

      {probes && probes.length > 0 && (
        <div style={{
          marginTop:12, padding:"10px 12px",
          background:"var(--paper-2)", border:"1px solid var(--rule)", borderRadius:2,
        }}>
          <div style={{fontSize:11, marginBottom:6, color:"var(--muted)"}}>
            Folder check: <strong style={{
              color: overall === "ok" ? "var(--green)" :
                     overall === "warn" ? "var(--tiger)" : "var(--red)",
            }}>{
              overall === "ok" ? "all good" :
              overall === "warn" ? "saved — see the note(s) below" :
              "needs attention"
            }</strong>
            {" "}<span style={{color:"var(--muted)"}}>
              (checks that the folders murmurent needs exist; ✗ blocks the save, ! is just a heads-up)
            </span>
          </div>
          {/* raw/ and refined/ are still created; they're just not worth a
              row each in the checklist (data-storage detail, not a knob). */}
          {probes.filter(p => p.name !== "raw" && p.name !== "refined").map(p => (
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
              <span style={{width:150, color:"var(--muted)"}}>{p.name}</span>
              <span style={{flex:1, color:"var(--ink)"}}>{p.detail}</span>
            </div>
          ))}
        </div>
      )}

      <div className="row" style={{justifyContent:"flex-end", gap:6, marginTop:10, alignItems:"baseline"}}>
        {msg && <span style={{
          fontSize:11, marginRight:"auto",
          color: msg === "saved" ? "var(--green)" : "var(--red)",
        }}>{msg}</span>}
        <button type="submit" className="btn sm primary" disabled={busy}>
          {busy ? "…" : "save changes"}
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

  // Synthesise a card for "this machine" from machine_settings. The
  // local row from /api/hosts contributes scan_dirs (the only field
  // we surface there today); the rest of the local-machine knobs are
  // owned by machine.yaml.
  const localHost = hosts.find(h => h.name === "local");
  const thisCard = {
    // Use the "local" key so onScanDirsSaved PATCHes the right row; the card
    // title shows the friendly display_name (falling back to the hostname).
    name: "local",
    display_name: ms.machine_name || thisMachine.short_hostname || "local",
    kind: "local",
    wigamig_base:        ms.wigamig_base        || "",
    obsidian_vault_path: ms.obsidian_vault_path || "",
    obsidian_vault_name: ms.obsidian_vault_name || "",
    oracle_subfolder:    ms.oracle_subfolder    || "oracle",
    notebook_subfolder:  ms.notebook_subfolder  || "lab-notebook",
    // Derived, read-only display names (issue #99 / #80 Part 1a): the fixed
    // murmurent_data vault subfolder + the resolved Files children.
    murmurent_data_subfolder: ms.murmurent_data_subfolder || "murmurent_data",
    data_immutable_name:      ms.data_immutable_name      || "immutable",
    data_append_only_name:    ms.data_append_only_name    || "append_only",
    // Lab (group) vault clone = the lab-mgmt clone (issue #25); its path is
    // the resolved lab_mgmt_path from lab settings, not a machine.yaml field.
    lab_vault_path: (window.DATA.lab_settings || {}).lab_mgmt_path || "",
    description: (thisMachine.short_hostname ? thisMachine.short_hostname + " · " : "")
                 + "OS user: " + (thisMachine.local_user || "?"),
    scan_dirs: localHost ? (localHost.scan_dirs || []) : [],
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
        display:"flex", flexDirection:"column", gap:4,
      }}>
        <div className="row" style={{justifyContent:"space-between", alignItems:"baseline"}}>
          <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:20, color:"var(--purple-deep)"}}>
            Machines
          </h2>
          <button type="button" className="btn sm ghost" onClick={onClose}>✕ close</button>
        </div>
        <p className="muted" style={{fontSize:12, margin:"4px 0 8px"}}>
          This window configures <strong>this machine only</strong> (issue #80).
          Each install configures itself and mirrors its config to the synced
          vault; your other machines are shown read-only below. Stored in
          <code>~/.murmurent/machine.yaml</code>.
        </p>

        {editingThis ? (
          <ThisMachineEditor
            initial={{ ...ms, scan_dirs: thisCard.scan_dirs,
                       ssh_host: localHost ? (localHost.ssh_host || "") : "",
                       remote_user: localHost ? (localHost.remote_user || "") : "",
                       local_user: thisMachine.local_user || "",
                       hostname: thisMachine.short_hostname || "local" }}
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

        {/* Read-only cross-machine view (synced <vault>/machines/*.yaml).
            Issue #94: this vault-mirror IS the cross-machine visibility now —
            the retired "SSH scan targets / add machine" section was removed.
            To act on another machine, open its own dashboard (docs/remote_dashboard.md). */}
        <OtherMachinesView />
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
/* Issue #94: HostEditForm (the connection editor for a foreign SSH machine)
   was removed with the retired "add machine / SSH repo scan" flow. Other
   machines are viewed read-only via the vault mirror (OtherMachinesView) and
   configured on their own dashboards (docs/remote_dashboard.md). */

function MachinesPanel({ span = "c-5" }) {
  const ms = window.DATA.machine_settings || {};
  const [thisMachine, setThisMachine] = useState({ short_hostname: "", kind: "host" });
  const [hosts, setHosts] = useState([]);
  const [loadErr, setLoadErr] = useState(null);
  const [editingThis, setEditingThis] = useState(false);

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

  const localHost = hosts.find(h => h.name === "local");
  const thisCard = {
    name: "local",
    display_name: ms.machine_name || thisMachine.short_hostname || "local",
    kind: "local",
    wigamig_base:        ms.wigamig_base        || "",
    obsidian_vault_path: ms.obsidian_vault_path || "",
    obsidian_vault_name: ms.obsidian_vault_name || "",
    oracle_subfolder:    ms.oracle_subfolder    || "oracle",
    notebook_subfolder:  ms.notebook_subfolder  || "lab-notebook",
    // Derived, read-only display names (issue #99 / #80 Part 1a): the fixed
    // murmurent_data vault subfolder + the resolved Files children.
    murmurent_data_subfolder: ms.murmurent_data_subfolder || "murmurent_data",
    data_immutable_name:      ms.data_immutable_name      || "immutable",
    data_append_only_name:    ms.data_append_only_name    || "append_only",
    // Lab (group) vault clone = the lab-mgmt clone (issue #25); its path is
    // the resolved lab_mgmt_path from lab settings, not a machine.yaml field.
    lab_vault_path: (window.DATA.lab_settings || {}).lab_mgmt_path || "",
    description: (thisMachine.short_hostname ? thisMachine.short_hostname + " · " : "")
                 + "OS user: " + (thisMachine.local_user || "?"),
    scan_dirs: localHost ? (localHost.scan_dirs || []) : [],
  };
  return (
    <div className={"panel " + span}>
      <header>
        <h2>This machine</h2>
      </header>
      <div style={{padding:"10px 14px"}}>
        {loadErr && (
          <div style={{color:"var(--red)", fontSize:12, marginBottom:8}}>
            load failed: {loadErr}
          </div>
        )}
        {/* Issue #80: the Machines window edits THIS machine only. Each install
            configures itself; other machines are shown read-only (synced from
            the vault) below. */}
        {editingThis ? (
          <ThisMachineEditor
            initial={{ ...ms, scan_dirs: thisCard.scan_dirs,
                       ssh_host: localHost ? (localHost.ssh_host || "") : "",
                       remote_user: localHost ? (localHost.remote_user || "") : "",
                       local_user: thisMachine.local_user || "",
                       hostname: thisMachine.short_hostname || "local" }}
            onSaved={() => { setEditingThis(false); refreshHosts(); }}
            onCancel={() => setEditingThis(false)}
          />
        ) : (
          <MachineCard machine={thisCard} isCurrent
                       onEditClick={() => setEditingThis(true)} />
        )}

        {/* Read-only cross-machine view (synced <vault>/machines/*.yaml).
            Issue #94: this vault-mirror IS the cross-machine visibility now —
            the retired "SSH scan targets / add machine" section was removed.
            To act on another machine, open its own dashboard (docs/remote_dashboard.md). */}
        <OtherMachinesView />
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

/* GitProvidersEditor — inline list editor used inside Lab Settings.
   Each row is one provider: {id, kind, label, target}. PI adds /
   edits / removes; the parent form sends the full list on save. Kept
   ascii-friendly so monospace alignment stays readable. */
function GitProvidersEditor({ value, onChange }) {
  const KINDS = ["github", "gitea", "local-bare"];
  const HINTS = {
    "github":     "target = org name (e.g. your-org)",
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
    space_audit:       ls.space_audit       || "",
    // Storage servers — three machine + path pairs. Files = the umbrella
    // (lab_base); notebooks + Obsidian get their own if the lab wants.
    files_host:        _fb.host,
    files_path:        _fb.path,
    notebook_host:     ls.notebook_host     || "",
    notebook_path:     ls.notebook_path     || "",
    obsidian_host:     ls.obsidian_host     || "",
    obsidian_path:     ls.obsidian_path     || "",
  });
  // The save payload for a form state; the first one is kept so a save can
  // send only the fields that changed.
  const buildLabPayload = (form) => ({
        display_name:      form.display_name,
        website:           form.website,
        admins:            form.admins.split(",").map(s => s.trim()).filter(Boolean),
        github_org:        form.github_org,
        git_repos_subpath: _reposSubpath(form.repos_path, form.files_path),
        git_providers:     form.git_providers,
        slack_workspace:   form.slack_workspace,
        slack_invite_url:  form.slack_invite_url,
        space_audit:       form.space_audit,
        // Files → the umbrella lab_base (host:/path).
        lab_base:          _joinHostPath(form.files_host, form.files_path),
        notebook_host:     form.notebook_host,
        notebook_path:     form.notebook_path,
        obsidian_host:     form.obsidian_host,
        obsidian_path:     form.obsidian_path,
  });
  const [initialPayload] = useState(() => buildLabPayload(form));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg]   = useState(null);

  const update = (k) => (e) => setForm((prev) => ({ ...prev, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setMsg(null);
    try {
      // Send only what the PI changed (#187): re-sending untouched fields
      // rewrote lab.md (for example github_org from the PI's own login, or
      // reshaped storage paths) without anyone asking.
      const all = buildLabPayload(form);
      const payload = Object.fromEntries(Object.entries(all).filter(
        ([k, v]) => JSON.stringify(v) !== JSON.stringify(initialPayload[k])));
      if (Object.keys(payload).length === 0) { setMsg("nothing changed"); setBusy(false); return; }
      const userParam = new URLSearchParams(window.location.search).get("user");
      const res = await fetch("/api/lab/settings" + (userParam ? "?user=" + encodeURIComponent(userParam) : ""), {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || ("HTTP " + res.status));
      }
      const body = await res.json().catch(() => ({}));
      if (typeof window.__murmurentFetchData === "function") {
        try { await window.__murmurentFetchData(window.DATA.persona); } catch (_) {}
      }
      // Stay open when the commit or push did not go through, so the change
      // is not silently left on this computer only (#185).
      const failed = (body.probes || []).filter(pr => pr.status !== "ok");
      if (failed.length) {
        setMsg("Saved here, but not shared: " + failed.map(pr => pr.name + ": " + pr.detail).join("; "));
        return;
      }
      setMsg("saved");
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
  const sectionHeader = {
    margin:0, fontFamily:"var(--mono)", fontSize:10, letterSpacing:1.5,
    textTransform:"uppercase", color:"var(--purple-deep)",
  };
  const sectionStyle = {
    borderTop:"1px solid var(--rule)", paddingTop:10, marginTop:6,
  };

  // Storage-server rows moved out (GH #23) — they were machine-dependent. The
  // storage form fields (files_host/path, notebook_*, obsidian_*, repos_*)
  // are still seeded from ls and sent unchanged in the save payload so
  // existing lab.md values persist; they're just no longer edited here.

  const githubOrg = (form.github_org || "").trim();
  const labMgmtPath = ls.lab_mgmt_path || "lab_mgmt";

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
            {groupNoun()} settings
          </h2>
          <button type="button" className="btn sm ghost" onClick={onClose}>✕ close</button>
        </div>
        <p className="muted" style={{fontSize:12, margin:"4px 0 8px", lineHeight:1.5}}>
          <strong>The whole lab.</strong> Only the PI can save. Edits write to
          <code className="mono"> {labMgmtPath}/lab.md</code> and are committed
          and pushed, so every member's dashboard picks them up.
        </p>

        {/* 1 · Identity */}
        <div style={sectionStyle}>
          <h4 style={sectionHeader}>Identity</h4>
          <div className="row" style={{flexWrap:"wrap", gap:14, marginTop:6, fontSize:13}}>
            <div><span className="muted">lab id</span> <code className="mono">{ls.name || "—"}</code></div>
            <div><span className="muted">netname of PI</span> <code className="mono">{ls.pi_handle || "—"}</code></div>
          </div>
          <div style={labelStyle}>display name</div>
          <input style={inputStyle} value={form.display_name} onChange={update("display_name")}
                 placeholder="e.g. Example Lab" />
          <div style={labelStyle}>lab website</div>
          <input style={inputStyle} value={form.website} onChange={update("website")}
                 placeholder="https://your-lab.example.edu" />
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

        {/* 5 · Space audit (#185): optional; needs a one-time setup on the
            lab's data server, so a PI chooses whether to use it. */}
        <div style={sectionStyle}>
          <h4 style={sectionHeader}>Space audit</h4>
          <div style={{fontSize:11, color:"var(--muted)", marginTop:3, marginBottom:6, lineHeight:1.5}}>
            A weekly report of how much disk each project uses on the lab's data
            server, with suggestions for what could be tidied. It runs under your
            own account on that server, only reads, and never needs administrator
            rights, but it has to be set up there once
            (<code>murmurent space schedule --install</code>; see the docs page
            "Tidying a project's space"). Turn it off if your lab does not want it:
            the dashboard then stops showing it and the weekly scan does nothing.
          </div>
          <select style={inputStyle} value={form.space_audit} onChange={update("space_audit")}>
            <option value="">not chosen (not shown on the dashboard)</option>
            <option value="on">on</option>
            <option value="off">off</option>
          </select>
        </div>

        {/* Storage servers section removed (GH #23): storage/lab-VM roots are
            machine-dependent and now live with each machine (the "large-file
            location" field in Machine settings). The lab_base / notebook /
            obsidian / repos values are still round-tripped through the save
            payload below (seeded from ls) so existing lab.md values persist
            unchanged — they're just no longer edited from this modal. */}

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
  const canEditLab = isPI;  // PI only; see CmdBar
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
                title="Edit my personal profile"
                onClick={() => setShowProfile(true)}
                style={{
                  background:"transparent", border:"1px solid var(--rule-strong)",
                  borderRadius:2, padding:"1px 6px", cursor:"pointer",
                  fontSize:11, color:"var(--purple)",
                }}>
                ⚙ personal profile
              </button>
              {/* ⚙ machines button moved into the Machines content block
                  (next to Projects, below Installations). The MachinesModal
                  state stays wired for back-compat in case external callers
                  still trigger it. */}
              {canEditLab && (
                <button
                  type="button"
                  title={groupNoun() + " settings (PI / admin)"}
                  onClick={() => setShowLabSettings(true)}
                  style={{
                    background:"transparent", border:"1px solid var(--rule-strong)",
                    borderRadius:2, padding:"1px 6px", cursor:"pointer",
                    fontSize:11, color:"var(--purple)",
                  }}>
                  ⚙ {groupNoun().toLowerCase()}
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
      <UpdateBanner />
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

        <div className="grid" style={{marginBottom:14}}>
          <PersonalOraclePanel data={D.personal_oracle} span="c-3" />
          <NotebookPanel span="c-5" />
          <LabOraclePanel entries={D.oracle_recent} drafts={D.oracle_drafts}
                          labFolder={D.lab_oracle_folder} span="c-4" />
        </div>

        {/* Launch Claude Code — prominent entry point above the repos list. */}
        <div className="grid" style={{marginBottom:14}}>
          <CCLaunchBar span="c-12" />
        </div>

        {/* Repo inventory: cross-machine + GitHub audit — one column per
            registered machine (local included). Cached weekly, on-demand
            refresh. Per-row "↑ adopt" / "Install on <machine>" pre-fill
            the adopt/install wizards. Each cloned-locally row also has a
            "▶ CC" button to open a Claude Code session in that repo. Terminal
            twin: `murmurent repo {list,status,adopt}`. */}
        <div className="grid" style={{marginBottom:14}}>
          <RepoInventoryPanel span="c-12" />
        </div>

        {/* Choreographies (group-shared) replace the removed SEA windows (#38).
            The live agent feed, "my contributions" and inventory panels were
            removed in #185. */}
        <div className="grid" style={{marginBottom:14}}>
          <ChoreographiesPanel choreographies={D.choreographies} span="c-12" />
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

        {/* Lab audits — the security audit (/security) and the millwright's
            space audit (/space) side by side (#185), plus the PI's grant of
            the murmurent-level ``lab_sudo`` flag that opens /security to a
            member. Independent of OS-level sudo on the lab server. */}
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
        <div className="grid">
          <AgentsPanel agents={D.agents} span="c-12" />
        </div>
      </div>
      <FooterMeta />
      <Footer />
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
