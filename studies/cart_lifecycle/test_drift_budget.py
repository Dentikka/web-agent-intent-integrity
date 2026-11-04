"""Budget safety regression tests; no network, no model calls."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import time
import unittest

from bounded_api import Ledger,StopRun


class BudgetTests(unittest.TestCase):
    def ledger(self,cap=.1):
        root=Path(tempfile.mkdtemp(prefix='drift-budget-'))
        return root,Ledger(root,dict(budget_usd=cap,started_epoch=time.time(),hours=1))

    def test_concurrent_reservations_share_global_cap(self):
        root,ledger=self.ledger()
        def reserve(n):
            try:ledger.reserve(('main' if n%2 else 'meaning')+str(n),.011);return True
            except StopRun:return False
        with ThreadPoolExecutor(max_workers=8) as pool:allowed=list(pool.map(reserve,range(20)))
        self.assertEqual(sum(allowed),9)
        spent=ledger.db.execute('SELECT SUM(reserve) FROM calls').fetchone()[0]
        self.assertLessEqual(spent,.1);ledger.db.close()

    def test_unknown_usage_preserves_reservation_and_blocks_resume(self):
        root,ledger=self.ledger();ident=ledger.reserve('smoke',.02)
        with self.assertRaises(StopRun):ledger.settle(ident,{},dict(input_per_million=.3,output_per_million=1.2))
        self.assertEqual(ledger.db.execute('SELECT status FROM calls').fetchone()[0],'pending')
        ledger.db.close()
        with self.assertRaises(StopRun):Ledger(root,dict(budget_usd=.1,started_epoch=time.time(),hours=1))

    def test_nonfinite_reservation_rejected(self):
        root,ledger=self.ledger()
        for amount in (float('nan'),float('inf'),-.01):
            with self.assertRaises(ValueError):ledger.reserve('bad',amount)
        self.assertEqual(ledger.db.execute('SELECT COUNT(*) FROM calls').fetchone()[0],0)
        ledger.db.close()

    def test_invalid_reported_cost_retains_unknown_charge(self):
        for cost in (float('nan'), float('inf'), -1, 'not-a-number'):
            root,ledger=self.ledger();ident=ledger.reserve('bad-usage',.02)
            with self.assertRaises(StopRun):
                ledger.settle(ident,dict(prompt_tokens=10,completion_tokens=1,cost=cost),
                              dict(input_per_million=.3,output_per_million=1.2))
            self.assertEqual(ledger.db.execute('SELECT status FROM calls').fetchone()[0],'pending')
            ledger.db.close()


if __name__=='__main__':unittest.main()
