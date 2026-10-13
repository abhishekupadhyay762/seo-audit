"""
Competitor comparison - your page (or a page you plan to write) next to up to five competitors,
with targets, the phrases and headings they use, the questions they answer, and a content brief.
The comparison is in seo_content.py; each page is read with seo_page.audit_page.
"""

import re
import time

import streamlit as st

import seo_content as content
import seo_core as core
import seo_page as page
import seo_ui as ui

DESCRIPTION = (
    "Compare your page with the pages that rank for your keyword, or plan a new page from them. Get word count "
    "targets, headings, questions and phrases to cover, and a content brief for your writer."
)
COVERS = [
    ("Side by side", "On-page score, title, meta, H1, word count, headings, readability, images, links and schema."),
    ("Targets", "How long the page should be, how many H2s and images, and the reading ease to aim for."),
    ("Phrases to cover", "Two and three word phrases the competitors repeat that your page does not use."),
    ("Suggested H2s", "The H2 headings competitors share, the most common first."),
    ("Questions to answer", "Question headings and FAQ markup from the competing pages."),
    ("Content brief", "A Word document with all of the above, ready to hand to a writer."),
]
LINK = st.column_config.LinkColumn


def run(keyword: str, yours: str, comps: list, settings: dict):
    session = core.make_session(settings["workers"], settings["user_agent"])
    pages = ([("Your page", yours)] if yours else []) + [(f"Competitor {i}", u) for i, u in enumerate(comps, 1)]
    audits = {}
    with st.status("Reading the pages", expanded=True) as status:
        for label, url in pages:
            line = st.empty()
            line.caption(f"{label}: {url}")
            try:
                audits[label] = page.audit_page(session, url, settings, keyword, check_links=False,
                                                check_targets=False, mobile="")
            except Exception as e:
                st.warning(f"{label} was skipped: {e}")
            line.empty()
        comp_audits = [audits[label] for label, _ in pages if label != "Your page" and label in audits]
        if not comp_audits:
            status.update(label="No competitor page could be read", state="error")
            return
        result = content.compare_competitors(audits.get("Your page"), comp_audits, keyword)
        status.update(label="Comparison complete", state="complete", expanded=False)
    state = st.session_state
    state["cc_result"] = result
    state["cc_run_id"] = time.time()
    state["cc_info"] = {"Keyword": keyword or "None", **ui.run_info(settings)}


def results(result: dict):
    state = st.session_state
    run_id = state.get("cc_run_id")
    t, y = result["targets"], result["yours"]
    numbers = {"Pages compared": len(result["pages"])}
    if t["words"]:
        numbers["Words to aim for"] = f"{t['words'][0]:,}–{t['words'][1]:,}"
    if y:
        numbers["Your page, words"] = y["words"]
        numbers["Your on-page score"] = f"{y['score']} ({y['grade']})"
    numbers["Phrases to cover"] = len(result["gaps"])
    ui.cards(numbers)
    failed = [label for label, _, _, status in result["pages"] if status != 200]
    if failed:
        st.warning("These pages did not answer 200, so their numbers are incomplete: " + ", ".join(failed) + ".")

    st.subheader("Targets")
    tt = content.targets_table(result)
    st.dataframe(tt, width="stretch", hide_index=True, height=ui.table_height(len(tt)),
                 column_config={"Aim For": st.column_config.TextColumn(width="large")})
    st.caption("Targets come from the competitors' median. Treat them as a guide: the page has to answer the search "
               "better, not just be longer.")

    names = ["Side by side", f"Phrases to cover ({len(result['gaps'])})", f"Suggested H2s ({len(result['suggested'])})",
             f"Questions ({len(result['questions'])})", "Titles and metas", "Schema", "All headings"]
    tabs = st.tabs(names)
    with tabs[0]:
        st.dataframe(result["table"], width="stretch", hide_index=True, height=ui.table_height(len(result["table"]), 720),
                     column_config={"Measure": st.column_config.TextColumn(pinned=True)})
        st.caption("Every page is read the same way (without link checks or the smartphone comparison), so the scores "
                   "compare directly. Score rows show points out of the points available.")
    with tabs[1]:
        if result["gaps"].empty:
            st.success("No repeated competitor phrase is missing from your page." if y else
                       "The competitors repeat no phrase in common.")
        else:
            need = "at least two competitors" if (len(result["pages"]) - (1 if y else 0)) >= 2 else "the competitor"
            st.caption(f"Two and three word phrases that {need} use more than once"
                       + (" and your page does not use." if y else ".") + " Use the ones that fit the topic.")
            st.dataframe(result["gaps"], width="stretch", hide_index=True, height=ui.table_height(len(result["gaps"]), 460))
    with tabs[2]:
        if result["suggested"].empty:
            st.info("The competitors have no H2 headings.")
        else:
            st.dataframe(result["suggested"], width="stretch", hide_index=True,
                         height=ui.table_height(len(result["suggested"]), 460),
                         column_config={"Heading": st.column_config.TextColumn(width="large")})
            st.caption("Headings with the same main words count as one. Rewrite them in your own words.")
    with tabs[3]:
        if result["questions"].empty:
            st.info("No question headings or FAQ markup were found on the competing pages.")
        else:
            st.dataframe(result["questions"], width="stretch", hide_index=True,
                         height=ui.table_height(len(result["questions"]), 460),
                         column_config={"Question": st.column_config.TextColumn(width="large")})
    with tabs[4]:
        st.dataframe(result["titles"], width="stretch", hide_index=True,
                     column_config={"Title": st.column_config.TextColumn(width="large"),
                                    "Meta Description": st.column_config.TextColumn(width="large")})
    with tabs[5]:
        st.dataframe(result["schema"], width="stretch", hide_index=True)
        if result["schema_gap"]:
            st.info(("Types competitors use that your page does not: " if y else "Types the competitors use: ")
                    + ", ".join(result["schema_gap"]))
    with tabs[6]:
        st.dataframe(result["headings"], width="stretch", hide_index=True,
                     height=ui.table_height(len(result["headings"]), 520),
                     column_config={"Heading": st.column_config.TextColumn(width="large")})

    info = state.get("cc_info", {})
    brand = ui.branding()
    row = st.container(horizontal=True)
    slug = re.sub(r"[^a-z0-9]+", "-", (result["keyword"] or "").lower()).strip("-")[:50]
    stem = "content-brief" + (f"-{slug}" if slug else "")
    ui.download(row, "⬇ Download content brief (Word)", lambda: content.build_brief(result, brand), f"{stem}.docx",
                ui.DOCX_MIME, "cc_docx", run_id, heavy=True)
    ui.download(row, "⬇ Download Excel", lambda: content.competitor_excel(result, info), "competitor-comparison.xlsx",
                core.XLSX_MIME, "cc_xlsx", run_id, heavy=True)
    st.caption("The content brief opens in Google Docs and Word: targets, suggested headings, questions, phrases, "
               "schema and the competitors' titles, with links to every page analysed.")


def main():
    settings = ui.crawl_settings(show_max=False)
    ui.page_header("competitor-comparison", "Competitor comparison", DESCRIPTION)

    with st.container(key="deck_competitors"):
        c1, c2 = st.columns([2, 3])
        keyword = c1.text_input("Target keyword", placeholder="local seo services",
                                help="Used for keyword checks and to name the content brief.")
        yours = c2.text_input("Your page URL (optional)", placeholder="https://example.com/services/local-seo",
                              help="Leave empty when you are planning a new page.")
        comps_text = st.text_area(f"Competitor URLs (up to {content.MAX_COMPETITORS}, one per line)", height=130,
                                  placeholder="https://competitor-one.com/local-seo\nhttps://competitor-two.com/seo-services",
                                  help="The pages ranking on the first page of Google for the keyword.")
        go = st.button("Compare pages", type="primary")

    if go:
        mine = core.normalize_url(yours) if core.looks_like_url(yours) else ""
        comps = []
        for line in comps_text.splitlines():
            u = core.normalize_url(line) if core.looks_like_url(line) else ""
            if u and u not in comps and core.norm_url(u) != core.norm_url(mine or "-"):
                comps.append(u)
        if yours.strip() and not mine:
            st.warning("Your page URL does not look like a web address. Enter the full address, or leave it empty.")
        elif not comps:
            st.warning("Add at least one competitor URL.")
        else:
            if len(comps) > content.MAX_COMPETITORS:
                st.info(f"Only the first {content.MAX_COMPETITORS} competitor URLs are compared.")
                comps = comps[: content.MAX_COMPETITORS]
            run(keyword.strip(), mine, comps, settings)

    result = st.session_state.get("cc_result")
    if not result:
        ui.covers("What the comparison covers", COVERS)
        return
    results(result)


if __name__ == "__main__":
    main()
