"""Static checks on the Hardwood Tickets pages (public/index.html, public/model.html and
public/static): the strict CSP holds (no inline script, style, style="" or on* handlers; everything
same-origin), API text can only reach the DOM escaped, fonts and logos are self-hosted with their
licences, the design tokens and reduced-motion rules are in the CSS, and nothing secret is shipped.
What only a browser can show (motion, focus trap, stamps, replay) is covered by tests/e2e/validate.mjs
and scripts/xss_harness.py; see design/hardwood/RUNBOOK.md.
"""
import glob
import os
import re
import unittest
from html.parser import HTMLParser

PUBLIC = os.path.join(os.path.dirname(__file__), "..", "public")
STATIC = os.path.join(PUBLIC, "static")
PAGES = {"index.html": "tonight.js", "model.html": "model.js"}
CSS_DIR = os.path.join(STATIC, "css")
FONTS = os.path.join(STATIC, "fonts")
# The legacy Fan Board (/legacy, templates/index.html) still uses these two files; they are not part
# of the new pages and keep their own rules.
LEGACY = {os.path.normpath(os.path.join(STATIC, "app.js")), os.path.normpath(os.path.join(STATIC, "style.css"))}


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def code(path):
    """Source with comments removed, so prose that mentions a banned pattern doesn't trip a check."""
    source = re.sub(r"/\*[\s\S]*?\*/", "", read(path))
    return re.sub(r"(?m)^\s*//.*$|(?<=[;{}),])\s*//.*$", "", source)


def js_files():
    return sorted(p for p in glob.glob(os.path.join(STATIC, "js", "**", "*.js"), recursive=True))


def css_files():
    return sorted(glob.glob(os.path.join(CSS_DIR, "*.css")))


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class PageHtmlTests(unittest.TestCase):
    def pages(self):
        for name, entry in PAGES.items():
            html = read(os.path.join(PUBLIC, name))
            parser = _Tags()
            parser.feed(html)
            yield name, entry, html, parser.tags

    def test_no_inline_script_code(self):
        for name, _, html, _ in self.pages():
            for attrs, body in re.findall(r"<script([^>]*)>([\s\S]*?)</script>", html):
                with self.subTest(page=name):
                    self.assertIn("src=", attrs)
                    self.assertEqual(body.strip(), "")

    def test_no_style_attributes_style_blocks_or_inline_handlers(self):
        for name, _, html, tags in self.pages():
            self.assertNotIn("<style", html.lower(), name)
            for tag, attrs in tags:
                for attr in attrs:
                    with self.subTest(page=name, tag=tag, attr=attr):
                        self.assertNotEqual(attr, "style")
                        self.assertFalse(attr.startswith("on"))

    def test_every_resource_is_same_origin(self):
        for name, _, html, tags in self.pages():
            self.assertNotIn("googleapis", html)
            self.assertNotIn("gstatic", html)
            for tag, attrs in tags:
                for attr in ("src", "href"):
                    value = attrs.get(attr)
                    if value is not None:
                        with self.subTest(page=name, value=value):
                            self.assertFalse(re.match(r"^(https?:)?//", value))

    def test_entry_points_gate_and_landmarks(self):
        for name, entry, html, _ in self.pages():
            with self.subTest(page=name):
                self.assertIn(f'<script type="module" src="/static/js/{entry}"></script>', html)
                self.assertIn('<script src="/static/js/gate.js"></script>', html)
                self.assertIn('<html lang="en">', html)
                self.assertIn('name="viewport"', html)
                self.assertEqual(html.count("<h1"), 1)
                self.assertIn('<nav class="tabs" aria-label="Pages">', html)
                self.assertIn('<div class="ambient" aria-hidden="true">', html)

    def test_tonight_live_region_and_dialog(self):
        html = read(os.path.join(PUBLIC, "index.html"))
        self.assertRegex(html, r'class="toasts"[^>]*role="status"[^>]*aria-live="polite"')
        self.assertRegex(html, r'role="dialog"[^>]*aria-modal="true"[^>]*aria-labelledby="d-title"')
        for testid in ("date-eyebrow", "counts", "hero", "tape", "chart", "filters", "sorts", "grid",
                       "drawer", "season-board", "bankroll", "wl", "calib", "mfacts"):
            self.assertIn(f'data-testid="{testid}"', html)


class JavaScriptTests(unittest.TestCase):
    SINKS = [r"\.outerHTML\s*=", r"document\.write", r"\beval\s*\(", r"new\s+Function\s*\(",
             r"setAttribute\(\s*[\"']style[\"']", r"setAttribute\(\s*[\"']on", r"createContextualFragment",
             r"DOMParser", r"setTimeout\(\s*[\"']", r"setInterval\(\s*[\"']"]

    def test_no_dangerous_sinks(self):
        for path in js_files():
            source = read(path)
            for pattern in self.SINKS:
                with self.subTest(file=os.path.relpath(path, STATIC), sink=pattern):
                    self.assertIsNone(re.search(pattern, source))

    def test_html_strings_are_built_with_esc(self):
        # Any module that writes HTML strings must import the escaper; API text goes through esc()
        # or textContent (scripts/xss_harness.py checks the result in a browser).
        for path in js_files():
            source = read(path)
            if re.search(r"\.innerHTML\s*=|insertAdjacentHTML", source):
                with self.subTest(file=os.path.relpath(path, STATIC)):
                    self.assertRegex(source, r"import\s*\{[^}]*\besc\b[^}]*\}\s*from\s*'\.\.?/(\.\./)?format\.js'")

    def test_no_style_attributes_in_html_strings(self):
        for path in js_files():
            with self.subTest(file=os.path.relpath(path, STATIC)):
                self.assertIsNone(re.search(r"style\s*=\s*\\?[\"']", code(path)))

    def test_no_prototype_controls_or_theme_code(self):
        for path in js_files():
            source = read(path)
            with self.subTest(file=os.path.relpath(path, STATIC)):
                for banned in ("data-testid=advance", "protoBar", "applyTheme", "cycleTheme", "nba-theme", "window.NBA"):
                    self.assertNotIn(banned, source)

    def test_no_external_origins_or_hotlinked_logos(self):
        for path in js_files() + css_files():
            source = read(path)
            with self.subTest(file=os.path.relpath(path, STATIC)):
                self.assertNotIn("cdn.nba.com", source)
                self.assertNotIn("fonts.googleapis", source)
                self.assertIsNone(re.search(r"(fetch|import)\(\s*[\"'`]https?:", source))


class CssTests(unittest.TestCase):
    def setUp(self):
        self.css = {os.path.basename(p): read(p) for p in css_files()}
        self.all = "\n".join(self.css.values())

    def test_design_tokens(self):
        tokens = self.css["tokens.css"]
        for token in ("--floor:#2b1d11", "--panel:#1d140c", "--ink:#f7ecdb", "--ink-2:#c9ad8a", "--paint:#4cc2b5",
                      "--ball:#ff8a3d", "--stock:#f1e4cc", "--t-ink:#24170b", "color-scheme:dark"):
            self.assertIn(token, tokens)
        self.assertNotIn("data-theme", self.all)

    def test_square_shapes_only(self):
        for value in re.findall(r"border-radius:\s*([^;}]+)", self.all):
            self.assertEqual(value.strip(), "50%")

    def test_touch_targets(self):
        for selector, minimum in ((".tabs a", 44), (".btn", 44), (".tg button", 44), (".more-link", 44), (".seasonbar button", 40)):
            match = re.search(re.escape(selector) + r"\{([^}]*)\}", self.all)
            with self.subTest(selector=selector):
                self.assertIsNotNone(match)
                sizes = re.findall(r"min-height:(\d+)px", match.group(1))
                self.assertTrue(sizes and int(sizes[0]) >= minimum, sizes)

    def test_reduced_motion_everywhere(self):
        self.assertRegex(self.css["components.css"], r"@media \(prefers-reduced-motion:reduce\)\{\s*\*,\*::before,\*::after\{animation:none!important;transition:none!important\}")
        self.assertIn("prefers-reduced-motion:reduce", self.css["ambient.css"])

    def test_pre_states_are_gated_on_html_js(self):
        for name, css in self.css.items():
            css = re.sub(r"/\*[\s\S]*?\*/", "", css)
            for selector in re.findall(r"([^{}]*\.pre(?![\w-])[^{}]*)\{", css):
                for part in selector.split(","):
                    if not re.search(r"\.pre(?![\w-])", part):
                        continue
                    with self.subTest(file=name, selector=part.strip()):
                        self.assertTrue(part.strip().startswith(".js "), part)

    def test_fonts_are_self_hosted(self):
        for url in re.findall(r"url\(\"(/static/fonts/[^\"]+)\"\)", self.css["fonts.css"]):
            self.assertTrue(os.path.isfile(os.path.join(PUBLIC, url.lstrip("/"))), url)


class FontLogoAndSecretTests(unittest.TestCase):
    def test_woff2_files_ship_with_their_licences(self):
        for name in ("graduate-latin-400-normal", "hanken-grotesk-latin-wght-normal", "ibm-plex-mono-latin-400-normal",
                     "ibm-plex-mono-latin-500-normal", "ibm-plex-mono-latin-600-normal"):
            with self.subTest(font=name):
                with open(os.path.join(FONTS, f"{name}.woff2"), "rb") as fh:
                    self.assertEqual(fh.read(4), b"wOF2")
        for lic in ("OFL-Graduate.txt", "OFL-Hanken-Grotesk.txt", "OFL-IBM-Plex-Mono.txt"):
            self.assertIn("Open Font License", read(os.path.join(FONTS, lic)))

    def test_thirty_team_logos(self):
        logos = glob.glob(os.path.join(STATIC, "logos", "*.svg"))
        self.assertEqual(len(logos), 30)
        for path in logos:
            with self.subTest(logo=os.path.basename(path)):
                self.assertRegex(os.path.basename(path), r"^[A-Z]{3}\.svg$")
                self.assertNotIn("<script", read(path).lower())

    def test_nothing_secret_is_shipped_in_public(self):
        pattern = re.compile(r"SUPABASE_SECRET_KEY|sb_secret_|sb_publishable_|service_role|eyJhbGciOi")
        for path in glob.glob(os.path.join(PUBLIC, "**", "*"), recursive=True):
            if os.path.isdir(path) or path.endswith(".woff2"):
                continue
            with self.subTest(file=os.path.relpath(path, PUBLIC)):
                self.assertIsNone(pattern.search(read(path)))


if __name__ == "__main__":
    unittest.main()
