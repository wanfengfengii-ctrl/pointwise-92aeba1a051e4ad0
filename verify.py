from pathlib import Path
import unittest


def main():
    tests = Path(__file__).resolve().parent / 'tests'
    suite = unittest.defaultTestLoader.discover(str(tests))
    if suite.countTestCases() == 0:
        raise SystemExit('no regression tests discovered')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
