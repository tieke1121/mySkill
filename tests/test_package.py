"""Check that the skill remains self-contained after directory installation."""

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "stock-research"


class PackageTests(unittest.TestCase):
    def test_relative_markdown_links_resolve(self):
        for path in [ROOT / "README.md", *SKILL.rglob("*.md")]:
            for link in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
                if link.startswith(("https://", "http://", "#")):
                    continue
                with self.subTest(path=str(path.relative_to(ROOT)), link=link):
                    self.assertTrue((path.parent / link.split("#")[0]).is_file())

    def test_installed_bundle_runs_outside_repo(self):
        with tempfile.TemporaryDirectory(prefix="skill install ") as folder:
            destination = Path(folder) / "skills" / "stock-research"
            shutil.copytree(SKILL, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            script = destination / "scripts/dcf.py"
            fixture = destination / "assets/dcf-example.json"
            run = subprocess.run([sys.executable, str(script), str(fixture)], cwd=folder, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertGreater(json.loads(run.stdout)["base"]["value_per_quote_unit"], 0)


if __name__ == "__main__":
    unittest.main()
