"""Static checks on the new dashboard's files (public/): the strict CSP holds (no inline
script, style or on* handlers; everything same-origin), data can only reach the page as text
(no HTML-string sinks), the accessibility basics from DESIGN sec1 are in the CSS, fonts are
self-hosted with their licence, and nothing secret is shipped. What only a browser can show
(focus trap, crosshair keys, reduced motion, 375 px, fired payloads) is covered by
scripts/browser_check.mjs and scripts/xss_harness.py; see design/BUILD_PROGRESS.md.
"""
import glob
import os
import re
import unittest
from html.parser import HTMLParser

PUBLIC = os.path.join(os.path.dirname(__file__), "..", "public")
INDEX = os.path.join(PUBLIC, "index.html")
JS_DIR = os.path.join(PUBLIC, "static", "js")
CSS = os.path.join(PUBLIC, "static", "dashboard.css")
FONTS = os.path.join(PUBLIC, "static", "fonts")


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def js_files():
    return sorted(glob.glob(os.path.join(JS_DIR, "*.js")))


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class IndexHtmlTests(unittest.TestCase):
    def setUp(self):
        self.html = read(INDEX)
        parser = _Tags()
        parser.feed(self.html)
        self.tags = parser.tags

    def test_no_inline_script_code(self):
        for attrs, body in re.findall(r"<script([^>]*)>([\s\S]*?)</script>", self.html):
            self.assertIn("src=", attrs)
            self.assertEqual(body.strip(), "")

    def test_no_style_attributes_style_blocks_or_inline_handlers(self):
        self.assertNotIn("<style", self.html.lower())
        for tag, attrs in self.tags:
            for name in attrs:
                self.assertNotEqual(name, "style", f"<{tag} style=...>")
                self.assertFalse(name.startswith("on"), f"<{tag} {name}=...>")

    def test_every_resource_is_same_origin(self):
        for tag, attrs in self.tags:
            for name in ("src", "href"):
                value = attrs.get(name)
                if value is None:
                    continue
                self.assertFalse(re.match(r"^(https?:)?//", value), f"<{tag} {name}={value}>")

    def test_module_entry_point_and_live_regions(self):
        self.assertIn('<script type="module" src="/static/js/main.js"></script>', self.html)
        self.assertRegex(self.html, r'id="toasts"[^>]*role="status"[^>]*aria-live="polite"')
        self.assertRegex(self.html, r'id="drawer"[^>]*role="dialog"[^>]*aria-modal="true"')
        self.assertIn('<html lang="en">', self.html)
        self.assertIn('name="viewport"', self.html)


class JavaScriptSinkTests(unittest.TestCase):
    SINKS = [
        r"\.innerHTML\s*=", r"\.outerHTML\s*=", r"insertAdjacentHTML", r"document\.write",
        r"\beval\s*\(", r"new\s+Function\s*\(", r"setAttribute\(\s*[\"']style[\"']",
        r"setAttribute\(\s*[\"']on", r"\.on[a-z]+\s*=\s*(?!null)", r"createContextualFragment",
        r"DOMParser", r"setTimeout\(\s*[\"']", r"setInterval\(\s*[\"']",
    ]

    def test_no_html_string_sinks(self):
        for path in js_files():
            source = read(path)
            for pattern in self.SINKS:
                with self.subTest(file=os.path.basename(path), sink=pattern):
                    self.assertIsNone(re.search(pattern, source))

    def test_the_dom_helper_refuses_handlers_styles_and_unsafe_urls(self):
        dom = read(os.path.join(JS_DIR, "dom.js"))
        self.assertIn("FORBIDDEN_ATTR = /^(on|style$|srcdoc$|formaction$)/i", dom)
        self.assertIn("SAFE_URL", dom)
        self.assertIn("createTextNode", dom)

    def test_one_keydown_listener_on_document(self):
        hits = []
        for path in js_files():
            hits += [(os.path.basename(path), m) for m in re.findall(r'(\w+)\.addEventListener\(\s*"keydown"', read(path))]
        self.assertEqual(hits, [("keys.js", "document")])

    def test_no_external_origins_or_hotlinked_logos(self):
        for path in js_files() + [CSS, INDEX]:
            source = read(path)
            with self.subTest(file=os.path.basename(path)):
                self.assertNotIn("cdn.nba.com", source)
                self.assertNotIn("fonts.googleapis", source)
                self.assertNotIn("fonts.gstatic", source)
                self.assertIsNone(re.search(r"(fetch|import)\(\s*[\"'`]https?:", source))

    def test_run_now_is_gated_by_the_api(self):
        topbar = read(os.path.join(JS_DIR, "topbar.js"))
        self.assertIn("ws && ws.controls_allowed", topbar)
        self.assertIn('"X-Requested-With": "run-now"', read(os.path.join(JS_DIR, "api.js")))


class CssTests(unittest.TestCase):
    def setUp(self):
        self.css = read(CSS)

    def block(self, selector):
        match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", self.css)
        self.assertIsNotNone(match, selector)
        return match.group(1)

    def test_design_tokens(self):
        for token in ("--bg: #0a1630", "--panel: #102244", "--deep: #0d1d3b", "--divider: #1d3461",
                      "--edge: #3a5185", "--accent: #ffc72c", "--muted: #b7c4dd", "--win: #3ee08f",
                      "--loss: #ff8a95", "--live: #d62839", "--dim: #7f8fb0"):
            self.assertIn(token, self.css)
        self.assertNotRegex(self.css, r"border-radius:\s*(?!50%)[1-9]")  # square edges (circles only for logos/dots)

    def test_touch_targets_are_44px(self):
        for selector in (".icon-btn", ".info-btn", ".btn", ".seg button", ".pill", ".details-btn",
                         ".tabs a", ".brand", ".toast-close", ".rail-day", ".link-btn"):
            with self.subTest(selector=selector):
                block = self.block(selector)
                sizes = re.findall(r"(?:min-height|height):\s*(\d+)px", block)
                self.assertTrue(sizes and max(int(s) for s in sizes) >= 44, f"{selector}: {sizes}")

    def test_reduced_motion_drops_flash_and_crossfade(self):
        match = re.search(r"@media \(prefers-reduced-motion: reduce\) \{([\s\S]*?)\n\}", self.css)
        self.assertIsNotNone(match)
        block = match.group(1)
        self.assertIn(".fade-in", block)
        self.assertIn("flash-live", block)
        self.assertIn("animation: none", block)

    def test_single_column_under_900px(self):
        self.assertIn("@media (max-width: 900px)", self.css)
        self.assertRegex(self.css, r"\.cards \{ grid-template-columns: minmax\(0, 1fr\); \}")

    def test_fonts_are_self_hosted(self):
        for url in re.findall(r"url\(\"([^\"]+)\"\)", self.css):
            self.assertTrue(url.startswith("fonts/"), url)
            self.assertTrue(os.path.isfile(os.path.join(PUBLIC, "static", url)), url)


class FontAndSecretTests(unittest.TestCase):
    def test_barlow_woff2_files_ship_with_the_ofl(self):
        for name in ("barlow-latin-400-normal", "barlow-latin-500-normal", "barlow-latin-600-normal",
                     "barlow-condensed-latin-600-normal", "barlow-condensed-latin-700-normal",
                     "barlow-condensed-latin-800-normal"):
            path = os.path.join(FONTS, f"{name}.woff2")
            with self.subTest(font=name):
                with open(path, "rb") as fh:
                    self.assertEqual(fh.read(4), b"wOF2")
        self.assertIn("SIL Open Font License", read(os.path.join(FONTS, "OFL.txt")))
        self.assertIn("SIL Open Font License", read(os.path.join(FONTS, "OFL-BarlowCondensed.txt")))

    def test_nothing_secret_is_shipped_in_public(self):
        pattern = re.compile(r"SUPABASE_SECRET_KEY|sb_secret_|sb_publishable_|service_role|eyJhbGciOi")
        for path in glob.glob(os.path.join(PUBLIC, "**", "*"), recursive=True):
            if os.path.isdir(path) or path.endswith(".woff2"):
                continue
            with self.subTest(file=os.path.relpath(path, PUBLIC)):
                self.assertIsNone(pattern.search(read(path)))


if __name__ == "__main__":
    unittest.main()
