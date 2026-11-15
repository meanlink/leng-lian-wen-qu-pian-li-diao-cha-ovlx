from src.services import ledger
def record(db, actor, action, detail=None):
    """业务留痕：与业务变更同一事务提交或回滚，并接入哈希链。"""
    return ledger.append(db, actor, action, detail)
