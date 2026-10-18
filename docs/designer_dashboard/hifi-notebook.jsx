/* Hi-fi notebook entry view — today's daily note rendered as a real
   journal page with marginalia. Markdown-ish content tree comes from DATA.notebook. */

/* Phase 1: read window.DATA.notebook inside each function body so the
   live fetch (which mutates window.DATA after first paint) is picked up
   on re-render. The previous module-level `const NB = ...` froze a stale
   reference after Object.assign(window.DATA, ...). */

/* ── NbHintPopup: ⓘ button with a click-to-open popover.
   First line of `text` is the file path (rendered as <code>);
   remaining text is the human-readable explanation.             */
function NbHintPopup({ text }) {
  const [open, setOpen] = React.useState(false);
  React.useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [open]);

  const newline = text.indexOf("\n");
  const path    = newline > -1 ? text.slice(0, newline)      : text;
  const note    = newline > -1 ? text.slice(newline + 1).trim() : "";

  return (
    <span style={{position:"relative", display:"inline-block"}}
          onClick={e => e.stopPropagation()}>
      <button type="button" onClick={() => setOpen(o => !o)}
        style={{
          background:"none", border:"1px solid var(--rule-strong)", borderRadius:2,
          padding:"2px 8px", cursor:"pointer", fontSize:11,
          color:"var(--muted)", fontFamily:"var(--mono)", letterSpacing:0.3,
        }}>
        ⓘ where does this save?
      </button>
      {open && (
        <div style={{
          position:"absolute", top:"calc(100% + 6px)", left:0, zIndex:60,
          background:"var(--card)", border:"1px solid var(--rule-strong)",
          borderRadius:2, padding:"10px 12px", width:360, maxWidth:"90vw",
          fontSize:11, color:"var(--ink-2)",
          boxShadow:"0 4px 16px rgba(32,20,54,0.15)",
        }}>
          <div style={{marginBottom:6}}>
            <span className="muted" style={{display:"block", marginBottom:3,
              fontSize:10, letterSpacing:1, textTransform:"uppercase"}}>
              path
            </span>
            <code style={{wordBreak:"break-all", fontSize:10.5}}>{path}</code>
          </div>
          {note && (
            <div style={{color:"var(--muted)", borderTop:"1px solid var(--rule)", paddingTop:6}}>
              {note}
            </div>
          )}
        </div>
      )}
    </span>
  );
}

function NbToday() {
  const NB = window.DATA.notebook;
  const t = NB.today;
  // Cap the rendered day to its most recent ~50 blocks so a long entry doesn't
  // grow the panel without bound — the file itself always has the full text.
  const CAP = 50;
  const all = t.content || [];
  const shown = all.length > CAP ? all.slice(-CAP) : all;
  const hidden = all.length - shown.length;
  return (
    <div className="nb-entry">
      <h3>{t.title}</h3>
      <div className="meta">
        <span><span className="muted">file ›</span> <code>{NB.folder}{t.iso}.md</code></span>
        <span><span className="muted">tags ›</span> {t.tags.map(x => <span key={x} className="tag" style={{marginRight:4}}>{x}</span>)}</span>
        <span><span className="muted">links ›</span> {t.links_seas.map(n => <span key={n} className="wikilink" style={{marginRight:6}}>SEA #{n}</span>)} {t.links_exp.map(e => <span key={e} className="wikilink" style={{marginRight:6}}>{e}</span>)}</span>
      </div>

      {hidden > 0 && (
        <p className="muted" style={{fontSize:12, fontStyle:"italic", margin:"0 0 8px"}}>
          … showing the last {CAP} of {all.length} blocks — open the file for the full day.
        </p>
      )}
      {shown.map((b, i) => {
        if (b.kind === "h4")        return <h4 key={i}>{b.text}</h4>;
        if (b.kind === "hint")      return <NbHintPopup key={i} text={b.text} />;
        if (b.kind === "p")         return <p key={i}>{b.text.split(/(\[\[[^\]]+\]\])/).map((s,j) => /^\[\[/.test(s) ? <span key={j} className="wikilink">{s.replace(/[\[\]]/g,'')}</span> : <span key={j}>{s}</span>)}</p>;
        if (b.kind === "task")      return <p key={i} style={{margin:"4px 0"}}><span className={"check"+(b.done?" done":"")}></span><span style={{textDecoration:b.done?"line-through":"none",color:b.done?"var(--muted)":"inherit"}}>{b.text}</span></p>;
        if (b.kind === "list")      return <ul key={i}>{b.items.map((x,j) => <li key={j}>{x}</li>)}</ul>;
        if (b.kind === "blockquote") return <blockquote key={i}>{b.text}</blockquote>;
        if (b.kind === "code")      return <code key={i} className="codeblock">{b.text}</code>;
        return null;
      })}
    </div>
  );
}

function NbRail() {
  const NB = window.DATA.notebook;
  const onOpenDay = async (iso) => {
    try {
      const r = await window.postNotebookEdit(iso);
      if (typeof window.__murmurentFetchData === "function") {
        try { await window.__murmurentFetchData(window.DATA.persona); } catch (_) {}
      }
    } catch (ex) {
      alert("Could not open " + iso + ".md: " + (ex.message || ex));
    }
  };
  return (
    <div>
      {NB.days.map(d => (
        <div
          key={d.iso}
          className={"nb-day"+(d.is_today?" on":"")}
          onClick={() => onOpenDay(d.iso)}
          title={"Open " + d.iso + ".md in your editor"}
        >
          <span className="d">{d.iso.slice(8)}</span>
          <span className="w">{d.weekday.toUpperCase()}</span>
          <span style={{flex:1}}></span>
          <span style={{fontSize:10, color: d.is_today?"rgba(255,255,255,0.7)":"var(--muted-2)"}}>
            {d.has_entry ? `${d.word_count} w` : "—"}
          </span>
        </div>
      ))}
      <div style={{marginTop:10, paddingTop:8, borderTop:"1px dotted var(--rule-strong)"}}>
        <button
          className="btn sm" style={{width:"100%"}}
          onClick={() => {
            // Today's iso = first day with is_today, fallback to top of list.
            const today = (NB.days.find(d => d.is_today) || NB.days[0] || {}).iso;
            onOpenDay(today);
          }}
        >
          ＋ new entry
        </button>
      </div>
    </div>
  );
}

window.NbToday = NbToday;
window.NbRail  = NbRail;
