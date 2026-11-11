import platform
import subprocess
import unittest
from pathlib import Path


CODE_DIR = Path(__file__).resolve().parents[1]
SETUP_JETSON = CODE_DIR / "setup_jetson.sh"
SETUP_MAC = CODE_DIR / "setup_mac.sh"


class SetupScriptTests(unittest.TestCase):
    def run_script(self, path, *arguments, input_text=None):
        return subprocess.run(
            ["bash", str(path), *arguments],
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    def test_setup_scripts_have_valid_bash_syntax(self):
        result = subprocess.run(
            ["bash", "-n", str(SETUP_JETSON), str(SETUP_MAC)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout)

    def test_jetson_setup_help_has_no_side_effects(self):
        result = self.run_script(SETUP_JETSON, "--help")
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertIn("Usage: bash setup_jetson.sh", result.stdout)

    def test_jetson_setup_rejects_unknown_options(self):
        result = self.run_script(SETUP_JETSON, "--not-a-real-option")
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("Unknown option", result.stdout)

    def test_mac_setup_stops_before_changes_when_prerequisites_are_missing(self):
        result = self.run_script(SETUP_MAC, input_text="\n\n")
        self.assertEqual(1, result.returncode, result.stdout)
        if platform.system() == "Darwin":
            self.assertIn("Username and host are required", result.stdout)
        else:
            self.assertIn("intended to run from macOS", result.stdout)


if __name__ == "__main__":
    unittest.main()
