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
    "Upload a CSV or Excel download from an earlier run and one from a later run of any audit tool here, to see "
    "which issues were fixed, which are new and what changed on each URL."
)
COVERS = [
    ("Issue trend", "For every issue, how many URLs had it before and after, so progress is easy to report."),
    ("Changed URLs", "Each URL with changed fields, the issues fixed and any new issues."),
    ("All changes", "Every change, field by field, with the value before and after."),
    ("New and removed URLs", "URLs that appear in only one of the two runs."),
]


def main():
    ui.page_header("compare-runs", "Compare runs", DESCRIPTION)
    with st.container(key="deck_compare"):
        c1, c2 = st.columns(2)
        before = c1.file_uploader("Before (the earlier download)", type=["csv", "xlsx"], key="cmp_before")
        after = c2.file_uploader("After (the later download)", type=["csv", "xlsx"], key="cmp_after")
        go = st.button("Compare", type="primary", disabled=not (before and after))

    state = st.session_state
    if go:
        try:
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
