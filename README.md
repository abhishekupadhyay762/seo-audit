# SEO Audit Toolkit (Streamlit)

One app, eleven tools (switch in the left sidebar).

**Audit**
1. **Sitemap audit** - enter a sitemap URL or a domain. Lists every URL in the sitemap, finds problems in
   the sitemap itself, then checks the pages you choose.
2. **Site crawl** - starts at the homepage and follows internal links. Checks every page found, compares
   the crawl with the sitemap (orphan pages, pages missing from the sitemap) and checks every link.
3. **Bulk URL check** - paste or upload URLs. Status, redirects, indexability, title, meta, headings,
   content, images, schema, hreflang, links and issues for each URL. Options: check every link on the
   pages, and compare the smartphone and desktop versions of each page.
4. **Page audit** - one URL in full, with an on-page score out of 100 and the points behind every check,
   what to fix first, a Google result preview, readability, content, schema fields, smartphone versus
   desktop and up to three competitors. Word report and Excel download.

Sitemap audit, Site crawl and Bulk URL check also give every page an on-page score (same checks as Page
audit, without the link checks), so you can sort a whole site and fix the weakest pages first.

**Content**
5. **Content check** - paste a draft (for example from Google Docs) or check many live pages: reading
   ease, long sentences and paragraphs, most used words and phrases, keyword use and what to improve.
6. **Keyword check** - URL plus target keyword. Shows whether the keyword is in the title, H1, meta
   description, URL, first 100 words and H2s, and flags URLs that compete for the same keyword.
7. **Competitor comparison** - your page (or a page you plan) next to up to five competitors: targets,
   phrases to cover, suggested H2s, questions to answer, titles and schema. Downloads a content brief (Word).
8. **Link opportunities** - the page that should rank plus its keywords. Finds pages on the site that
   mention a keyword but do not link to that page from their content, with the sentence to link from.

**Technical**
9. **Schema check** - many URLs, every URL in a sitemap, or pasted code: each schema type with the
   required and recommended fields it is missing, and broken JSON-LD with the line of the error.
10. **Redirect check** - old URL plus expected new URL (a migration redirect map). Confirms each old URL
    lands on the right page in one permanent redirect.

**Compare**
11. **Compare runs** - upload two downloads from this tool (before and after) to see fixed and new issues
    and score changes. Two Page audit Excel files show the score, area and check changes for one page.

Every audit tool can download CSV, Excel, a client report (Word, opens in Google Docs) and an XML
sitemap of the indexable URLs it found.

## Your agency branding on the Word reports

Open **Report branding** in the sidebar (under the tool list) and enter your agency name, the client name and a
logo (PNG or JPG). To make it permanent, set `AGENCY_NAME` at the top of `seo_report.py` and save your
logo as `report_logo.png` in the tool's folder.

## Folder structure (keep it exactly like this)

    sitemap-audit/
      Sitemap_to_URL_and_Title_Generator.py   main file (the one Streamlit runs)
      page_sitemap.py                         Sitemap audit screen
      page_audit.py                           Page audit screen
      page_content.py                         Content check screen
      page_competitors.py                     Competitor comparison screen
      page_links.py                           Link opportunities screen
      page_schema.py                          Schema check screen
      page_crawl.py                           Site crawl screen
      page_bulk.py                            Bulk URL check screen
      page_keywords.py                        Keyword check screen
      page_redirects.py                       Redirect check screen
      page_compare.py                         Compare runs screen
      seo_core.py                             fetching, page checks, issue rules, sitemap reading, exports
      seo_crawl.py                            site crawl and link checks
      seo_checks.py                           canonical / hreflang targets, keywords, redirects, compare, XML sitemap
      seo_report.py                           Word client report, branding and the advice text for every issue
      seo_page.py                             page audit: score, readability, content, schema fields, mobile vs desktop
      seo_content.py                          content check, schema check, competitor comparison, link opportunities
      seo_ui.py                               look, sidebar and the results view
      requirements.txt
      report_logo.png                         optional: your logo for the Word reports
      .streamlit/
        config.toml                           colours and fonts

## Run on your computer

    pip install -r requirements.txt
    python -m streamlit run Sitemap_to_URL_and_Title_Generator.py

The browser opens http://localhost:8501. After replacing files, stop the tool (Ctrl+C) and start it again.

## Put it live (Streamlit Community Cloud)

Upload the same files and the `.streamlit` folder to the GitHub repo. The main file name is unchanged, so
the app redeploys by itself. If it shows an error after an update, open Manage app and choose Reboot app.

## Change the look, the wording or the limits

- Colours and fonts: `.streamlit/config.toml`
- Tool name: `APP_NAME` at the top of `seo_ui.py`
- Advice text in the client report: `ADVICE` in `seo_report.py`
- Limits and thresholds: the settings block at the top of `seo_core.py`, `seo_crawl.py` and `seo_checks.py`
- Page audit score weights, grades and schema field rules: the top of `seo_page.py`
