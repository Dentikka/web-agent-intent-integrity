"""Keep study imports isolated from the existing root benchmark modules."""
from pathlib import Path
import subprocess
import sys
import unittest


class OperationBindingTests(unittest.TestCase):
    def test_isolated_binding_suite(self):
        folder = Path(__file__).parent / 'studies/operation_binding'
        result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', str(folder),
                                 '-p', 'test_*.py', '-v'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
