"""Explicit, backed-up repair for the known ParadeDB invalid-ctid failure.

Run on the deployment host. Default is read-only; --apply permits one index
rebuild only when the known assertion is reproduced. No tables are dropped,
documents deleted, vectors recomputed, or database services restarted.
"""
import argparse
import os
from pathlib import Path
import subprocess
from datetime import datetime

CONTAINER = 'edu-weknora-postgres-1'
PSQL = ['docker', 'exec', '-i', CONTAINER, 'psql', '-X', '-U', 'weknora',
        '-d', 'weknora', '-v', 'ON_ERROR_STOP=1', '-At']
PROBE = """SET statement_timeout='20s';
SELECT count(*) FROM (
 SELECT id, paradedb.score(id) FROM public.embeddings
 WHERE content ||| '逼单' AND (is_enabled IS NULL OR is_enabled=true)
 ORDER BY paradedb.score(id) DESC LIMIT 5
) matches;
"""
REPAIR = """BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='90s';
SET LOCAL maintenance_work_mem='64MB';
LOCK TABLE public.embeddings IN SHARE MODE;
CREATE TEMP TABLE repair_fingerprint AS
 SELECT count(*) AS rows, md5(string_agg(md5(row_to_json(e)::text),' ' ORDER BY id)) AS digest
 FROM public.embeddings e;
REINDEX INDEX public.embeddings_search_idx;
DO $$ DECLARE before_rows bigint; after_rows bigint; before_hash text; after_hash text;
BEGIN
 SELECT rows,digest INTO before_rows,before_hash FROM repair_fingerprint;
 SELECT count(*),md5(string_agg(md5(row_to_json(e)::text),' ' ORDER BY id))
 INTO after_rows,after_hash FROM public.embeddings e;
 IF before_rows IS DISTINCT FROM after_rows OR before_hash IS DISTINCT FROM after_hash THEN
   RAISE EXCEPTION 'Embedding data changed during repair';
 END IF;
END $$;
COMMIT;
"""


def sql(text):
    return subprocess.run(PSQL, input=text, text=True, encoding='utf-8',
                          capture_output=True, timeout=110)


def require_success(result):
    if result.returncode:
        raise RuntimeError(result.stderr[-1500:])
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    definition = require_success(sql("SELECT pg_get_indexdef('public.embeddings_search_idx'::regclass);"))
    if 'ON public.embeddings USING bm25 ' not in definition:
        raise RuntimeError('Unexpected index definition; refusing repair')
    probe = sql(PROBE)
    if not probe.returncode:
        print('Keyword index probe passed; no changes made.')
        return
    if 'item_pointer_is_valid(ctid)' not in probe.stderr:
        raise RuntimeError('Different database error; refusing automatic repair: ' + probe.stderr[-1000:])
    if not args.apply:
        raise SystemExit('Known invalid-ctid failure reproduced. Re-run with --apply to back up and repair.')
    reports = Path(__file__).resolve().parent / 'reports'
    reports.mkdir(exist_ok=True)
    backup = reports / ('database-before-keyword-repair-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.dump')
    # Exclusive creation and owner-only permissions: backups contain private data.
    descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as output:
        result = subprocess.run(['docker', 'exec', CONTAINER, 'pg_dump', '-U', 'weknora',
                                 '-d', 'weknora', '-Fc'], stdout=output, stderr=subprocess.PIPE, timeout=120)
    if result.returncode or backup.stat().st_size == 0:
        raise RuntimeError('Database backup failed; index was not modified')
    with backup.open('rb') as source:
        subprocess.run(['docker', 'exec', '-i', CONTAINER, 'pg_restore', '-l'],
                       stdin=source, stdout=subprocess.DEVNULL, check=True, timeout=30)
    print('Validated private database backup:', backup, flush=True)
    require_success(sql(REPAIR))
    require_success(sql(PROBE))
    print('PASS: BM25 index rebuilt; embedding row count and contents unchanged; keyword query passed.')


if __name__ == '__main__':
    main()
