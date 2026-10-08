import importlib.util
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch
import unittest

spec = importlib.util.spec_from_file_location('keyword_repair', Path(__file__).with_name('repair_keyword_index.py'))
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)

DEFINITION = 'CREATE INDEX embeddings_search_idx ON public.embeddings USING bm25 (id, content)'


class KeywordRepairTests(unittest.TestCase):
    def test_healthy_probe_never_changes_database(self):
        values = [CompletedProcess([], 0, DEFINITION, ''), CompletedProcess([], 0, 'SET\n3\n', '')]
        with patch.object(repair, 'sql', side_effect=values) as query, patch('sys.argv', ['repair']), \
                patch.object(repair.subprocess, 'run') as process:
            repair.main()
            self.assertEqual(query.call_count, 2)
            process.assert_not_called()

    def test_known_failure_requires_explicit_apply(self):
        values = [CompletedProcess([], 0, DEFINITION, ''),
                  CompletedProcess([], 1, '', 'ERROR: assertion failed: item_pointer_is_valid(ctid)')]
        with patch.object(repair, 'sql', side_effect=values), patch('sys.argv', ['repair']), \
                patch.object(repair.subprocess, 'run') as process:
            with self.assertRaises(SystemExit):
                repair.main()
            process.assert_not_called()

    def test_other_failure_cannot_trigger_reindex(self):
        values = [CompletedProcess([], 0, DEFINITION, ''), CompletedProcess([], 1, '', 'permission denied')]
        with patch.object(repair, 'sql', side_effect=values), patch('sys.argv', ['repair', '--apply']), \
                patch.object(repair.subprocess, 'run') as process:
            with self.assertRaisesRegex(RuntimeError, 'Different database error'):
                repair.main()
            process.assert_not_called()

    def test_repair_is_transactional_bounded_and_index_only(self):
        self.assertIn('BEGIN;', repair.REPAIR)
        self.assertIn("lock_timeout='5s'", repair.REPAIR)
        self.assertIn("maintenance_work_mem='64MB'", repair.REPAIR)
        self.assertIn('REINDEX INDEX public.embeddings_search_idx;', repair.REPAIR)
        self.assertIn('before_hash IS DISTINCT FROM after_hash', repair.REPAIR)
        self.assertNotIn('DROP ', repair.REPAIR)
        self.assertNotIn('DELETE ', repair.REPAIR)


if __name__ == '__main__':
    unittest.main()
