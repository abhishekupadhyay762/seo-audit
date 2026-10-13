"""
SEO Audit Toolkit - client report (Word .docx, opens in Word and Google Docs)

build_report() turns a results table into a short report: summary, priority issues with why each
matters, how to fix it and example URLs, then notices and any tool-specific sections.
ADVICE holds the explanation for every issue the tool can raise; edit the wording here.
"""

import io
import re
from datetime import date
from urllib.parse import urlsplit

import os

import pandas as pd
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

import seo_core as core

EXAMPLE_URLS = 10      # example URLs listed under each issue
LINK_COLOR = "1A0DAB"

# Branding on every Word report. Both can also be changed for one session under Report branding in the sidebar.
AGENCY_NAME = ""                   # your agency name, e.g. "RocketTech"
LOGO_FILE = "report_logo.png"      # put a PNG or JPG logo with this name next to this file

# issue name (without the part in brackets) -> (why it matters, how to fix)
ADVICE = {
    # ---- smartphone vs desktop (Bulk URL check option)
    "Smartphone and desktop versions differ": (
        "Google indexes the smartphone version of a page. Anything missing or different there (title, headings, "
        "content, links, tags) is what Google sees.",
        "Serve the same title, meta description, headings, main content, links, canonical and robots tags to phones "
        "and desktops. Check responsive templates and any separate mobile site or dynamic serving rules."),
    # ---- status, redirects, fetching
    "Blocked by robots.txt": (
        "Googlebot is not allowed to crawl this URL, so Google cannot read its content. A blocked page can still be "
        "indexed from links, but without a proper title or description.",
        "If the page should rank, remove or narrow the Disallow rule in robots.txt that matches it. To keep a page out "
        "of Google, allow crawling and use a noindex tag instead."),
    "robots.txt could not be read": (
        "When robots.txt returns a server error or times out, Google may pause crawling the whole site until it can read it.",
        "Make sure /robots.txt answers quickly with 200 (or 404 if the site has none). Check server, firewall and CDN rules for the file."),
    "Redirect loop / too many redirects": (
        "Browsers and Google give up on the URL, so the page cannot be reached or indexed.",
        "Trace the redirect rules and change them so the URL redirects once, straight to a page that returns 200."),
    "Redirect to an invalid target": (
        "The redirect points to an address that is not a web page, so visitors and Google cannot follow it.",
        "Change the redirect target to the correct full https:// URL."),
    "Fetch failed": (
        "The URL did not answer (timeout, connection or SSL error). If Google sees the same, the page cannot be crawled.",
        "Open the URL in a browser. If it fails there too, check the server, DNS and SSL certificate. If it works in a "
        "browser, the server may be blocking automated requests: run the check again with the Chrome option."),
    "Redirect chain": (
        "Each extra hop slows the page down for visitors and wastes crawl budget. Google stops following long chains.",
        "Point the first URL, and every internal link to it, straight at the final destination."),
    "Temporary redirect": (
        "A temporary redirect tells Google the move may be undone, so the old URL can stay indexed.",
        "If the move is permanent, change the redirect to a 301 (or 308)."),
    "URL redirects": (
        "The URL is not a final page. Linking to or listing a redirecting URL adds a hop for every visit and crawl.",
        "Update internal links, canonical tags and the sitemap to use the final URL directly."),
    "Redirects to an error page": (
        "Visitors and Google land on an error, so any value the old URL had is lost.",
        "Change the redirect to point at a live, relevant page that returns 200."),
    "5xx server error": (
        "The server failed to deliver the page. Repeated server errors make Google crawl less and can drop pages from the index.",
        "Check the server logs for the error, fix the cause and confirm the URL returns 200."),
    "4xx client error": (
        "The page does not exist or is not accessible. Links to it are wasted and it cannot rank.",
        "If the content moved, add a 301 redirect to the new URL. If it is gone for good, remove links to it and "
        "remove it from the sitemap."),
    "Unexpected status code": (
        "The URL returned an unusual status (such as 204), so there is no page content to index.",
        "Make sure the URL returns 200 with its content, or redirect it."),
    "Noindex": (
        "A noindex directive (meta robots tag or X-Robots-Tag header) keeps the page out of search results.",
        "If the page should rank, remove the noindex. If it should stay out of search, remove it from the sitemap."),
    "Non-HTML file": (
        "The URL is a file such as a PDF, so the on-page checks do not apply.",
        "No action needed, unless the file should not be indexed; then send an X-Robots-Tag: noindex header for it."),
    "HTML could not be read": (
        "The page returned 200 but its HTML could not be read, so its content could not be checked.",
        "Open the page source in a browser and check for an empty or broken response."),
    # ---- indexability
    "Canonical missing": (
        "Without a canonical tag Google chooses the main version itself, for example when the page is also reachable "
        "with parameters or a different trailing slash.",
        "Add a self-referencing canonical tag with the page's full https:// URL to the <head>."),
    "Canonicalised to another URL": (
        "The canonical tag points to a different URL, so this page is treated as a duplicate and will not be the version shown in search.",
        "Confirm this is intended. If this page should rank, change the canonical to point to itself."),
    "Multiple canonical tags": (
        "With canonical tags pointing to different URLs, Google ignores them and chooses itself.",
        "Keep one canonical tag in the <head>. This often happens when a theme and an SEO plugin both add one."),
    "Relative canonical URL": (
        "A relative canonical (such as /page) works, but breaks easily across http, https, www and non-www versions.",
        "Use the full address, for example https://www.example.com/page."),
    "Not HTTPS": (
        "The page loads over http, which browsers mark as not secure. HTTPS is also a small ranking signal.",
        "Serve the site over HTTPS and 301 redirect every http URL to its https version."),
    "Meta refresh redirect": (
        "A meta refresh is slower than a server redirect and may not pass signals as reliably.",
        "Replace it with a 301 redirect on the server."),
    "Possibly JS-rendered": (
        "The HTML holds very little content and looks like a JavaScript app. Google renders JavaScript later and less "
        "reliably, and this audit does not run JavaScript, so content checks for these pages may be wrong.",
        "Check the page with URL Inspection in Search Console. Server-side rendering or pre-rendering puts content "
        "and links straight into the HTML."),
    # ---- title and meta
    "Title missing": (
        "The title is the headline in search results and a strong relevance signal. Without one, Google writes its own.",
        "Add a unique, descriptive title of about 50 to 60 characters with the main keyword near the start."),
    "Title too long": (
        "Google cuts titles wider than about 600 pixels, so the end of the title is not shown.",
        "Shorten the title to about 50 to 60 characters and keep the important words first."),
    "Title too short": (
        "A very short title wastes space in search results and gives Google little context.",
        "Expand the title to describe the page, with the main keyword and, where useful, the brand or location."),
    "Duplicate title": (
        "Several pages share the same title, so Google and searchers find it hard to tell them apart.",
        "Write a unique title for each page that says what is different about it."),
    "Multiple title tags": (
        "With more than one title tag, Google may use the wrong one.",
        "Keep one title tag in the <head>; check the theme and SEO plugin for duplicates."),
    "Meta description missing": (
        "Without a meta description Google takes text from the page for the snippet, which may not be the best reason to click.",
        "Write a unique description of about 120 to 155 characters that sums up the page and invites the click."),
    "Meta description too long": (
        "Google cuts descriptions after about 155 to 160 characters, so the end is not shown.",
        "Shorten it to about 120 to 155 characters with the key message first."),
    "Meta description too short": (
        "A very short description leaves space unused and gives searchers little reason to click.",
        "Expand it to about 120 to 155 characters describing the page and its benefit."),
    "Duplicate meta description": (
        "Several pages share the same description, so their snippets look alike and Google is more likely to rewrite them.",
        "Write a unique description for each page."),
    "Multiple meta descriptions": (
        "With more than one meta description, Google may use the wrong one.",
        "Keep one meta description tag in the <head>."),
    # ---- headings and content
    "H1 missing": (
        "The H1 is the main heading for visitors and a clear topic signal for search engines.",
        "Add one H1 that names the page's topic, usually close to the title."),
    "H1 empty": (
        "The H1 tag exists but holds no text, so it adds no meaning.",
        "Put the main heading text in the H1, or give an image inside it a descriptive alt text."),
    "Multiple H1": (
        "Several H1s are allowed, but one clear main heading makes the page easier to understand.",
        "Keep one H1 for the main topic and change the others to H2 or H3."),
    "Heading levels skipped": (
        "Jumping from H2 to H4 breaks the outline that screen readers and search engines use.",
        "Use heading levels in order: H2 for sections, H3 for sub-sections."),
    "Thin content": (
        "Pages with little main content often lack the detail needed to rank, especially for informational searches.",
        "Expand the content to fully answer the searcher's question, or merge thin pages into a stronger one. "
        "Pages such as contact forms can be left as they are."),
    "Very large HTML": (
        "The HTML is over 3 MB, which is slow to download; only the first part was checked.",
        "Reduce inline code and data in the HTML, and split very long lists into pages."),
    # ---- images, schema, tags, links on the page
    "Images missing alt attribute": (
        "Alt text describes images to screen readers and image search. A missing alt attribute is an accessibility error.",
        'Add descriptive alt text to content images. Use an empty alt="" for purely decorative images.'),
    "Images without width/height": (
        "Without width and height the browser cannot reserve space, so the layout jumps as images load (Cumulative Layout Shift).",
        "Add width and height attributes, or a CSS aspect-ratio, to images."),
    "Invalid JSON-LD schema": (
        "A JSON-LD block that does not parse is ignored, so the page loses that structured data.",
        "Fix the syntax (often a trailing comma or an unescaped quote) and test it with Google's Rich Results Test."),
    "No schema markup": (
        "Structured data helps Google understand the page and can make it eligible for rich results.",
        "Add the schema that fits: Organization on the homepage, Article on posts, Product on product pages, "
        "LocalBusiness for local businesses."),
    "Viewport tag missing": (
        "Without a viewport tag mobile browsers show the desktop layout zoomed out, which hurts mobile usability.",
        'Add <meta name="viewport" content="width=device-width, initial-scale=1"> to the <head>.'),
    "Lang attribute missing": (
        "The lang attribute tells browsers and screen readers which language the page is in.",
        'Add it to the <html> tag, for example <html lang="en">.'),
    "Open Graph tags incomplete": (
        "Without og:title and og:image, links shared on social networks and messaging apps show a poor preview.",
        "Add og:title, og:description and og:image tags; most SEO plugins can do this."),
    "Links with empty anchor text": (
        "Links without text, such as icon links with no label, give no context to search engines or screen readers.",
        "Add visible link text, or an aria-label or an alt text on the image inside the link."),
    # ---- sitemap files and entries
    "Sitemap file could not be read": (
        "Google cannot read URLs from a sitemap that returns an error.",
        "Make sure every sitemap URL returns 200, or remove broken ones from the sitemap index and robots.txt."),
    "XML error in sitemap file": (
        "Broken XML can stop Google reading the sitemap from the point of the error.",
        "Fix the XML (often an unescaped & in a URL) and validate the file."),
    "Sitemap URL returns a web page, not a sitemap": (
        "The sitemap address returns an HTML page (often an error page), so it lists no URLs.",
        "Point the sitemap index or robots.txt at the correct sitemap URL, or regenerate the sitemap."),
    "Sitemap file format not recognised": (
        "The file is not a valid XML, text or feed sitemap, so search engines cannot use it.",
        "Regenerate the sitemap in the standard XML format."),
    "Sitemap file is empty": (
        "An empty sitemap lists no URLs and adds nothing.",
        "Remove it from the sitemap index, or fix the plugin or script that should fill it."),
    "More than 50,000 URLs in one sitemap file": (
        "The sitemap standard allows at most 50,000 URLs per file, so Google may not read the rest.",
        "Split it into several sitemaps listed in a sitemap index."),
    "Sitemap file larger than 50 MB": (
        "The standard allows at most 50 MB per uncompressed sitemap file.",
        "Split it into smaller sitemaps listed in a sitemap index."),
    "URL is not a full web address": (
        "Sitemaps must list full URLs, including https:// and the domain.",
        "Use full addresses such as https://www.example.com/page."),
    "HTTP URL in the sitemap": (
        "The sitemap lists http addresses on an https site, so Google is sent to URLs that redirect.",
        "List only the https version of each URL."),
    "www / non-www differs from the site": (
        "The sitemap lists the other host version (www or non-www), which normally redirects.",
        "List URLs on the same host the site uses."),
    "URL on a different domain": (
        "A sitemap may only list URLs on its own site, unless cross-site submission is set up in Search Console.",
        "Remove URLs from other domains, or move them to that domain's own sitemap."),
    "Spaces or unencoded characters in URL": (
        "Spaces and some characters must be encoded in URLs, otherwise they can be read wrongly.",
        "Use hyphens instead of spaces in URLs, and percent-encode special characters in the sitemap."),
    "URL longer than 2,048 characters": (
        "Very long URLs can be cut off and are hard to share.",
        "Shorten the URL structure and drop unneeded parameters."),
    "Listed with and without a trailing slash": (
        "Both versions of the URL are listed, which sends mixed signals about which one is the real page.",
        "List only the version that returns 200, and redirect the other one to it."),
    "URL has parameters": (
        "Parameter URLs (such as ?sort= or ?utm_source=) are often duplicates of a cleaner URL.",
        "List only the clean, canonical URL in the sitemap."),
    "Uppercase letters in URL": (
        "URLs are case-sensitive, so mixed case can create duplicate URLs.",
        "Use lowercase URLs and redirect uppercase versions to them."),
    "URL has a # fragment": (
        "Search engines ignore everything after #, so the fragment does nothing in a sitemap.",
        "Remove the # part from sitemap URLs."),
    "Listed more than once in the sitemap": (
        "Duplicate entries do not hurt rankings, but they bloat the sitemap and point to a problem in how it is built.",
        "List each URL once."),
    "Lastmod missing": (
        "Lastmod helps Google decide which pages to recrawl first after changes.",
        "Add a lastmod date to each URL, set to when its content last changed."),
    "Lastmod is not a valid date": (
        "A lastmod in the wrong format is ignored.",
        "Use the W3C date format, for example 2026-05-01 or 2026-05-01T10:00:00+05:30."),
    "Lastmod is in the future": (
        "A future date is clearly wrong, so Google may stop trusting lastmod across the site.",
        "Set lastmod to the real date of the last change, and check the generator's time zone setting."),
    "No XML sitemap found": (
        "Without a sitemap Google finds pages only through links, so new or deep pages can be found late or missed.",
        "Create an XML sitemap (most CMS and SEO plugins can), list it in robots.txt and submit it in Search Console."),
    "Sitemap is not listed in robots.txt": (
        "Listing the sitemap in robots.txt helps every search engine find it.",
        "Add a line such as Sitemap: https://www.example.com/sitemap.xml to robots.txt."),
    "Every lastmod date is the same": (
        "When every URL has the same lastmod the dates are clearly not real, so Google ignores them.",
        "Set each URL's lastmod to the date its own content last changed."),
    "Non-indexable URL in the sitemap": (
        "A sitemap should list only pages you want indexed. Redirects, errors, noindex and canonicalised pages waste "
        "crawl budget and send mixed signals.",
        "Remove these URLs from the sitemap, or fix the pages if they should be indexed."),
    # ---- crawl
    "Indexable page missing from the sitemap": (
        "The page can be indexed but is not in the sitemap, so Google may find and recrawl it more slowly.",
        "Add it to the sitemap, or make it non-indexable if it should not appear in search."),
    "Orphan page": (
        "No page on the site links to it, so visitors cannot reach it and Google treats it as unimportant.",
        "Link to it from relevant pages, or remove it from the sitemap if it is no longer needed."),
    "In the sitemap, not reached by the crawl": (
        "The crawl stopped at its limit before reaching this page, so whether it is linked is unknown.",
        "Raise the page or depth limit and crawl again."),
    "Deep page": (
        "Pages many clicks from the start page receive less link value and are crawled less often.",
        "Link to important deep pages from higher-level pages, menus, hub pages or related-content blocks."),
    "Only one internal link points here": (
        "A page with a single internal link receives little link value and is easily lost in a redesign.",
        "Add links to it from related pages."),
    "Broken internal links": (
        "Links to missing pages waste link value and frustrate visitors.",
        "Update each link to the right live URL, or remove it. The broken links list shows the page, the link and its anchor text."),
    "Broken external links": (
        "Links to dead pages on other sites make the page look neglected.",
        "Update or remove the links."),
    "Internal links to redirects": (
        "Each internal link to a redirect adds a hop for visitors and crawlers.",
        "Change the links to point straight at the final URL."),
    # ---- canonical targets
    "Canonical target could not be fetched": (
        "The URL in the canonical tag did not answer, so Google may ignore the canonical.",
        "Check that the canonical URL is right and loads."),
    "Canonical points to an error page": (
        "The canonical points to a page that returns an error, so Google will ignore it or may drop the page.",
        "Point the canonical at a live page that returns 200, usually the page itself."),
    "Canonical points to a redirect": (
        "A canonical should point at the final URL; pointing at a redirect is a weaker, mixed signal.",
        "Change the canonical to the URL the redirect ends at."),
    "Canonical points to a URL blocked by robots.txt": (
        "Google cannot crawl the canonical target to confirm it, so it may ignore the canonical.",
        "Allow crawling of the target, or point the canonical at a crawlable page."),
    "Canonical points to a noindex page": (
        "Contradictory signals: this page names the other as the main version, while that page asks not to be indexed. Both may drop out.",
        "Point the canonical at an indexable page, or remove the noindex from the target."),
    "Canonical chain": (
        "The canonical target points to yet another URL, a chain Google may not follow.",
        "Point every canonical straight at the final main version."),
    # ---- hreflang
    "Invalid hreflang code": (
        "Google ignores hreflang values it does not recognise, such as en-UK or en_US.",
        "Use an ISO 639-1 language code, optionally with an ISO 3166-1 region: en, en-GB, hi-IN, or x-default."),
    "Duplicate hreflang codes": (
        "The same language code points to different URLs, so Google cannot tell which one to show.",
        "Keep one URL per language and region code."),
    "No self-referencing hreflang": (
        "Each page in an hreflang set should also list itself; without that the set may be ignored.",
        "Add an hreflang tag for the page's own language pointing to its own URL."),
    "No x-default hreflang": (
        "x-default tells Google which page to show people whose language is not in the set.",
        "Add an x-default hreflang, usually pointing to the main or language-choice page."),
    "Hreflang return link missing": (
        "Hreflang works only when the pages point to each other. If an alternate does not point back, Google ignores the pair.",
        "Add matching hreflang tags on every page in the set, each listing all the others and itself."),
    "Hreflang alternate is broken or redirects": (
        "The alternate URL does not return 200, so Google cannot use it in the set.",
        "Point the hreflang at the live, final URL of the alternate page."),
    "Hreflang alternate is not indexable": (
        "The alternate page is noindex or canonicalised elsewhere, which conflicts with the hreflang set.",
        "Make the alternate page indexable and self-canonical, or remove it from the set."),
    # ---- keyword check
    "Keyword not in title": (
        "The title is the strongest on-page signal of what a page is about.",
        "Include the target keyword, or a close variant, naturally near the start of the title."),
    "Keyword only partly in title": (
        "All the words are there, but not as the phrase people search for.",
        "Use the keyword as a phrase where it reads naturally."),
    "Keyword not in H1": (
        "The H1 tells visitors and Google the main topic of the page.",
        "Include the keyword or a close variant in the H1."),
    "Keyword only partly in H1": (
        "All the words are there, but not as the phrase people search for.",
        "Use the keyword as a phrase in the H1 where it reads naturally."),
    "Keyword not in meta description": (
        "Google highlights the searched words in snippets, which helps the click-through rate.",
        "Mention the keyword naturally in the description."),
    "Keyword not in URL": (
        "A short URL containing the keyword is a small relevance signal and is clearer to searchers.",
        "Use the keyword in the slug of new pages. Change an existing URL only when the gain is clear, and add a 301 redirect."),
    "Keyword not in the first 100 words": (
        "Mentioning the topic early confirms to readers and Google what the page is about.",
        "Work the keyword into the opening paragraph."),
    "High keyword density": (
        "Repeating the exact keyword too often reads as unnatural and can look like keyword stuffing.",
        "Use variations, synonyms and related terms instead of repeating the exact phrase."),
    "Same keyword targeted by several URLs": (
        "Several pages competing for one keyword can split rankings (keyword cannibalisation).",
        "Choose one main page for the keyword, refocus the others on different keywords, or merge them."),
}
_DETAIL = re.compile(r"\s*\([^()]*\)\s*$")


def advice_for(issue: str):
    """(why, fix) for an issue name; works with names that carry a detail in brackets."""
    for key in (issue, _DETAIL.sub("", issue)):
        if key in ADVICE:
            return ADVICE[key]
    for key, value in ADVICE.items():
        if issue.startswith(key):
            return value
    return ("The audit flagged this on the URLs listed.", "Review the affected URLs and fix the cause.")


# --------------------------------------------------------------------------
# Word helpers
# --------------------------------------------------------------------------
def _text(value) -> str:
    if value is None or value is pd.NA or (isinstance(value, float) and pd.isna(value)):
        return ""
    return core.clean(str(value))


def _shade(cell, color: str):
    pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), color)
    pr.append(shd)


def _table(doc, header: list, rows: list, widths=None):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    for i, h in enumerate(header):
        cell = t.rows[0].cells[i]
        cell.text = ""
        run = cell.paragraphs[0].add_run(h)
        run.bold = True
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        _shade(cell, "1F4E78")
    for values in rows:
        cells = t.add_row().cells
        for i, v in enumerate(values):
            cells[i].text = _text(v)
    for row in t.rows:
        for cell in row.cells:
            for p in cell.paragraphs:
                for run in p.runs:
                    run.font.size = Pt(9)
    doc.add_paragraph()
    return t


def _link(paragraph, url: str, label: str):
    r_id = paragraph.part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), r_id)
    run = OxmlElement("w:r")
    props = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), LINK_COLOR)
    under = OxmlElement("w:u")
    under.set(qn("w:val"), "single")
    props.append(color)
    props.append(under)
    run.append(props)
    text = OxmlElement("w:t")
    text.text = label
    text.set(qn("xml:space"), "preserve")
    run.append(text)
    link.append(run)
    paragraph._p.append(link)


def url_label(url: str, site: str = "") -> str:
    """A short, readable name for a URL: its path (the homepage is called Homepage)."""
    try:
        p = urlsplit(url)
    except ValueError:
        return _text(url)
    path = (p.path or "/") + (f"?{p.query}" if p.query else "")
    if site and core.host_key(url) != core.host_key(site):
        return f"{p.netloc}{path}"
    return "Homepage" if path == "/" else path


def brand_defaults() -> dict:
    """The agency name and logo set in this file (and the logo file next to it)."""
    logo = b""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), LOGO_FILE)
    try:
        if os.path.isfile(path) and os.path.getsize(path) < 5_000_000:
            with open(path, "rb") as f:
                logo = f.read()
    except OSError:
        logo = b""
    return {"agency": AGENCY_NAME, "client": "", "logo": logo}


def apply_brand(doc, brand: dict = None):
    """Logo and agency name in the page header, 'Prepared for ... by ...' in the footer, of a new report."""
    brand = brand or {}
    agency, client, logo = (brand.get("agency") or "").strip(), (brand.get("client") or "").strip(), brand.get("logo")
    section = doc.sections[0]
    if logo or agency:
        p = section.header.paragraphs[0]
        if logo:
            try:
                p.add_run().add_picture(io.BytesIO(logo), height=Cm(1.0))
                if agency:
                    p.add_run("   ")
            except Exception:
                pass  # not an image Word can show (for example WebP or SVG): leave the logo out
        if agency:
            run = p.add_run(agency)
            run.bold = True
            run.font.size = Pt(10)
    if agency or client:
        text = ("Prepared for " + client if client else "Prepared") + (" by " + agency if agency else "")
        p = section.footer.paragraphs[0]
        run = p.add_run(text)
        run.font.size = Pt(8.5)
        run.font.color.rgb = RGBColor(0x59, 0x59, 0x59)


def brand_line(brand: dict = None) -> str:
    """'Prepared for Client by Agency. ' for the line under a report title, or an empty string."""
    brand = brand or {}
    agency, client = (brand.get("agency") or "").strip(), (brand.get("client") or "").strip()
    if not (agency or client):
        return ""
    return ("Prepared for " + client if client else "Prepared") + (" by " + agency if agency else "") + ". "


def _label_value(doc, label: str, value: str):
    p = doc.add_paragraph()
    p.add_run(f"{label}: ").bold = True
    p.add_run(value)
    return p


# --------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------
def build_report(tool: str, site: str, info: dict, df: pd.DataFrame, extra_sections: list = None,
                 brand: dict = None) -> bytes:
    """Word report for one run.

    df              the full results table (with the _issues column)
    extra_sections  optional [{"title", "intro", "header": [...], "rows": [[...], ...]}, ...]
    brand           optional {"agency", "client", "logo" (image bytes)} for the header and footer
    """
    numbers = core.headline_numbers(df)
    split = core.status_split(df)
    summary = core.issue_summary(df)
    total = max(len(df), 1)

    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(10.5)

    apply_brand(doc, brand)
    doc.add_heading("SEO audit report", level=0)
    sub = doc.add_paragraph()
    host = urlsplit(site).netloc if site and "://" in site else site
    sub.add_run(brand_line(brand) + f"Website: {host or 'not recorded'}. Checked with the {tool.lower()} on "
                f"{date.today().strftime('%d %B %Y')}.").italic = True

    # ---- summary
    doc.add_heading("Summary", level=1)
    doc.add_paragraph(
        f"This report covers {numbers['URLs checked']:,} URLs checked with the {tool.lower()}. "
        f"{numbers['Indexable']:,} can be indexed by Google and {numbers['Non-indexable']:,} cannot. "
        f"{numbers['With critical issues']:,} URLs have at least one critical issue and "
        f"{numbers['With warnings']:,} more have warnings. Critical issues stop pages from being found or indexed "
        "and should be fixed first; warnings weaken rankings or the search snippet; notices are smaller improvements."
    )
    rows = [[k, f"{v:,}"] for k, v in numbers.items()]
    answer = {"200 OK": "Answered 200 OK", "Redirect": "Redirected", "4xx": "Answered with a 4xx error",
              "5xx or failed": "Server error or no answer", "Other": "Other answer or not crawled"}
    rows += [[answer.get(k, k), f"{v:,}"] for k, v in split.items() if v]
    _table(doc, ["Measure", "URLs"], rows)

    # ---- priority issues
    priority = summary[summary["Severity"].isin([core.CRITICAL, core.WARNING])]
    doc.add_heading("Priority issues", level=1)
    if priority.empty:
        doc.add_paragraph("No critical issues or warnings were found.")
    else:
        doc.add_paragraph("Critical issues first, then warnings. Each one explains why it matters, how to fix it "
                          "and lists example URLs. The full list of affected URLs is in the Excel download.")
        _table(doc, ["Issue", "Severity", "URLs", "% of URLs"],
               [[r["Issue"], r["Severity"], f"{r['URLs']:,}", f"{r['% of URLs']}%"] for _, r in priority.iterrows()])
        for _, issue in priority.iterrows():
            sev, name, n = issue["Severity"], issue["Issue"], int(issue["URLs"])
            why, fix = advice_for(name)
            doc.add_heading(name, level=2)
            p = doc.add_paragraph()
            p.add_run(sev).bold = True
            p.add_run(f", {n:,} URL{'s' if n != 1 else ''} ({100 * n / total:.1f}% of the URLs checked)")
            _label_value(doc, "Why it matters", why)
            _label_value(doc, "How to fix", fix)
            hits = df[df["_issues"].map(lambda items, key=(sev, name): key in items)]["URL"].tolist()
            if hits:
                doc.add_paragraph().add_run("Example URLs").bold = True
                for url in hits[:EXAMPLE_URLS]:
                    _link(doc.add_paragraph(style="List Bullet"), url, url_label(url, site))
                if len(hits) > EXAMPLE_URLS:
                    doc.add_paragraph(f"and {len(hits) - EXAMPLE_URLS:,} more.")

    # ---- tool-specific sections (sitemap problems, broken links, crawl vs sitemap ...)
    for section in extra_sections or []:
        if not section.get("rows"):
            continue
        doc.add_heading(section["title"], level=1)
        if section.get("intro"):
            doc.add_paragraph(section["intro"])
        _table(doc, section["header"], section["rows"])

    # ---- notices
    notices = summary[summary["Severity"] == core.NOTICE]
    if not notices.empty:
        doc.add_heading("Smaller improvements (notices)", level=1)
        _table(doc, ["Notice", "URLs", "How to fix"],
               [[r["Issue"], f"{r['URLs']:,}", advice_for(r["Issue"])[1]] for _, r in notices.iterrows()])

    # ---- method
    doc.add_heading("How this audit was done", level=1)
    notes = [
        "Each URL was requested once, following redirects one step at a time, and its HTML was read as delivered by "
        "the server. JavaScript was not run, so content added by scripts is not included.",
        "Robots.txt rules were read the way Googlebot reads them.",
        "Indexable means the URL answered 200 directly, is not blocked by robots.txt, has no noindex, and its "
        "canonical tag does not point to another URL.",
    ]
    for k, v in info.items():
        notes.append(f"{k}: {v}")
    for note in notes:
        doc.add_paragraph(note, style="List Bullet")

    for p in doc.paragraphs:
        if p.style.name == "Title":
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
