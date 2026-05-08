"""
Purpose: Streamlit live view of the wigamig dashboard. Theme matches the
         Hallett Lab website (Western purple + tiger orange + EB Garamond).
         Home view is a grid of category buttons; each opens one section.
         Land acknowledgement lives in the footer.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-08
Input: ``--user <handle>`` argv (passed by ``wigamig dashboard`` via streamlit
       argv) or ``$WIGAMIG_USER`` env var. Empty handle is allowed; the page
       renders a login sidebar.
Output: A locally-served Streamlit page.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    import streamlit as st  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover
    print("streamlit is not installed; install with `uv pip install streamlit`.")
    sys.exit(1)

try:
    from ..core import dashboard
except ImportError:
    from wigamig.core import dashboard  # type: ignore[no-redef]


USER_PREF_PATH = Path.home() / ".wigamig" / "user"

# Western University brand palette, picked from the Hallett Lab website.
WESTERN_PURPLE = "#4F2683"
WESTERN_PURPLE_DEEP = "#201436"
TIGER_ORANGE = "#F0A757"
ORCHID = "#8F55E0"
PAPER_BG = "#faf8f5"
BORDER = "#E0E0E2"
INK = "#1a1a1a"
MUTED = "#5b5b5b"


def _parse_argv() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", default=os.environ.get("WIGAMIG_USER", ""))
    return parser.parse_args()


def _save_user(handle: str) -> None:
    handle = handle.strip().lstrip("@")
    if not handle:
        return
    USER_PREF_PATH.parent.mkdir(parents=True, exist_ok=True)
    USER_PREF_PATH.write_text(handle + "\n", encoding="utf-8")


def _inject_theme() -> None:
    """Inject the Hallett Lab / Western look-and-feel onto the Streamlit page.

    Uses ``st.html`` because Streamlit's markdown parser breaks ``<style>``
    blocks at blank lines and CSS comments and renders the tail as plain text.
    """
    st.html(
        f"""
        <link href="https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,500;0,600;1,400&family=Courier+Prime:ital,wght@0,400;0,700&display=swap" rel="stylesheet">
        <style>
          /* Apply EB Garamond globally so the lab name's font is everywhere. */
          html, body,
          [data-testid="stAppViewContainer"],
          [data-testid="stSidebar"],
          [data-testid="stMarkdownContainer"],
          [data-testid="stMarkdownContainer"] *,
          [data-testid="stCaptionContainer"],
          [data-testid="stCaptionContainer"] *,
          .stMarkdown, .stMarkdown *,
          .stCaption,
          p, span, div, li, td, th, label,
          input, select, textarea {{
            font-family: 'EB Garamond', Georgia, serif !important;
          }}
          /* Code blocks keep monospace for readability. */
          code, pre, kbd, samp {{
            font-family: 'Courier Prime', Menlo, monospace !important;
          }}

          html, body, [data-testid="stAppViewContainer"] {{
            background: {PAPER_BG} !important;
            color: {INK} !important;
          }}
          [data-testid="stHeader"] {{ background: {PAPER_BG} !important; }}
          h1, h2, h3, h4 {{
            font-family: 'EB Garamond', Georgia, serif !important;
            font-weight: 600 !important;
            color: {WESTERN_PURPLE_DEEP} !important;
            letter-spacing: -0.3px;
          }}
          h1 {{ color: {WESTERN_PURPLE} !important; }}
          h2 {{ border-bottom: 1px solid {BORDER}; padding-bottom: 6px; }}

          /* Slim banner: lab + Western, NO land ack here. */
          .wigamig-banner {{
            background: {WESTERN_PURPLE};
            color: #fff;
            padding: 10px 22px;
            margin: -1rem -1rem 1.4rem -1rem;
            display: flex;
            align-items: center;
            gap: 14px;
            border-bottom: 3px solid {TIGER_ORANGE};
          }}
          .wigamig-banner .lab {{
            font-family: 'EB Garamond', Georgia, serif;
            font-size: 20px;
            color: {TIGER_ORANGE};
          }}
          .wigamig-banner .sep {{ color: rgba(255,255,255,0.4); }}
          .wigamig-banner .uwo {{
            font-size: 11px; letter-spacing: 0.5px;
            color: rgba(255,255,255,0.85);
          }}
          .wigamig-banner .who {{
            margin-left: auto;
            font-size: 11px; color: rgba(255,255,255,0.85);
          }}
          .wigamig-banner .who code {{
            background: rgba(255,255,255,0.12);
            color: #fff; padding: 2px 6px; border-radius: 1px;
          }}

          /* Box style for sections + nav buttons. */
          .wigamig-card {{
            background: #fff;
            border: 1px solid {BORDER};
            border-radius: 2px;
            padding: 18px 22px;
            margin-bottom: 16px;
          }}
          .wigamig-tag {{
            display: inline-block;
            font-size: 10px; font-weight: 600; letter-spacing: 0.5px;
            text-transform: uppercase;
            color: {WESTERN_PURPLE};
            border: 1px solid {WESTERN_PURPLE};
            padding: 2px 6px; border-radius: 1px;
            margin-right: 6px;
          }}
          .wigamig-tag.tiger {{ color: {TIGER_ORANGE}; border-color: {TIGER_ORANGE}; }}
          .wigamig-tag.muted {{ color: {MUTED}; border-color: {BORDER}; }}

          /* Slim footer (no land ack here — it lives on the home page). */
          .wigamig-footer {{
            margin-top: 36px; padding: 14px 22px;
            border-top: 3px solid {TIGER_ORANGE};
            background: {WESTERN_PURPLE_DEEP};
            color: rgba(255,255,255,0.85);
            font-size: 12px; line-height: 1.5;
            font-family: 'EB Garamond', Georgia, serif !important;
          }}
          .wigamig-footer a {{
            color: {TIGER_ORANGE};
            text-decoration: none;
            border-bottom: 1px dotted {TIGER_ORANGE};
          }}

          /* Land acknowledgement card, home page only. */
          .wigamig-land-ack {{
            margin: 28px 0 8px 0;
            padding: 16px 20px;
            border-left: 4px solid {TIGER_ORANGE};
            background: #fff;
            border-radius: 2px;
            color: {INK};
            font-family: 'EB Garamond', Georgia, serif !important;
            font-style: italic;
            font-size: 14px;
            line-height: 1.55;
          }}
          .wigamig-land-ack strong {{
            font-style: normal;
            color: {WESTERN_PURPLE};
            text-transform: uppercase;
            letter-spacing: 1px;
            font-size: 12px;
            display: block;
            margin-bottom: 6px;
          }}

          /* Per-tile caption under each nav button. */
          .wigamig-nav-caption {{
            font-family: 'EB Garamond', Georgia, serif !important;
            font-size: 13px;
            color: {MUTED};
            text-align: center;
            margin: 6px 0 18px 0;
            font-style: italic;
          }}

          /* Nav buttons: uniform size regardless of label length. */
          .stButton > button {{
            width: 100%;
            min-height: 96px;
            border-radius: 2px;
            border: 1px solid {BORDER};
            background: #fff;
            color: {WESTERN_PURPLE_DEEP} !important;
            font-family: 'EB Garamond', Georgia, serif !important;
            font-size: 18px;
            font-weight: 600;
            padding: 18px 16px;
            text-align: center;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.15s;
          }}
          .stButton > button:hover {{
            border-color: {WESTERN_PURPLE};
            background: {WESTERN_PURPLE};
            color: #fff !important;
          }}
          .stButton > button:focus,
          .stButton > button:focus-visible {{
            outline: none;
            border-color: {TIGER_ORANGE};
            box-shadow: 0 0 0 2px {TIGER_ORANGE};
            color: {WESTERN_PURPLE_DEEP} !important;
          }}
          .stButton > button:active {{
            background: {WESTERN_PURPLE_DEEP};
            color: #fff !important;
          }}
          /* Compact 'back home' + form buttons (override large min-height
             when used inside a form). */
          [data-testid="stForm"] .stButton > button,
          .wigamig-compact-btn .stButton > button {{
            min-height: 38px;
            padding: 6px 14px;
            font-size: 14px;
          }}

          [data-testid="stSidebar"] {{
            background: #fff !important;
            border-right: 1px solid {BORDER};
          }}
          [data-testid="stExpander"] {{
            border: 1px solid {BORDER};
            border-radius: 2px;
            background: #fff;
          }}
        </style>
        """
    )


def _banner(member: str, role: str | None = None) -> None:
    """Slim banner: lab name, Western, current user. NO land ack here."""
    who = ""
    if member:
        role_chip = f" · <em>{role}</em>" if role else ""
        who = f"<span class='who'>logged in as <code>@{member}</code>{role_chip}</span>"
    st.html(
        f"""
        <div class="wigamig-banner">
          <span class="lab">Hallett Lab</span>
          <span class="sep">|</span>
          <span class="uwo">Western University &middot; Department of Biochemistry</span>
          {who}
        </div>
        """
    )


def _footer() -> None:
    """Slim footer: lab + Western contact line. No land ack here."""
    st.html(
        """
        <div class="wigamig-footer">
          Hallett Lab &middot; Department of Biochemistry &middot;
          Schulich School of Dentristy and Medicine &middot;
          Western University, London, ON, Canada
          &middot;
          <a href="https://hallettmiket.github.io" target="_blank">hallettmiket.github.io</a>
        </div>
        """
    )


def _home_land_ack() -> None:
    """Render the land acknowledgement on the home page only."""
    st.html(
        """
        <div class="wigamig-land-ack">
          <strong>Land Acknowledgement.</strong>
          We acknowledge that Western University is located on the
          traditional territories of the Anishinaabek, Haudenosaunee,
          Lūnaapéewak and Attawandaron peoples, on lands connected with
          the London Township and Sombra Treaties of 1796 and the
          Dish with One Spoon Covenant Wampum. With this, we recognise
          and respect the cultural diversity that reflects the depth of
          this land.
        </div>
        """
    )


def _render_login_screen(initial: str) -> None:
    st.markdown(
        "<h2 style='margin-top:1.5rem'>Welcome to wigamig</h2>",
        unsafe_allow_html=True,
    )
    st.write(
        "We need your handle to load the right dashboard. Enter your "
        "**Western username** (e.g. `the_pi`) — or one of the demo personas "
        "(`allie`, `bob`, `cassie`)."
    )
    with st.form("login"):
        handle = st.text_input("Username", value=initial)
        save = st.checkbox("Remember me on this machine", value=True)
        submitted = st.form_submit_button("Open dashboard")
    if submitted and handle.strip():
        if save:
            _save_user(handle)
        st.query_params["user"] = handle.strip().lstrip("@")
        st.rerun()


def _sidebar(current: str) -> None:
    st.sidebar.markdown(
        f"<div style='font-family: \"EB Garamond\", Georgia, serif; "
        f"font-size: 24px; color: {WESTERN_PURPLE}; font-weight: 600;'>"
        f"wigamig</div>",
        unsafe_allow_html=True,
    )
    st.sidebar.caption("Hallett Lab dashboard · Western University")

    st.sidebar.markdown("---")
    st.sidebar.markdown("**Logged in as**")
    st.sidebar.markdown(f"`@{current}`" if current else "_(not set)_")

    with st.sidebar.expander("Switch user"):
        new_handle = st.text_input(
            "Username (e.g. the_pi)",
            value="",
            key="switch_user",
            help="Saved to ~/.wigamig/user — useful if you log in from another machine.",
        )
        save = st.checkbox("Remember me", value=True, key="switch_save")
        if st.button("Switch", key="switch_btn") and new_handle.strip():
            if save:
                _save_user(new_handle)
            st.query_params["user"] = new_handle.strip().lstrip("@")
            st.rerun()


# ---------------------------------------------------------------------------
# Section navigation
# ---------------------------------------------------------------------------


SECTION_KEY = "wigamig_section"


def _go(section: str) -> None:
    st.session_state[SECTION_KEY] = section


def _current_section() -> str:
    return st.session_state.get(SECTION_KEY, "home")


def _nav_grid(snap: dashboard.DashboardSnapshot) -> None:
    """Home view: a uniform grid of section buttons with a caption under each."""
    rows = [
        ("projects", "Projects", f"{len(snap.projects)} you're on"),
        ("group", "Group", f"{len(snap.peers)} peers in your projects"),
        (
            "seas",
            "SEAs",
            f"{len(snap.seas_incoming)} incoming · "
            f"{len(snap.seas_outgoing)} outgoing · "
            f"{len(snap.outstanding)} outstanding",
        ),
        (
            "browse",
            "Browse",
            f"{len(snap.all_projects)} projects · "
            f"{len(snap.all_experiments)} exp folders · "
            f"{len(snap.all_seas)} SEAs",
        ),
        ("compliance", "Compliance", f"{len(snap.compliance)} project rows"),
        (
            "inventory",
            "Inventory",
            _inventory_caption(snap.inventory_summary),
        ),
    ]
    if snap.is_pi:
        rows.append(("pi", "PI view", "clinical-project compliance grid"))

    st.html("<p style='color:#5b5b5b; margin: 0 0 1.2rem 0;'>Pick a topic.</p>")
    # 3 columns × ceil(rows/3) rows of buttons. With 6 (or 7) tiles, this gives
    # a clean grid; the last row may be partial. Each tile = button + caption.
    cols_per_row = 3
    for i in range(0, len(rows), cols_per_row):
        cols = st.columns(cols_per_row, gap="medium")
        for j in range(cols_per_row):
            if i + j >= len(rows):
                continue
            key, label, caption = rows[i + j]
            with cols[j]:
                if st.button(label, key=f"nav_{key}"):
                    _go(key)
                    st.rerun()
                st.html(f"<div class='wigamig-nav-caption'>{caption}</div>")


def _inventory_caption(inv: dict) -> str:
    total = sum(len(v) for v in inv.values())
    return f"{total} flagged" if total else "all clear"


def _back_button() -> None:
    if st.button("← Home", key="back_home"):
        _go("home")
        st.rerun()


# ---------------------------------------------------------------------------
# Section bodies
# ---------------------------------------------------------------------------


def _section_projects(snap: dashboard.DashboardSnapshot) -> None:
    _back_button()
    st.subheader("Projects you are on")
    if not snap.projects:
        st.info("You are not on any project.")
        return
    for p in snap.projects:
        badge = {"clinical": "🔴", "restricted": "🟡", "standard": "🟢"}.get(
            p.sensitivity, "⚪"
        )
        with st.container(border=True):
            st.markdown(
                f"### {badge} {p.name}\n\n"
                f"**Lead:** `{p.lead}`  \n"
                f"**Sensitivity:** {p.sensitivity}  \n"
                f"**Choreography:** {p.choreography or '—'}  \n"
                f"**Members:** {', '.join(p.members) or '—'}  \n"
                f"**Path:** `{p.path}`"
            )


def _section_group(snap: dashboard.DashboardSnapshot) -> None:
    _back_button()
    st.subheader("Group — peers in your shared projects")
    if not snap.peers:
        st.info("No peers in your projects yet.")
        return
    for peer in snap.peers:
        tcps_badge = {
            "ok": "✅",
            "expiring": "🟡",
            "expired": "🔴",
            "missing": "🔴",
        }.get(peer.tcps_status, "⚪")
        shared = ", ".join(peer.shared_projects) or "—"
        name = peer.full_name or peer.handle
        with st.container(border=True):
            st.markdown(
                f"**{tcps_badge} @{peer.handle}** — {name}  \n"
                f"role: _{peer.role}_ · status: {peer.status}  \n"
                f"shared: {shared}"
            )


def _section_seas(snap: dashboard.DashboardSnapshot) -> None:
    _back_button()
    st.subheader("SEAs involving me")
    col_in, col_out = st.columns(2, gap="medium")
    with col_in:
        with st.container(border=True):
            st.markdown("**Incoming**")
            if not snap.seas_incoming:
                st.write("_none_")
            for s in snap.seas_incoming:
                st.write(f"#{s.id} ({s.state}) ← {s.from_handle}: {s.description}")
    with col_out:
        with st.container(border=True):
            st.markdown("**Outgoing**")
            if not snap.seas_outgoing:
                st.write("_none_")
            for s in snap.seas_outgoing:
                st.write(f"#{s.id} ({s.state}) → {s.to_handle}: {s.description}")

    with st.container(border=True):
        st.markdown("**Outstanding analysis**")
        if not snap.outstanding:
            st.success("Nothing outstanding.")
        for item in snap.outstanding:
            line = (
                f"{item.scope} {item.target} ({item.project}) "
                f"· state: {item.state} "
                f"· age: {item.age_days if item.age_days is not None else '—'}d"
            )
            if item.severity == "red":
                st.error(line)
            elif item.severity == "yellow":
                st.warning(line)
            else:
                st.write(line)


def _section_browse(snap: dashboard.DashboardSnapshot) -> None:
    _back_button()
    st.subheader("Browse all local projects, experiment folders, SEAs")
    st.caption(
        "Pulldowns scan every local project repo (anything in `~/repos` with a "
        "`CHARTER.md`).  \n"
        "**SEA** = a tracked unit of work (kind: `skill` / `experiment` / `analysis`) "
        "with a request → claim → complete → examined → concluded lifecycle, stored "
        "as a markdown file under `<project>/seas/`.  \n"
        "**Experiment folder** = a working directory under `<project>/exp/<n>_<slug>/` "
        "with `notebook.md`, `run_all.py`, sketches, and data links. A SEA of "
        "kind=experiment usually points at one, but exp folders also exist on their "
        "own and SEAs of kind=skill / kind=analysis don't have one."
    )

    with st.container(border=True):
        st.markdown("**Projects**")
        labels = [
            f"{p.name}  —  lead {p.lead}  ({p.sensitivity})" for p in snap.all_projects
        ]
        if not labels:
            st.write("_no local projects found_")
        else:
            choice = st.selectbox("Project", ["—"] + labels, key="proj_browse")
            if choice and choice != "—":
                p = snap.all_projects[labels.index(choice)]
                st.markdown(
                    f"- name: **{p.name}**\n"
                    f"- lead: `{p.lead}`\n"
                    f"- sensitivity: {p.sensitivity}\n"
                    f"- choreography: {p.choreography or '—'}\n"
                    f"- members: {', '.join(p.members) or '—'}\n"
                    f"- path: `{p.path}`"
                )

    with st.container(border=True):
        st.markdown("**Experiment folders** (`<project>/exp/`)")
        labels = [
            f"{e.project} / {e.slug}  —  performer {','.join(e.performer) or '—'}"
            for e in snap.all_experiments
        ]
        if not labels:
            st.write("_no experiment folders found_")
        else:
            choice = st.selectbox("Experiment folder", ["—"] + labels, key="exp_browse")
            if choice and choice != "—":
                e = snap.all_experiments[labels.index(choice)]
                st.markdown(
                    f"- project: **{e.project}**\n"
                    f"- folder: `exp/{e.slug}/`\n"
                    f"- status: {e.status}\n"
                    f"- analysis_status: {e.analysis_status}\n"
                    f"- performer: {', '.join(e.performer) or '—'}\n"
                    f"- date: {e.date or '—'}"
                )

    with st.container(border=True):
        st.markdown("**SEAs** (`<project>/seas/`, all kinds)")
        labels = [
            f"#{s.id} {s.project} ({s.state})  —  {s.from_handle} → {s.to_handle}"
            for s in snap.all_seas
        ]
        if not labels:
            st.write("_no SEAs found_")
        else:
            choice = st.selectbox("SEA", ["—"] + labels, key="sea_browse")
            if choice and choice != "—":
                s = snap.all_seas[labels.index(choice)]
                st.markdown(
                    f"- SEA **#{s.id}** in `{s.project}`\n"
                    f"- kind: {s.kind}\n"
                    f"- state: {s.state}\n"
                    f"- {s.from_handle} → {s.to_handle}\n"
                    f"- {s.description}"
                )


def _section_compliance(snap: dashboard.DashboardSnapshot) -> None:
    _back_button()
    st.subheader("Security and compliance")
    if not snap.compliance:
        st.info("No per-project compliance rows; you are not in any project.")
        return
    for row in snap.compliance:
        with st.container(border=True):
            st.markdown(f"**{row.project}** ({row.sensitivity})")
            for cert in row.member_certs:
                badge = {
                    "ok": "✅",
                    "expiring": "🟡",
                    "expired": "🔴",
                    "missing": "🔴",
                }[cert.status]
                extra = f" (expires {cert.expires})" if cert.expires else ""
                st.write(f"{badge} {cert.name}{extra}")
            for note in row.notes:
                st.warning(note)


def _section_inventory(snap: dashboard.DashboardSnapshot) -> None:
    _back_button()
    st.subheader("Inventory — flagged items")
    inv = snap.inventory_summary
    for label, rows in (
        ("Expired", inv.get("expired", [])),
        ("Low / out", inv.get("low", [])),
        ("Expiring soon (30d)", inv.get("expiring", [])),
    ):
        with st.container(border=True):
            st.markdown(f"**{label}**")
            if not rows:
                st.write("_none_")
            for r in rows:
                st.write(
                    f"- {r['name']} ({r['status']}; expiry {r.get('expiry') or '—'})"
                )


def _section_pi(snap: dashboard.DashboardSnapshot) -> None:
    _back_button()
    st.subheader("PI view: clinical-project compliance grid")
    grid = snap.pi_view.get("clinical_compliance", [])
    if not grid:
        st.info("No clinical projects.")
        return
    for row in grid:
        badge = {
            "ok": "✅",
            "expiring": "🟡",
            "expired": "🔴",
            "missing": "🔴",
        }[row["tcps_status"]]
        line = (
            f"{badge} **{row['project']}** · {row['member']} "
            f"(TCPS_2 {row['tcps_status']}, expires {row.get('tcps_expires') or '—'})"
        )
        if row["tcps_status"] in {"missing", "expired"}:
            st.error(line)
        elif row["tcps_status"] == "expiring":
            st.warning(line)
        else:
            st.write(line)


SECTIONS = {
    "projects": _section_projects,
    "group": _section_group,
    "seas": _section_seas,
    "browse": _section_browse,
    "compliance": _section_compliance,
    "inventory": _section_inventory,
    "pi": _section_pi,
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:  # pragma: no cover - rendered live
    args = _parse_argv()
    handle = args.user.strip().lstrip("@")

    qp_user = st.query_params.get("user") if hasattr(st, "query_params") else None
    if isinstance(qp_user, list):
        qp_user = qp_user[0] if qp_user else None
    if qp_user:
        handle = str(qp_user).strip().lstrip("@")

    st.set_page_config(
        page_title="wigamig · Hallett Lab" + (f" · @{handle}" if handle else ""),
        layout="wide",
    )
    _inject_theme()

    if not handle:
        _banner("")
        _sidebar("")
        _render_login_screen("")
        _footer()
        return

    snap = dashboard.build_snapshot(handle)
    _banner(snap.member, snap.role)
    _sidebar(snap.member)

    section = _current_section()
    if section == "home":
        st.html(f"<h1>Dashboard for @{snap.member}</h1>")
        if snap.full_name:
            st.caption(snap.full_name)
        st.html(
            f"<div>"
            f"<span class='wigamig-tag'>{snap.role}</span>"
            f"<span class='wigamig-tag muted'>status: {snap.member_status}</span>"
            f"<span class='wigamig-tag tiger'>generated {snap.generated_at}</span>"
            f"</div>"
        )
        _nav_grid(snap)
        _home_land_ack()
    else:
        renderer = SECTIONS.get(section, _section_projects)
        renderer(snap)

    _footer()


if __name__ == "__main__":  # pragma: no cover
    main()
