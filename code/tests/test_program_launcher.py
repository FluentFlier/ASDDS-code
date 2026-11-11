import datetime
import json
import os
import subprocess
import tempfile
import unittest


CODE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAUNCHER = os.path.join(CODE_DIR, "program_launcher.sh")


class ProgramLauncherTests(unittest.TestCase):
    def make_environment(self, directory, program_exit=0):
        program_dir = os.path.join(directory, "programs")
        log_dir = os.path.join(directory, "logs")
        os.makedirs(program_dir)
        os.makedirs(log_dir)

        selected_program = os.path.join(program_dir, "led_sleep_detect_clean.py")
        with open(selected_program, "w") as handle:
            handle.write("import sys\nsys.exit({})\n".format(program_exit))

        graph_marker = os.path.join(directory, "graph-ran.txt")
        graph_program = os.path.join(program_dir, "auto_graph.py")
        with open(graph_program, "w") as handle:
            handle.write(
                "import os, sys\n"
                "open(os.environ['GRAPH_MARKER'], 'w').write(sys.argv[1])\n"
            )

        run_date = datetime.datetime.now().strftime("%Y%m%d")
        log_path = os.path.join(log_dir, "sleep_log_{}.json".format(run_date))
        with open(log_path, "w") as handle:
            json.dump([], handle)

        environment = os.environ.copy()
        environment.update(
            {
                "ASDDS_PROG_DIR": program_dir,
                "ASDDS_LOG_DIR": log_dir,
                "GRAPH_MARKER": graph_marker,
            }
        )
        return environment, graph_marker, log_path

    def run_launcher(self, environment):
        return subprocess.run(
            ["bash", LAUNCHER],
            input="2\n",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=environment,
            check=False,
        )

    def test_successful_program_runs_automatic_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            environment, graph_marker, log_path = self.make_environment(directory)

            result = self.run_launcher(environment)

            self.assertEqual(0, result.returncode, result.stdout)
            self.assertIn("Creating end-of-run graph", result.stdout)
            self.assertIn("completed", result.stdout)
            with open(graph_marker) as handle:
                self.assertEqual(log_path, handle.read())

    def test_program_failure_is_preserved_after_graphing(self):
        with tempfile.TemporaryDirectory() as directory:
            environment, graph_marker, _log_path = self.make_environment(
                directory, program_exit=7
            )

            result = self.run_launcher(environment)

            self.assertEqual(7, result.returncode, result.stdout)
            self.assertIn("exited with code 7", result.stdout)
            self.assertTrue(os.path.isfile(graph_marker))


if __name__ == "__main__":
    unittest.main()
