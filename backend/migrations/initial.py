from sqlalchemy import inspect, text
from src.config.database import Base, engine
from src import models
from src.services.ledger import GENESIS

# 既有 audits 表需要补的链式字段；新增列默认把旧行标为未认证历史
AUDIT_CHAIN_COLUMNS = [
    ('seq', 'INTEGER'),
    ('prev_hash', "VARCHAR(64) NOT NULL DEFAULT ''"),
    ('entry_hash', "VARCHAR(64) NOT NULL DEFAULT ''"),
    ('kind', "VARCHAR(16) NOT NULL DEFAULT 'legacy'"),
]

def migrate():
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        existing = {c['name'] for c in inspect(conn).get_columns('audits')}
        for name, ddl in AUDIT_CHAIN_COLUMNS:
            if name not in existing:
                conn.execute(text(f'ALTER TABLE audits ADD COLUMN {name} {ddl}'))
        indexes = {i['name'] for i in inspect(conn).get_indexes('audits')}
        if 'uq_audits_seq' not in indexes:
            conn.execute(text('CREATE UNIQUE INDEX uq_audits_seq ON audits (seq)'))
        if not conn.execute(text('SELECT COUNT(*) FROM ledger_state')).scalar():
            conn.execute(text('INSERT INTO ledger_state (id, head_seq, head_hash, updated_at) VALUES (1, 0, :genesis, 0)'), {'genesis': GENESIS})

if __name__ == '__main__':
    migrate()
