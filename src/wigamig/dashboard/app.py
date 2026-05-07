"""
Purpose: Streamlit live view of the wigamig dashboard. Reads the snapshot for
         the current member and renders it with severity colouring.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-07
Input: ``--user <handle>`` argv (passed by ``wigamig dashboard`` via streamlit
       argv) or ``$WIGAMIG_USER`` env var.
Output: A locally-served Streamlit page.

Run via ``wigamig dashboard`` (preferred) or directly::

    streamlit run -m wigamig.dashboard.app -- --user allie
"""

from __future__ import annotations

import argparse
import os
import sys

try:
    import streamlit as st  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover
    print("streamlit is not installed; install with `uv pip install streamlit`.")
    sys.exit(1)

try:
    from ..core import dashboard
except ImportError:
    # Streamlit loads this file as a top-level script, not a package member,
    # so the relative import fails. Fall back to absolute import; the wigamig
    # package only needs to be installed in the env (it is).
    from wigamig.core import dashboard  # type: ignore[no-redef]


def _parse_argv() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", default=os.environ.get("WIGAMIG_USER", "mike"))
    return parser.parse_args()


def main() -> None:  # pragma: no cover - rendered live
    args = _parse_argv()
    snap = dashboard.build_snapshot(args.user)

    st.set_page_config(page_title=f"wigamig — @{snap.member}", layout="wide")
    st.title(f"wigamig dashboard — @{snap.member}")
    if snap.full_name:
        st.caption(snap.full_name)
    st.write(
        f"Generated: {snap.generated_at}  |  Role across projects: {snap.role}  "
        f"|  Member status: {snap.member_status}"
    )

    cols = st.columns(2)
    with cols[0]:
        st.subheader("Projects")
        if not snap.projects:
            st.write("_none_")
        for p in snap.projects:
            badge = {"clinical": "🔴", "restricted": "🟡", "standard": "🟢"}.get(p.sensitivity, "⚪")
            st.write(
                f"{badge} **{p.name}** — {p.sensitivity}; lead {p.lead}; "
                f"choreography {p.choreography or '—'}"
            )

        st.subheader("SEAs")
        st.markdown("**Incoming**")
        if not snap.seas_incoming:
            st.write("_none_")
        for s in snap.seas_incoming:
            st.write(f"- #{s.id} ({s.state}) ← {s.from_handle}: {s.description}")
        st.markdown("**Outgoing**")
        if not snap.seas_outgoing:
            st.write("_none_")
        for s in snap.seas_outgoing:
            st.write(f"- #{s.id} ({s.state}) → {s.to_handle}: {s.description}")

    with cols[1]:
        st.subheader("Outstanding analysis")
        st.caption("what does each result *mean*?")
        if not snap.outstanding:
            st.success("Nothing outstanding.")
        for item in snap.outstanding:
            line = (
                f"{item.scope} {item.target} ({item.project}) — "
                f"state: {item.state}; age: "
                f"{item.age_days if item.age_days is not None else '—'}d"
            )
            if item.severity == "red":
                st.error(line)
            elif item.severity == "yellow":
                st.warning(line)
            else:
                st.write(line)

        st.subheader("Inventory")
        inv = snap.inventory_summary
        for label, rows in (
            ("Expired", inv.get("expired", [])),
            ("Low / out", inv.get("low", [])),
            ("Expiring soon (30d)", inv.get("expiring", [])),
        ):
            st.markdown(f"**{label}**")
            if not rows:
                st.write("_none_")
            for r in rows:
                st.write(f"- {r['name']} ({r['status']}; expiry {r.get('expiry') or '—'})")

    st.subheader("Security and compliance")
    if not snap.compliance:
        st.write("_no per-project compliance rows; not in any project_")
    for row in snap.compliance:
        st.markdown(f"### {row.project} ({row.sensitivity})")
        for cert in row.member_certs:
            badge = {"ok": "✅", "expiring": "🟡", "expired": "🔴", "missing": "🔴"}[cert.status]
            extra = f" (expires {cert.expires})" if cert.expires else ""
            st.write(f"{badge} {cert.name}{extra}")
        for note in row.notes:
            st.warning(note)

    if snap.is_pi:
        st.subheader("PI view: clinical-project compliance grid")
        grid = snap.pi_view.get("clinical_compliance", [])
        if not grid:
            st.write("_no clinical projects_")
        else:
            for row in grid:
                badge = {
                    "ok": "✅",
                    "expiring": "🟡",
                    "expired": "🔴",
                    "missing": "🔴",
                }[row["tcps_status"]]
                line = (
                    f"{badge} **{row['project']}** — {row['member']} "
                    f"(TCPS_2 {row['tcps_status']}, expires {row.get('tcps_expires') or '—'})"
                )
                if row["tcps_status"] in {"missing", "expired"}:
                    st.error(line)
                elif row["tcps_status"] == "expiring":
                    st.warning(line)
                else:
                    st.write(line)


if __name__ == "__main__":  # pragma: no cover
    main()
