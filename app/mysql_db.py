"""MySQL storage for the existing API; vectors remain JSON-encoded text."""
import json
from contextlib import contextmanager
from datetime import datetime, timezone
import mysql.connector
from .config import settings

@contextmanager
def connect():
    credentials = ({'app_user': settings.mysql_user, 'app_password': settings.mysql_password}
                   if settings.mysql_user else
                   json.loads(settings.mysql_credentials.read_text(encoding='utf-8')))
    conn = mysql.connector.connect(host=settings.mysql_host, port=settings.mysql_port,
        user=credentials['app_user'], password=credentials['app_password'],
        database=settings.mysql_database, charset='utf8mb4', connection_timeout=10)
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    statements = [
        """CREATE TABLE IF NOT EXISTS documents (id VARCHAR(36) PRIMARY KEY, title TEXT NOT NULL,
        filename TEXT NOT NULL, file_type VARCHAR(32) NOT NULL, effective_date VARCHAR(64),
        validity VARCHAR(32) NOT NULL DEFAULT 'unknown', created_at VARCHAR(64) NOT NULL,
        status VARCHAR(32) NOT NULL, error TEXT) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
        """CREATE TABLE IF NOT EXISTS chunks (id VARCHAR(36) PRIMARY KEY, document_id VARCHAR(36) NOT NULL,
        content LONGTEXT NOT NULL, page INT, section TEXT, embedding LONGTEXT NOT NULL,
        INDEX idx_chunks_document(document_id), FOREIGN KEY (document_id) REFERENCES documents(id))
        ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
        """CREATE TABLE IF NOT EXISTS qa_history (id BIGINT AUTO_INCREMENT PRIMARY KEY,
        question TEXT NOT NULL, answer LONGTEXT NOT NULL, sources LONGTEXT NOT NULL,
        created_at VARCHAR(64) NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    ]
    with connect() as conn:
        cursor=conn.cursor()
        for statement in statements: cursor.execute(statement)
        cursor.close()

def _execute(sql, params=(), many=False):
    with connect() as conn:
        cur=conn.cursor(dictionary=True)
        if many: cur.executemany(sql, params)
        else: cur.execute(sql, params)
        rows=cur.fetchall() if cur.with_rows else []
        cur.close()
        return rows

def insert_document(document):
    keys=('id','title','filename','file_type','effective_date','validity','created_at','status','error')
    _execute('INSERT INTO documents ('+','.join(keys)+') VALUES ('+','.join(['%s']*len(keys))+')',tuple(document[k] for k in keys))

def insert_chunks(chunks):
    if chunks:
        _execute('INSERT INTO chunks (id,document_id,content,page,section,embedding) VALUES (%s,%s,%s,%s,%s,%s)',
            [(c['id'],c['document_id'],c['content'],c['page'],c['section'],json.dumps(c['embedding'],ensure_ascii=False)) for c in chunks],True)

def list_documents():
    return _execute('SELECT d.*, (SELECT COUNT(*) FROM chunks c WHERE c.document_id=d.id) AS chunk_count FROM documents d ORDER BY d.created_at DESC')

def get_document_chunks(document_id):
    return _execute('SELECT id,document_id,content,page,section FROM chunks WHERE document_id=%s ORDER BY COALESCE(page,0),id',(document_id,))

def get_chunks(only_valid):
    sql="SELECT c.*,d.title,d.filename,d.effective_date,d.validity FROM chunks c JOIN documents d ON d.id=c.document_id WHERE d.status='ready'"
    return _execute(sql+(" AND d.validity IN ('valid','unknown')" if only_valid else ''))

def get_search_chunks(only_valid):
    sql="SELECT c.id,c.document_id,c.content,c.page,c.section,d.title,d.effective_date,d.validity FROM chunks c JOIN documents d ON d.id=c.document_id WHERE d.status='ready'"
    return _execute(sql+(" AND d.validity IN ('valid','unknown')" if only_valid else ''))

def get_ready_chunks_for_embedding():
    return _execute("SELECT c.id,c.content FROM chunks c JOIN documents d ON d.id=c.document_id WHERE d.status='ready' ORDER BY c.id")

def update_chunk_embeddings(embeddings):
    if embeddings: _execute('UPDATE chunks SET embedding=%s WHERE id=%s',[(json.dumps(v,ensure_ascii=False),k) for k,v in embeddings.items()],True)

def save_history(question,answer,sources):
    with connect() as conn:
        cur=conn.cursor()
        cur.execute('INSERT INTO qa_history (question,answer,sources,created_at) VALUES (%s,%s,%s,%s)',
                    (question,answer,json.dumps(sources,ensure_ascii=False),datetime.now(timezone.utc).isoformat()))
        result=int(cur.lastrowid)
        cur.close()
        return result
