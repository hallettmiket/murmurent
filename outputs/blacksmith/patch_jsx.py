"""
Purpose: Apply targeted edits to docs/designer_dashboard/hifi-app.jsx for
         the Oracle split + member profile modal features.
Author: Blacksmith (Claude Code)
Date: 2026-05-10
Input:  /Users/mth/repos/wigamig/docs/designer_dashboard/hifi-app.jsx
Output: same file, edited in place after backup.
"""

from __future__ import annotations

from pathlib import Path

SRC = Path("/Users/mth/repos/wigamig/docs/designer_dashboard/hifi-app.jsx")


def must_replace(text: str, needle: str, replacement: str, label: str) -> str:
    if needle not in text:
        raise SystemExit(f"PATCH FAILED — anchor not found for {label!r}")
    count = text.count(needle)
    if count != 1:
        raise SystemExit(
            f"PATCH FAILED — anchor for {label!r} appears {count}× (need exactly 1)"
        )
    return text.replace(needle, replacement, 1)


def main() -> None:
    text = SRC.read_text(encoding="utf-8")

    # --------------------------------------------------------------
    # 1. LabOraclePanel: add `labFolder` prop + render a muted
    #    subtitle row showing <code>{labFolder}</code> under the header.
    # --------------------------------------------------------------
    old_sig = 'function LabOraclePanel({ entries, drafts, span="c-6" }) {\n'
    new_sig = 'function LabOraclePanel({ entries, drafts, labFolder, span="c-6" }) {\n'
    text = must_replace(text, old_sig, new_sig, "LabOraclePanel signature")

    # Insert subtitle row right after the closing </header> for the
    # LabOraclePanel. We anchor on the <header>...</header> block that
    # contains the "Lab oracle · recent" title.
    old_header = (
        '      <header>\n'
        '        <h2>Lab oracle · recent</h2>\n'
        '        <div className="row" style={{gap:6}}>\n'
        '          <span className="meta">\n'
        '            {list.length} published\n'
        '            {isPI && pendingDrafts.length > 0 && (\n'
        '              <span> · <strong style={{color:"var(--tiger-deep)"}}>\n'
        '                {pendingDrafts.length} draft{pendingDrafts.length === 1 ? "" : "s"}\n'
        '              </strong></span>\n'
        '            )}\n'
        '          </span>\n'
        '          <OracleProcessButton />\n'
        '        </div>\n'
        '      </header>\n'
    )
    new_header = old_header + (
        '      {labFolder && (\n'
        '        <div className="muted" style={{padding:"2px 14px 6px",\n'
        '             fontSize:11, borderBottom:"1px solid var(--rule)"}}>\n'
        '          <code className="mono">{labFolder}</code>\n'
        '        </div>\n'
        '      )}\n'
    )
    text = must_replace(text, old_header, new_header, "LabOraclePanel header subtitle")

    # --------------------------------------------------------------
    # 2. Add PersonalOraclePanel component immediately before
    #    LabOraclePanel.
    # --------------------------------------------------------------
    insertion_anchor = (
        'function LabOraclePanel({ entries, drafts, labFolder, span="c-6" }) {\n'
    )
    personal_panel = (
        '/* Personal Oracle — the member\'s own evolving knowledge base, backed by\n'
        '   their personal Obsidian vault. No drafts/approval flow (that\'s the\n'
        '   lab oracle\'s job); this is just the member\'s notes-to-self. */\n'
        'function PersonalOraclePanel({ data, span="c-4" }) {\n'
        '  const block = data || { folder: "oracle/", entry_count: 0, recent: [] };\n'
        '  const recent = block.recent || [];\n'
        '  return (\n'
        '    <div className={"panel "+span}>\n'
        '      <header>\n'
        '        <h2>Oracle · personal</h2>\n'
        '        <span className="meta">{block.entry_count} entries</span>\n'
        '      </header>\n'
        '      <div className="muted" style={{padding:"2px 14px 6px",\n'
        '           fontSize:11, borderBottom:"1px solid var(--rule)"}}>\n'
        '        <code className="mono">{block.folder}</code>\n'
        '      </div>\n'
        '      <div className="body" style={{padding:"6px 0"}}>\n'
        '        {recent.map((e, i) => (\n'
        '          <div key={i} style={{padding:"9px 14px", borderBottom:"1px solid var(--rule)"}}>\n'
        '            <div style={{display:"flex", justifyContent:"space-between", alignItems:"baseline", gap:10}}>\n'
        '              <span style={{fontWeight:500, fontSize:14, lineHeight:1.3, color:"var(--purple-deep)"}}>{e.title}</span>\n'
        '              <span className="mono muted" style={{fontSize:10, whiteSpace:"nowrap"}}>{e.date}</span>\n'
        '            </div>\n'
        '            <div className="muted" style={{fontSize:12, marginTop:4, lineHeight:1.45}}>\n'
        '              {e.excerpt}\n'
        '            </div>\n'
        '            <div className="mono muted" style={{fontSize:10, marginTop:5, letterSpacing:0.5, color:"var(--purple)"}}>\n'
        '              <code>{e.path}</code>\n'
        '            </div>\n'
        '          </div>\n'
        '        ))}\n'
        '        {recent.length === 0 && (\n'
        '          <div className="muted" style={{padding:"14px", fontSize:13}}>\n'
        '            No personal oracle entries yet. Ask the Oracle to remember\n'
        '            something and it\'ll show up here.\n'
        '          </div>\n'
        '        )}\n'
        '      </div>\n'
        '    </div>\n'
        '  );\n'
        '}\n'
        '\n'
    )
    text = must_replace(
        text, insertion_anchor, personal_panel + insertion_anchor,
        "PersonalOraclePanel insertion before LabOraclePanel",
    )

    # --------------------------------------------------------------
    # 3. Layout: replace the notebook+oracle row with three columns.
    # --------------------------------------------------------------
    old_layout = (
        '        <div className="grid" style={{marginBottom:14}}>\n'
        '          <NotebookPanel span="c-7" />\n'
        '          <LabOraclePanel entries={D.oracle_recent} drafts={D.oracle_drafts} span="c-5" />\n'
        '        </div>\n'
    )
    new_layout = (
        '        <div className="grid" style={{marginBottom:14}}>\n'
        '          <PersonalOraclePanel data={D.personal_oracle} span="c-3" />\n'
        '          <NotebookPanel span="c-5" />\n'
        '          <LabOraclePanel entries={D.oracle_recent} drafts={D.oracle_drafts}\n'
        '                          labFolder={D.lab_oracle_folder} span="c-4" />\n'
        '        </div>\n'
    )
    text = must_replace(text, old_layout, new_layout, "notebook+oracle layout row")

    # --------------------------------------------------------------
    # 4. Convert FooterMeta from a plain function into one that uses
    #    useState for showProfile + a gear button + the modal mount.
    # --------------------------------------------------------------
    old_footer_open = (
        'function FooterMeta() {\n'
        '  const m = window.DATA.member;\n'
        '  const loc = m.location || {};\n'
        '  const c = m.contact || {};\n'
        '\n'
        '  // Build the office/dry-lab/wet-labs line, dropping any blank pieces.\n'
        '  const officeBits = [\n'
        '    loc.office     ? "Office: "   + loc.office   : null,\n'
        '    loc.dry_lab    ? "Dry lab: "  + loc.dry_lab  : null,\n'
        '    loc.wet_labs   ? "Wet labs: " + loc.wet_labs : null,\n'
        '  ].filter(Boolean).join(" · ");\n'
        '\n'
        '  return (\n'
        '    <div className="footer-meta">\n'
        '      <div className="grid">\n'
        '        <div>\n'
        '          <h5>Location</h5>\n'
    )
    new_footer_open = (
        'function FooterMeta() {\n'
        '  const m = window.DATA.member;\n'
        '  const loc = m.location || {};\n'
        '  const c = m.contact || {};\n'
        '  const [showProfile, setShowProfile] = useState(false);\n'
        '\n'
        '  // Build the office/dry-lab/wet-labs line, dropping any blank pieces.\n'
        '  const officeBits = [\n'
        '    loc.office     ? "Office: "   + loc.office   : null,\n'
        '    loc.dry_lab    ? "Dry lab: "  + loc.dry_lab  : null,\n'
        '    loc.wet_labs   ? "Wet labs: " + loc.wet_labs : null,\n'
        '  ].filter(Boolean).join(" · ");\n'
        '\n'
        '  return (\n'
        '    <div className="footer-meta">\n'
        '      {showProfile && <MemberProfileModal onClose={() => setShowProfile(false)} />}\n'
        '      <div className="grid">\n'
        '        <div>\n'
        '          <h5>\n'
        '            <span style={{display:"inline-flex", alignItems:"center", gap:6}}>\n'
        '              {m.name || m.handle}\n'
        '              <button\n'
        '                type="button"\n'
        '                title="Edit profile"\n'
        '                onClick={() => setShowProfile(true)}\n'
        '                style={{\n'
        '                  background:"transparent", border:"1px solid var(--rule-strong)",\n'
        '                  borderRadius:2, padding:"1px 6px", cursor:"pointer",\n'
        '                  fontSize:11, color:"var(--muted)",\n'
        '                }}>\n'
        '                ⚙\n'
        '              </button>\n'
        '            </span>\n'
        '          </h5>\n'
        '          <div className="row mono muted" style={{fontSize:11, marginBottom:6}}>\n'
        '            @{m.handle} · {m.role}\n'
        '          </div>\n'
        '          <h5 style={{marginTop:10}}>Location</h5>\n'
    )
    text = must_replace(text, old_footer_open, new_footer_open, "FooterMeta open + gear button")

    # --------------------------------------------------------------
    # 5. Add MemberProfileModal component definition right before
    #    `function FooterMeta()`.
    # --------------------------------------------------------------
    modal_anchor = "/* ───────── footer ───────── */\n"
    member_profile_modal = (
        '/* MemberProfileModal — view/edit member-specific settings. Opened from\n'
        '   the gear button beside the member name in FooterMeta. POSTs to\n'
        '   /api/member/settings on save (silently ignores 404 / fetch errors\n'
        '   while the backend wiring lands). */\n'
        'function MemberProfileModal({ onClose }) {\n'
        '  const m = window.DATA.member || {};\n'
        '  const initial = window.DATA.member_settings || {};\n'
        '  const [form, setForm] = useState({\n'
        '    obsidian_vault_path: initial.obsidian_vault_path || "",\n'
        '    obsidian_vault_name: initial.obsidian_vault_name || "",\n'
        '    notebook_subfolder:  initial.notebook_subfolder  || "lab-notebook",\n'
        '    oracle_subfolder:    initial.oracle_subfolder    || "oracle",\n'
        '    email:    initial.email    || "",\n'
        '    orcid:    initial.orcid    || "",\n'
        '    bluesky:  initial.bluesky  || "",\n'
        '    github:   initial.github   || "",\n'
        '    osf:      initial.osf      || "",\n'
        '    website:  initial.website  || "",\n'
        '    office:   initial.office   || "",\n'
        '    dry_lab:  initial.dry_lab  || "",\n'
        '    wet_labs: initial.wet_labs || "",\n'
        '    address:  initial.address  || "",\n'
        '    city:     initial.city     || "",\n'
        '    department: initial.department || "",\n'
        '  });\n'
        '  const [busy, setBusy] = useState(false);\n'
        '  const [msg, setMsg]   = useState(null);\n'
        '\n'
        '  const update = (k) => (e) =>\n'
        '    setForm((prev) => ({ ...prev, [k]: e.target.value }));\n'
        '\n'
        '  const submit = async (e) => {\n'
        '    e.preventDefault();\n'
        '    setBusy(true); setMsg(null);\n'
        '    try {\n'
        '      const res = await fetch("/api/member/settings", {\n'
        '        method: "POST",\n'
        '        credentials: "same-origin",\n'
        '        headers: { "Content-Type": "application/json", Accept: "application/json" },\n'
        '        body: JSON.stringify(form),\n'
        '      });\n'
        '      if (res.ok) {\n'
        '        setMsg("saved");\n'
        '        if (typeof window.__wigamigFetchData === "function") {\n'
        '          try { await window.__wigamigFetchData(window.DATA.persona); } catch (_) {}\n'
        '        }\n'
        '      } else {\n'
        '        // Endpoint not wired yet — keep local state, surface a hint.\n'
        '        setMsg("backend not wired (HTTP " + res.status + ")");\n'
        '      }\n'
        '    } catch (ex) {\n'
        '      setMsg("offline — local only");\n'
        '    } finally {\n'
        '      setBusy(false);\n'
        '    }\n'
        '  };\n'
        '\n'
        '  const labelStyle = {\n'
        '    fontFamily:"var(--mono)", fontSize:10, letterSpacing:1,\n'
        '    textTransform:"uppercase", color:"var(--muted)",\n'
        '    marginTop:8, marginBottom:2,\n'
        '  };\n'
        '  const inputStyle = {\n'
        '    padding:"5px 8px", border:"1px solid var(--rule-strong)",\n'
        '    borderRadius:2, fontFamily:"var(--mono)", fontSize:12, width:"100%",\n'
        '    boxSizing:"border-box", background:"var(--paper)",\n'
        '  };\n'
        '  const sectionStyle = {\n'
        '    borderTop:"1px solid var(--rule)", paddingTop:10, marginTop:10,\n'
        '  };\n'
        '  const sectionHeader = {\n'
        '    margin:0, fontFamily:"var(--mono)", fontSize:10, letterSpacing:1.5,\n'
        '    textTransform:"uppercase", color:"var(--purple-deep)",\n'
        '  };\n'
        '\n'
        '  const vaultName = form.obsidian_vault_name || initial.obsidian_vault_name || "—";\n'
        '\n'
        '  return (\n'
        '    <div onClick={onClose} style={{\n'
        '      position:"fixed", inset:0, background:"rgba(32,20,54,0.55)",\n'
        '      display:"flex", alignItems:"flex-start", justifyContent:"center",\n'
        '      zIndex:200, padding:"40px 20px", overflowY:"auto",\n'
        '    }}>\n'
        '      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} style={{\n'
        '        background:"var(--card)", border:"1px solid var(--rule-strong)",\n'
        '        borderRadius:2, padding:18, width:"min(640px, 96vw)",\n'
        '        display:"flex", flexDirection:"column", gap:4,\n'
        '      }}>\n'
        '        <div className="row" style={{justifyContent:"space-between", alignItems:"baseline"}}>\n'
        '          <h2 style={{margin:0, fontFamily:"var(--serif)", fontSize:20, color:"var(--purple-deep)"}}>\n'
        '            Member profile\n'
        '          </h2>\n'
        '          <button type="button" className="btn sm ghost" onClick={onClose}>✕ close</button>\n'
        '        </div>\n'
        '        <p className="muted" style={{fontSize:12, margin:"4px 0 0"}}>\n'
        '          Edits POST to <code>/api/member/settings</code> and update\n'
        '          <code> &lt;lab-mgmt&gt;/members/&lt;handle&gt;.yaml</code>.\n'
        '        </p>\n'
        '\n'
        '        {/* Identity (read-only) */}\n'
        '        <div style={sectionStyle}>\n'
        '          <h4 style={sectionHeader}>Identity</h4>\n'
        '          <div className="row" style={{flexWrap:"wrap", gap:14, marginTop:6, fontSize:13}}>\n'
        '            <div><span className="muted">handle</span> <code className="mono">@{m.handle}</code></div>\n'
        '            <div><span className="muted">name</span> {m.name}</div>\n'
        '            <div><span className="muted">role</span> {m.role}</div>\n'
        '            <div><span className="muted">lab</span> <code className="mono">{m.lab}</code></div>\n'
        '            <div><span className="muted">vault</span> <code className="mono">{vaultName}/</code></div>\n'
        '          </div>\n'
        '        </div>\n'
        '\n'
        '        {/* Obsidian + notebook */}\n'
        '        <div style={sectionStyle}>\n'
        '          <h4 style={sectionHeader}>Obsidian &amp; notebook</h4>\n'
        '          <div style={labelStyle}>vault path (full)</div>\n'
        '          <input style={inputStyle} value={form.obsidian_vault_path}\n'
        '                 onChange={update("obsidian_vault_path")}\n'
        '                 placeholder="/Users/you/.../obsidian-lab" />\n'
        '          <div style={labelStyle}>vault name (for obsidian:// URLs)</div>\n'
        '          <input style={inputStyle} value={form.obsidian_vault_name}\n'
        '                 onChange={update("obsidian_vault_name")}\n'
        '                 placeholder="obsidian-lab" />\n'
        '          <div className="row" style={{gap:10, marginTop:4}}>\n'
        '            <div style={{flex:1}}>\n'
        '              <div style={labelStyle}>notebook subfolder</div>\n'
        '              <input style={inputStyle} value={form.notebook_subfolder}\n'
        '                     onChange={update("notebook_subfolder")} />\n'
        '            </div>\n'
        '            <div style={{flex:1}}>\n'
        '              <div style={labelStyle}>oracle subfolder</div>\n'
        '              <input style={inputStyle} value={form.oracle_subfolder}\n'
        '                     onChange={update("oracle_subfolder")} />\n'
        '            </div>\n'
        '          </div>\n'
        '        </div>\n'
        '\n'
        '        {/* Contact */}\n'
        '        <div style={sectionStyle}>\n'
        '          <h4 style={sectionHeader}>Contact</h4>\n'
        '          <div style={labelStyle}>email</div>\n'
        '          <input style={inputStyle} value={form.email} onChange={update("email")} />\n'
        '          <div className="row" style={{gap:10, marginTop:4}}>\n'
        '            <div style={{flex:1}}>\n'
        '              <div style={labelStyle}>ORCID</div>\n'
        '              <input style={inputStyle} value={form.orcid} onChange={update("orcid")} />\n'
        '            </div>\n'
        '            <div style={{flex:1}}>\n'
        '              <div style={labelStyle}>Bluesky</div>\n'
        '              <input style={inputStyle} value={form.bluesky} onChange={update("bluesky")} />\n'
        '            </div>\n'
        '          </div>\n'
        '          <div className="row" style={{gap:10, marginTop:4}}>\n'
        '            <div style={{flex:1}}>\n'
        '              <div style={labelStyle}>GitHub</div>\n'
        '              <input style={inputStyle} value={form.github} onChange={update("github")} />\n'
        '            </div>\n'
        '            <div style={{flex:1}}>\n'
        '              <div style={labelStyle}>OSF</div>\n'
        '              <input style={inputStyle} value={form.osf} onChange={update("osf")} />\n'
        '            </div>\n'
        '          </div>\n'
        '          <div style={labelStyle}>website</div>\n'
        '          <input style={inputStyle} value={form.website} onChange={update("website")} />\n'
        '        </div>\n'
        '\n'
        '        {/* Location */}\n'
        '        <div style={sectionStyle}>\n'
        '          <h4 style={sectionHeader}>Location</h4>\n'
        '          <div className="row" style={{gap:10, marginTop:4}}>\n'
        '            <div style={{flex:1}}>\n'
        '              <div style={labelStyle}>office</div>\n'
        '              <input style={inputStyle} value={form.office} onChange={update("office")} />\n'
        '            </div>\n'
        '            <div style={{flex:1}}>\n'
        '              <div style={labelStyle}>dry lab</div>\n'
        '              <input style={inputStyle} value={form.dry_lab} onChange={update("dry_lab")} />\n'
        '            </div>\n'
        '          </div>\n'
        '          <div style={labelStyle}>wet labs</div>\n'
        '          <input style={inputStyle} value={form.wet_labs} onChange={update("wet_labs")} />\n'
        '          <div style={labelStyle}>address</div>\n'
        '          <input style={inputStyle} value={form.address} onChange={update("address")} />\n'
        '          <div style={labelStyle}>city</div>\n'
        '          <input style={inputStyle} value={form.city} onChange={update("city")} />\n'
        '          <div style={labelStyle}>department</div>\n'
        '          <input style={inputStyle} value={form.department} onChange={update("department")} />\n'
        '        </div>\n'
        '\n'
        '        <div className="row" style={{justifyContent:"flex-end", gap:6, marginTop:14, alignItems:"center"}}>\n'
        '          {msg && (\n'
        '            <span className="muted" style={{fontSize:11, marginRight:"auto"}}>{msg}</span>\n'
        '          )}\n'
        '          <button type="button" className="btn sm ghost" onClick={onClose}>close</button>\n'
        '          <button type="submit" className="btn sm primary" disabled={busy}>\n'
        '            {busy ? "…" : "save"}\n'
        '          </button>\n'
        '        </div>\n'
        '      </form>\n'
        '    </div>\n'
        '  );\n'
        '}\n'
        '\n'
    )
    text = must_replace(
        text, modal_anchor, member_profile_modal + modal_anchor,
        "MemberProfileModal insertion before footer comment",
    )

    SRC.write_text(text, encoding="utf-8")
    print("OK — patched")


if __name__ == "__main__":
    main()
