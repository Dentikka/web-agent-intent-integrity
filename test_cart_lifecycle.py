"""Run isolated study tests without shadowing the main programme's modules."""
from pathlib import Path
import subprocess
import sys
import unittest


class CartLifecycleTests(unittest.TestCase):
    def test_isolated_replication_suite(self):
        folder = Path(__file__).parent / 'studies/cart_lifecycle'
        result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', str(folder),
                                 '-p', 'test_*.py', '-v'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
