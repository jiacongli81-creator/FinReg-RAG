"""Copy an SQLite snapshot to an empty MySQL schema, validating all rows before commit."""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.mysql_db import connect,init_db

TABLES={
 'documents':('id','title','filename','file_type','effective_date','validity','created_at','status','error'),
 'chunks':('id','document_id','content','page','section','embedding'),
 'qa_history':('id','question','answer','sources','created_at'),
}
def digest(rows):
    h=hashlib.sha256()
    for row in rows: h.update(json.dumps(list(row),ensure_ascii=False,separators=(',',':')).encode('utf-8')+b'\n')
    return h.hexdigest()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--snapshot',type=Path,required=True);args=parser.parse_args()
    if args.snapshot.exists(): raise RuntimeError('Snapshot already exists')
    args.snapshot.parent.mkdir(parents=True,exist_ok=True)
    from app.config import settings
    with sqlite3.connect(f'file:{settings.database_path.as_posix()}?mode=ro',uri=True) as source, sqlite3.connect(args.snapshot) as backup:
        source.backup(backup)
    init_db()
    with sqlite3.connect(args.snapshot) as source, connect() as target:
        cur=target.cursor()
        for table in TABLES:
            cur.execute(f'SELECT COUNT(*) FROM {table}')
            if cur.fetchone()[0]: raise RuntimeError(f'MySQL {table} is not empty; refusing to overwrite')
        for table,columns in TABLES.items():
            names=','.join(columns)
            rows=source.execute(f'SELECT {names} FROM {table} ORDER BY id').fetchall()
            sql=f'INSERT INTO {table} ({names}) VALUES ('+','.join(['%s']*len(columns))+')'
            for start in range(0,len(rows),100): cur.executemany(sql,rows[start:start+100])
            cur.execute(f'SELECT {names} FROM {table} ORDER BY id')
            copied=cur.fetchall()
            if len(rows)!=len(copied) or digest(rows)!=digest(copied): raise RuntimeError(f'Validation failed for {table}')
            print(f'{table}: {len(rows)} rows verified',flush=True)
        cur.close()
    print('Migration committed; snapshot:',args.snapshot)
if __name__=='__main__': main()
