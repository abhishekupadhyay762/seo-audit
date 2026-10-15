"""
Compare runs - upload two downloads from this tool (before and after) and see what changed.
The comparison is in seo_checks.py.
"""

import time

import streamlit as st

import seo_checks as checks
import seo_core as core
import seo_ui as ui

DESCRIPTION = (
    "Upload a download from an earlier run and one from a later run of the same tool, to see which issues were "
    "fixed, which are new and what changed. Works with Page audit Excel files too."
)
COVERS = [
    ("Issue trend", "For every issue, how many URLs had it before and after, so progress is easy to report."),
    ("Changed URLs", "Each URL with changed fields, the issues fixed and any new issues."),
    ("All changes", "Every change, field by field, with the value before and after, the on-page score included."),
    ("New and removed URLs", "URLs that appear in only one of the two runs."),
    ("Page audit before and after", "Two Page audit Excel files: the score, every area and every check that changed."),
]


def page_audit_results(result: dict):
    state = st.session_state
    n = result["numbers"]
    b, a = result["before"], result["after"]
    change = n["Change"]
    ui.cards({"Score before": f"{n['Score before']} ({b['grade']})", "Score after": f"{n['Score after']} ({a['grade']})",
              "Change": f"{change:+d}", "Checks fixed": n["Checks fixed"], "New problems": n["New problems"]})
    if b["url"] and a["url"] and core.norm_url(b["url"]) != core.norm_url(a["url"]):
        st.warning(f"The two files are for different pages: {b['url']} and {a['url']}.")
    elif a["url"]:
        st.caption(f"Page: {a['url']}" + (f". Keyword: {a['keyword']}" if a["keyword"] and a["keyword"] != "None" else "") + ".")
    st.subheader("Areas")
    st.dataframe(result["areas"], width="stretch", hide_index=True, height=ui.table_height(len(result["areas"])),
                 column_config={"Change": st.column_config.NumberColumn(format="%+d")})
    st.subheader("Checks that changed")
    changes = result["changes"]
    if changes.empty:
        st.info("No check changed between the two audits.")
    else:
        kinds = [k for k in ("New problem", "Worse", "Fixed", "Better", "Changed") if k in set(changes["Change"])]
        pick = st.multiselect("Show", kinds, default=[], placeholder="Every change", key=f"cmp_pa_{state['cmp_id']}")
        view = changes[changes["Change"].isin(pick)] if pick else changes
        st.dataframe(view, width="stretch", hide_index=True, height=ui.table_height(len(view), 460),
                     column_config={"How To Fix": st.column_config.TextColumn(width="large")})
    row = st.container(horizontal=True)
    ui.download(row, "⬇ Download comparison (Excel)", lambda: checks.page_compare_excel(result, state.get("cmp_info", {})),
                "page-audit-comparison.xlsx", core.XLSX_MIME, "cmp_pa_xlsx", state["cmp_id"], heavy=True)


def main():
    ui.page_header("compare-runs", "Compare runs", DESCRIPTION)
    with st.container(key="deck_compare"):
        c1, c2 = st.columns(2)
        before = c1.file_uploader("Before (the earlier download)", type=["csv", "xlsx"], key="cmp_before")
        after = c2.file_uploader("After (the later download)", type=["csv", "xlsx"], key="cmp_after")
        go = st.button("Compare", type="primary", disabled=not (before and after))

    state = st.session_state
    work = st.container()  # progress and messages go here, so the results below keep their place
    with work:
        if go:
            try:
                audits = (checks.is_page_audit(before), checks.is_page_audit(after))
                if all(audits):
                    state["cmp_result"] = checks.compare_page_audits(checks.load_page_audit(before),
                                                                     checks.load_page_audit(after))
                elif any(audits):
                    raise ValueError("one file is a Page audit download and the other is not. Upload two Page audit "
                                     "Excel files, or two downloads from the same other tool.")
                else:
                    state["cmp_result"] = checks.compare_runs(checks.load_export(before), checks.load_export(after))
                state["cmp_info"] = {"Before": before.name, "After": after.name}
                state["cmp_id"] = time.time()
            except Exception as e:
                st.error(f"These files could not be compared: {e}")
                state.pop("cmp_result", None)

    result = state.get("cmp_result")
    if result is None:
        ui.covers("What the comparison shows", COVERS)
        return
    if result.get("page_audit"):
        page_audit_results(result)
        return

    n = result["numbers"]
    ui.cards({"URLs in both": n["In both"], "New URLs": n["New URLs"], "Removed URLs": n["Removed URLs"],
              "URLs with changes": n["URLs with changes"], "Issues fixed": n["Issues fixed"], "New issues": n["New issues"]})
    tabs = st.tabs(["Issue trend", f"Changed URLs ({len(result['per_url']):,})", f"All changes ({len(result['changes']):,})",
                    f"New URLs ({n['New URLs']:,})", f"Removed URLs ({n['Removed URLs']:,})"])
    with tabs[0]:
        trend = result["trend"].assign(Direction=result["trend"]["Change"].map(
            lambda c: "Fewer URLs" if c < 0 else ("More URLs" if c > 0 else "No change")))
        st.dataframe(trend, width="stretch", hide_index=True, height=420)
        st.caption("Negative change means fewer URLs have the issue in the later run.")
    with tabs[1]:
        st.dataframe(result["per_url"], width="stretch", hide_index=True, height=420,
                     column_config={"URL": st.column_config.LinkColumn("URL", pinned=True, width="medium")})
    with tabs[2]:
        fields = sorted(result["changes"]["Field"].unique()) if not result["changes"].empty else []
        pick = st.multiselect("Fields", fields, default=[], placeholder="All fields", key=f"cmp_fields_{state['cmp_id']}")
        view = result["changes"] if not pick else result["changes"][result["changes"]["Field"].isin(pick)]
        st.dataframe(view, width="stretch", hide_index=True, height=420,
                     column_config={"URL": st.column_config.LinkColumn("URL", pinned=True, width="medium")})
    with tabs[3]:
        st.dataframe(result["added"], width="stretch", hide_index=True, column_config={"URL": st.column_config.LinkColumn("URL")})
    with tabs[4]:
        st.dataframe(result["removed"], width="stretch", hide_index=True, column_config={"URL": st.column_config.LinkColumn("URL")})
    row = st.container(horizontal=True)
    ui.download(row, "⬇ Download comparison (Excel)", lambda: checks.compare_excel_bytes(result, state.get("cmp_info", {})),
                "run-comparison.xlsx", core.XLSX_MIME, "cmp_xlsx", state["cmp_id"], heavy=True)


if __name__ == "__main__":
    main()
