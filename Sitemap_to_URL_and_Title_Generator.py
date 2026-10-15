"""
SEO Audit Toolkit - main file (this is the file Streamlit runs)

It only sets up the page, the sidebar and the list of tools. The tools themselves are in:
  page_sitemap.py      Sitemap audit
  page_crawl.py        Site crawl (with site structure, link score, duplicates and images)
  page_bulk.py         Bulk URL check
  page_audit.py        Page audit (one URL, on-page score, competitors)
  page_content.py      Content check (readability and content analysis)
  page_keywords.py     Keyword check
  page_competitors.py  Competitor comparison and content brief
  page_links.py        Internal link opportunities
  page_duplicates.py   Duplicate content
  page_schema.py       Schema check
  page_search.py       Custom search and extraction
  page_ai.py           AI crawlers and robots.txt
  page_redirects.py    Redirect check (site migrations)
  page_staging.py      Staging vs live (before a redesign or migration goes live)
  page_compare.py      Compare runs (and Page audit before / after)
  page_saved.py        Open a saved run
Shared code:
  seo_core.py          fetching, reading pages, issue rules, sitemap reading, exports
  seo_crawl.py         site crawl, link checks and image checks
  seo_checks.py        canonical / hreflang targets, keywords, redirects, comparisons, XML sitemap, saved runs
  seo_page.py          page audit: score, readability, content, schema fields, mobile vs desktop
  seo_content.py       content check, schema check, competitor comparison, link opportunities
  seo_tech.py          duplicates, custom search, staging vs live, site structure, AI crawlers
  seo_report.py        the Word reports, branding and the advice for every issue
  seo_ui.py            look, sidebar and the results view

Run locally:  python -m streamlit run Sitemap_to_URL_and_Title_Generator.py
"""

import streamlit as st

import seo_ui as ui

st.set_page_config(page_title=ui.APP_NAME, page_icon="🔎", layout="wide")

TOOLS = {
    "Audit": [
        st.Page("page_sitemap.py", title="Sitemap audit", icon=":material/account_tree:", url_path="sitemap-audit", default=True),
        st.Page("page_crawl.py", title="Site crawl", icon=":material/travel_explore:", url_path="site-crawl"),
        st.Page("page_bulk.py", title="Bulk URL check", icon=":material/checklist:", url_path="bulk-url-check"),
        st.Page("page_audit.py", title="Page audit", icon=":material/fact_check:", url_path="page-audit"),
    ],
    "Content": [
        st.Page("page_content.py", title="Content check", icon=":material/article:", url_path="content-check"),
        st.Page("page_keywords.py", title="Keyword check", icon=":material/key:", url_path="keyword-check"),
        st.Page("page_competitors.py", title="Competitor comparison", icon=":material/leaderboard:",
                url_path="competitor-comparison"),
        st.Page("page_links.py", title="Link opportunities", icon=":material/add_link:", url_path="link-opportunities"),
        st.Page("page_duplicates.py", title="Duplicate content", icon=":material/content_copy:", url_path="duplicate-content"),
    ],
    "Technical": [
        st.Page("page_schema.py", title="Schema check", icon=":material/data_object:", url_path="schema-check"),
        st.Page("page_search.py", title="Custom search", icon=":material/manage_search:", url_path="custom-search"),
        st.Page("page_ai.py", title="AI crawlers and robots.txt", icon=":material/smart_toy:", url_path="ai-crawlers"),
        st.Page("page_redirects.py", title="Redirect check", icon=":material/alt_route:", url_path="redirect-check"),
    ],
    "Compare": [
        st.Page("page_staging.py", title="Staging vs live", icon=":material/difference:", url_path="staging-vs-live"),
        st.Page("page_compare.py", title="Compare runs", icon=":material/compare_arrows:", url_path="compare-runs"),
        st.Page("page_saved.py", title="Open a saved run", icon=":material/folder_open:", url_path="open-saved-run"),
    ],
}

current = st.navigation([page for pages in TOOLS.values() for page in pages], position="hidden")
ui.frame(TOOLS)
current.run()
