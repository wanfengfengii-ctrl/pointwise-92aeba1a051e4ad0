import tempfile
import unittest
from pathlib import Path

from intake_examples import acceptance_scenario


def main():
    tests = Path(__file__).resolve().parent / 'tests'
    suite = unittest.defaultTestLoader.discover(str(tests))
    if suite.countTestCases() == 0:
        raise SystemExit('no regression tests discovered')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        return 1
    # Acceptance business checks travel with the regressions in the same entry.
    with tempfile.TemporaryDirectory(prefix='chengchuan-verify-') as directory:
        scenario = acceptance_scenario(Path(directory))
        if len(scenario['accepted']) != 3 or scenario['local_report']['intervals'] != [[0, 0, 1]]:
            raise SystemExit('acceptance scenario did not produce the expected receipts')
        if set(scenario['reverified'].values()) - {scenario['accepted']['A/morning']['report_id'],
                                                   scenario['accepted']['A/followup']['report_id']}:
            raise SystemExit('re-exported package identities disagree with accepted receipts')
    print('acceptance verification passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
