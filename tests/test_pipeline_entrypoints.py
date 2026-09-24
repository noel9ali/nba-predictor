"""DP-F21: the DP-F2 UTF-8 fix only protected daily_workflow.py's own
invocation path (which calls force_utf8_stdio() itself, plus PYTHONIOENCODING
injected into run_pipeline.bat/run_predict.bat's child env). None of
src/collect.py, src/elo.py, src/features.py, src/model.py, src/odds.py,
src/predict.py, src/track.py, src/backtest_last_year.py imported
console.force_utf8_stdio() themselves, so a bare `python src\\track.py` (or
any other invocation path) could still crash with UnicodeEncodeError.

Every one of those entry points must now call force_utf8_stdio() as the
FIRST statement of its own `if __name__ == '__main__':` block -- not at
import time, since importing a module must not reconfigure the importer's
own stdio.
"""
import ast
import os
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(REPO_ROOT, "src")

ENTRYPOINTS = [
    "collect.py",
    "elo.py",
    "features.py",
    "model.py",
    "odds.py",
    "predict.py",
    "track.py",
    "backtest_last_year.py",
]


def _main_node(tree):
    """Return the module's `if __name__ == '__main__':` ast.If node, or None."""
    for node in tree.body:
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
        ):
            return node
    return None


def _is_force_utf8_stdio_call(stmt):
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Call)
        and isinstance(stmt.value.func, ast.Name)
        and stmt.value.func.id == "force_utf8_stdio"
    )


def _parse(filename):
    path = os.path.join(SRC_DIR, filename)
    with open(path, encoding="utf-8") as f:
        return ast.parse(f.read(), filename=path)


class EntrypointCallsForceUtf8StdioFirstTests(unittest.TestCase):
    def test_main_block_calls_force_utf8_stdio_as_its_first_statement(self):
        for filename in ENTRYPOINTS:
            with self.subTest(filename=filename):
                main_node = _main_node(_parse(filename))
                self.assertIsNotNone(main_node, f"{filename} has no `if __name__ == '__main__':` block")
                self.assertTrue(main_node.body, f"{filename}'s __main__ block is empty")
                self.assertTrue(
                    _is_force_utf8_stdio_call(main_node.body[0]),
                    f"{filename}'s __main__ block must call force_utf8_stdio() as its first statement, "
                    f"got: {ast.dump(main_node.body[0])}",
                )

    def test_force_utf8_stdio_is_not_called_at_module_import_time(self):
        # A module-level call (outside __main__) would reconfigure the
        # importer's own stdio just by importing the module -- forbidden.
        for filename in ENTRYPOINTS:
            with self.subTest(filename=filename):
                tree = _parse(filename)
                main_node = _main_node(tree)
                for node in tree.body:
                    if node is main_node:
                        continue
                    self.assertFalse(
                        _is_force_utf8_stdio_call(node),
                        f"{filename} must not call force_utf8_stdio() at module import time",
                    )


class ForceUtf8StdioSubprocessTests(unittest.TestCase):
    """A real subprocess proof that force_utf8_stdio() survives a non-UTF-8
    console encoding with file-redirected stdout. Uses a tiny scratch
    script -- NEVER a real pipeline module (network + live DB)."""

    def test_a_scratch_script_using_force_utf8_stdio_survives_cp1252_with_redirected_stdout(self):
        script = (
            "import sys; sys.path.insert(0, %r); "
            "from console import force_utf8_stdio; force_utf8_stdio(); "
            "print(u'✓ →')" % SRC_DIR
        )
        child_env = os.environ.copy()
        child_env["PYTHONIOENCODING"] = "cp1252"

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "stdout.txt")
            with open(out_path, "w") as out_file:
                result = subprocess.run(
                    [sys.executable, "-c", script],
                    stdout=out_file,
                    stderr=subprocess.STDOUT,
                    env=child_env,
                )

            self.assertEqual(result.returncode, 0)
            with open(out_path, encoding="utf-8") as f:
                self.assertIn("✓", f.read())


if __name__ == "__main__":
    unittest.main()
