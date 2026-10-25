import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


class CliIntegrationTests(unittest.TestCase):
    def run_cli(self, command, reports, *extra):
        env = {"PYTHONPATH": str(SRC)}
        return subprocess.run(
            [sys.executable, "-m", "sn119_demo.cli", command, "--reports-dir", str(reports), *extra],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )

    def test_pipeline_writes_reports_and_disclaimer(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports = Path(tmp) / "reports"
            for command in ("seed", "generate", "validate", "evaluate", "simulate", "report"):
                self.run_cli(command, reports)
            self.assertTrue((reports / "report.json").exists())
            report = json.loads((reports / "report.json").read_text())
            self.assertTrue(report["offline"])
            self.assertIn("not real TAO earnings", report["disclaimer"])
            self.assertEqual(json.loads((reports / "validate.json").read_text())["quality_gate"], "pass")

    def test_quality_gate_fails_for_empty_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports = Path(tmp) / "reports"
            self.run_cli("seed", reports)
            self.run_cli("generate", reports, "--count", "0")
            self.run_cli("validate", reports)
            result = json.loads((reports / "validate.json").read_text())
            self.assertEqual(result["quality_gate"], "fail")
            self.assertFalse(result["valid"])


if __name__ == "__main__":
    unittest.main()

