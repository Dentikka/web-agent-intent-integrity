import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from api_client import Ledger,StopRun


class BudgetTests(unittest.TestCase):
    def test_parallel_reservations_share_one_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Ledger(Path(tmp),dict(budget_usd=.1,started_epoch=time.time(),hours=1))
            def reserve(i):
                try:return ledger.reserve(str(i),.03)
                except StopRun:return None
            with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(reserve,range(20)))
            self.assertEqual(sum(r is not None for r in results),3)
            self.assertAlmostEqual(ledger.db.execute('SELECT SUM(reserve) FROM calls').fetchone()[0],.09)
            ledger.db.close()

    def test_budget_pending_and_actual_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cfg=dict(budget_usd=.1,started_epoch=time.time(),hours=1)
            ledger=Ledger(root,cfg)
            call=ledger.reserve('episode',.08)
            with self.assertRaises(StopRun):ledger.reserve('other',.03)
            ledger.settle(call,{'prompt_tokens':1000,'completion_tokens':100},dict(input_per_million=5,output_per_million=25))
            self.assertAlmostEqual(ledger.db.execute('SELECT actual FROM calls').fetchone()[0],.0075)
            ledger.reserve('pending',.01);ledger.db.close()
            with self.assertRaises(StopRun):Ledger(root,cfg)

    def test_deadline_and_missing_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            ledger=Ledger(root,dict(budget_usd=1,started_epoch=time.time()-1000,hours=.1))
            with self.assertRaises(StopRun):ledger.reserve('episode',.01)
            ledger.db.close()
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Ledger(Path(tmp),dict(budget_usd=1,started_epoch=time.time(),hours=1))
            call=ledger.reserve('episode',.1)
            with self.assertRaises(StopRun):ledger.settle(call,{},dict(input_per_million=5,output_per_million=25))
            ledger.db.close()


if __name__=='__main__':unittest.main()
