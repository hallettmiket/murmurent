/* Hi-fi notebook entry view — today's daily note rendered as a real
   journal page with marginalia. Markdown-ish content tree comes from DATA.notebook. */

/* Phase 1: read window.DATA.notebook inside each function body so the
   live fetch (which mutates window.DATA after first paint) is picked up
   on re-render. The previous module-level `const NB = ...` froze a stale
   reference after Object.assign(window.DATA, ...). */

function NbToday() {
  const NB = window.DATA.notebook;
  const t = NB.today;
  return (
    <div className="nb-entry">
      <h3>{t.title}</h3>
      <div className="meta">
        <span><span className="muted">file ›</span> <code>{NB.folder}{t.iso}.md</code></span>
        <span><span className="muted">tags ›</span> {t.tags.map(x => <span key={x} className="tag" style={{marginRight:4}}>{x}</span>)}</span>
        <span><span className="muted">links ›</span> {t.links_seas.map(n => <span key={n} className="wikilink" style={{marginRight:6}}>SEA #{n}</span>)} {t.links_exp.map(e => <span key={e} className="wikilink" style={{marginRight:6}}>{e}</span>)}</span>
      </div>

      {t.content.map((b, i) => {
        if (b.kind === "h4") return <h4 key={i}>{b.text}</h4>;
        if (b.kind === "p")  return <p key={i}>{b.text.split(/(\[\[[^\]]+\]\])/).map((s,j) => /^\[\[/.test(s) ? <span key={j} className="wikilink">{s.replace(/[\[\]]/g,'')}</span> : <span key={j}>{s}</span>)}</p>;
        if (b.kind === "task") return <p key={i} style={{margin:"4px 0"}}><span className={"check"+(b.done?" done":"")}></span><span style={{textDecoration:b.done?"line-through":"none",color:b.done?"var(--muted)":"inherit"}}>{b.text}</span></p>;
        if (b.kind === "list") return <ul key={i}>{b.items.map((x,j) => <li key={j}>{x}</li>)}</ul>;
        if (b.kind === "blockquote") return <blockquote key={i}>{b.text}</blockquote>;
        if (b.kind === "code") return <code key={i} className="codeblock">{b.text}</code>;
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
      if (typeof window.__wigamigFetchData === "function") {
        try { await window.__wigamigFetchData(window.DATA.persona); } catch (_) {}
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
