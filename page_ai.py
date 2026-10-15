"""
AI crawlers and robots.txt - which search and AI crawlers the site lets in, what the server answers them,
and a tester for a draft robots.txt. The checks are in seo_tech.py; the shared look is in seo_ui.py.
"""

import time
from urllib.parse import urlsplit

import streamlit as st

import seo_core as core
import seo_tech as tech
import seo_ui as ui

DESCRIPTION = (
    "See which search engines and AI crawlers (ChatGPT, Claude, Perplexity, Gemini and others) the site lets in, "
    "whether the server or firewall blocks them anyway, and test a robots.txt change before it goes live."
)
COVERS = [
    ("robots.txt per crawler", "Allowed or blocked for each crawler and each address you test, with the rule that decides."),
    ("Blocked by the server", "Whether the homepage answers each crawler's User-Agent, or a firewall or CDN blocks it."),
    ("Training versus search", "Which crawlers train AI models and which show your site in AI answers, so you can choose."),
    ("Test a draft robots.txt", "Paste a new robots.txt and see what would change for every crawler before it goes live."),
    ("robots.txt problems", "Lines Google ignores (Noindex, Crawl-delay), the size limit and the sitemaps listed."),
    ("llms.txt", "Whether the site has an llms.txt file (a proposal some AI tools read; Google does not use it)."),
]
KIND_NOTES = {
    "Search engine": "Search engines. Blocking them removes the site from their results.",
    "AI search": "Crawlers that show and link to your pages in AI answers (ChatGPT search, Claude, Perplexity). "
                 "Blocking them usually means fewer AI citations.",
    "User request": "Fetches made when a user asks the assistant to open a page. They may not follow robots.txt.",
    "AI training": "Crawlers (or tokens) that decide whether your content can be used to train AI models. Blocking "
                   "them does not affect Google Search.",
}
LINK = st.column_config.LinkColumn


def results(result: dict, paths: list):
    state = st.session_state
    run_id, info = state.get("ai_run_id"), state.get("ai_info", {})
    table = result["table"]
    ui.cards({"robots.txt": "Found" if result["robots_status"] == 200 else "Not found",
              "llms.txt": "Found" if result["llms"]["found"] else "Not found",
              **{k.replace(": allowed", ""): v for k, v in tech.ai_summary(table, paths[0]).items()}})
    st.caption(f"robots.txt: {result['robots_state']}. Counts are for {paths[0]}; the table shows every address you tested.")
    for note in result["notes"]:
        st.warning(note)
    if result["chrome"] is not None and result["chrome"] != 200:
        st.warning(f"The homepage answered {result['chrome']} even to a normal Chrome browser, so the server answers "
                   "below may not tell you much.")

    kinds = st.segmented_control("Crawler type", ["All"] + tech.BOT_KINDS, default="All", key=f"ai_kind_{run_id}") or "All"
    view = table if kinds == "All" else table[table["Type"] == kinds]
    if kinds != "All":
        st.caption(KIND_NOTES[kinds])
    st.dataframe(view, width="stretch", hide_index=True, height=ui.table_height(len(view), 680),
                 column_config={"Crawler": st.column_config.TextColumn(pinned=True),
                                "What It Does": st.column_config.TextColumn(width="large")})
    st.caption("Rules Followed shows which group of robots.txt a crawler obeys: its own group when one names it, "
               "otherwise the * group. The server answer is what the homepage returns to that crawler's User-Agent; "
               "real crawlers are also checked by IP address, so a firewall may treat them differently.")
    with st.expander("What each type means"):
        st.markdown("\n".join(f"- **{k}.** {v}" for k, v in KIND_NOTES.items()))
        st.markdown("- **Google-Extended** and **Applebot-Extended** are robots.txt tokens, not crawlers: Googlebot and "
                    "Applebot do the crawling, and these tokens only control AI training use. AI Overviews in Google "
                    "Search are controlled by Googlebot, not Google-Extended.")
    if result["sitemaps"]:
        st.caption("Sitemaps listed in robots.txt: " + ", ".join(result["sitemaps"]))
    if result["robots_text"]:
        with st.expander("The robots.txt file"):
            st.code(result["robots_text"][:20000], language=None)

    draft = state.get("ai_draft")
    if draft is not None:
        st.subheader("Draft robots.txt compared with the live one")
        changed = draft[draft["Changes"] == "Yes"]
        if changed.empty:
            st.success("The draft gives every crawler the same access as the live file for the addresses tested.")
        else:
            st.dataframe(changed, width="stretch", hide_index=True, height=ui.table_height(len(changed), 460))
        with st.expander(f"Every crawler and address ({len(draft):,} rows)"):
            st.dataframe(draft, width="stretch", hide_index=True, height=ui.table_height(len(draft), 460))
    row = st.container(horizontal=True)
    ui.download(row, "⬇ Download Excel", lambda: tech.ai_excel(result, draft, info), "ai-crawlers-robots.xlsx",
                core.XLSX_MIME, "ai_xlsx", run_id, heavy=True)


def main():
    settings = ui.crawl_settings(show_max=False)
    ui.page_header("ai-crawlers", "AI crawlers and robots.txt", DESCRIPTION)
    state = st.session_state

    with st.container(key="deck_ai"):
        c1, c2 = st.columns([2, 3])
        site = c1.text_input("Website", placeholder="example.com")
        paths_text = c2.text_area("Addresses to test (optional, one per line)", height=90,
                                  placeholder="/\n/blog/\n/products/blue-widget",
                                  help="Paths or full URLs on the site. The homepage is always tested.")
        draft_text = st.text_area("Draft robots.txt to test (optional)", height=130,
                                  placeholder="User-agent: *\nDisallow: /cart/\n\nUser-agent: GPTBot\nDisallow: /")
        go = st.button("Check crawlers", type="primary")

    work = st.container()  # progress and messages go here, so the results below keep their place
    with work:
        if go:
            base = tech.base_of(site)
            if not base:
                st.warning("Enter the website address, for example example.com")
            else:
                base = core.origin_of(base)
                paths = ["/"]
                for line in paths_text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    if "://" in line or line.startswith("www."):
                        parts = urlsplit(core.normalize_url(line) or "/")
                        line = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
                    if not line.startswith("/"):
                        line = "/" + line
                    if line not in paths:
                        paths.append(line)
                with st.spinner("Reading robots.txt and asking the server as each crawler..."):
                    result = tech.check_ai_access(base, min(settings["timeout"], 20), paths, settings.get("headers"),
                                                  settings.get("auth"))
                state["ai_result"], state["ai_paths"], state["ai_run_id"] = result, paths, time.time()
                state["ai_draft"] = tech.draft_compare(result, draft_text, paths) if draft_text.strip() else None
                state["ai_info"] = {"Website": base, **ui.run_info(settings)}

    if not state.get("ai_result"):
        ui.covers("What the check covers", COVERS)
        return
    results(state["ai_result"], state.get("ai_paths", ["/"]))


if __name__ == "__main__":
    main()
