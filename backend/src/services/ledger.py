"""连续可验审计账：哈希链追加、封账、导出与核验。

- 追加与业务变更处于同一数据库事务，同成同败；失败回滚不留伪记录。
- 所有追加先锁定 ledger_state 单行，并发下序号唯一且连续。
- 封账把头高度与链头哈希写入凭据，凭据由管理员离线保存，作为核验锚点。
- 导出文件先写临时文件、fsync、再原子改名；只有校验完整的文件才允许下载。
"""
import hashlib, hmac, json, math, os, secrets, time
from sqlalchemy import select, func
from src.config.settings import ARTIFACT_DIR
from src.models import Audit, LedgerState, LedgerSeal

GENESIS = '0' * 64
SEAL_FORMAT = 'cold-excursion.ledger-seal'
EXPORT_FORMAT = 'cold-excursion.ledger-export'
MAC_DOMAIN = 'cold-excursion-seal-v1'

def _norm(value):
    """数值归一：整数值浮点归为整数。JSON 中 8 与 8.0 同值，
    浏览器等中间环节会互相改写，归一后哈希对改写文本形式免疫。"""
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError('留痕内容含非有限数值')
        return int(value) if value.is_integer() else value
    if isinstance(value, dict):
        return {k: _norm(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_norm(v) for v in value]
    return value

def canonical(value):
    """确定性 JSON：键排序、紧凑分隔符、数值归一、禁止 NaN，保证后端与离线脚本逐字节一致。"""
    return json.dumps(_norm(value), sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))

def entry_hash(seq, actor, action, detail, at, prev_hash):
    payload = {'seq': seq, 'actor': actor, 'action': action, 'detail': detail or {}, 'at': at, 'prev_hash': prev_hash}
    return hashlib.sha256(canonical(payload).encode()).hexdigest()

def seal_mac(key_hex, seal_id, head_seq, head_hash):
    message = f'{MAC_DOMAIN}|{seal_id}|{head_seq}|{head_hash}'.encode()
    return hmac.new(bytes.fromhex(key_hex), message, hashlib.sha256).hexdigest()

def _state(db):
    state = db.scalar(select(LedgerState).where(LedgerState.id == 1).with_for_update())
    if state is None:  # 迁移尚未写入单行时的兜底；并发下由主键约束保证只成功一次
        state = LedgerState(id=1, head_seq=0, head_hash=GENESIS, updated_at=time.time())
        db.add(state)
        db.flush()
        state = db.scalar(select(LedgerState).where(LedgerState.id == 1).with_for_update())
    return state

def _append(db, state, actor, action, detail=None):
    # 先规范化 detail，使入库 JSON 与哈希输入逐字节一致，避免数据库回读差异造成误报
    detail = json.loads(canonical(detail or {}))
    at = time.time()
    seq = state.head_seq + 1
    hashed = entry_hash(seq, actor, action, detail, at, state.head_hash)
    entry = Audit(actor=actor, action=action, detail=detail, at=at,
                  seq=seq, prev_hash=state.head_hash, entry_hash=hashed, kind='entry')
    db.add(entry)
    state.head_seq = seq
    state.head_hash = hashed
    state.updated_at = at
    return entry

def append(db, actor, action, detail=None):
    """在调用方事务内追加链上留痕；随业务变更一起提交或回滚。"""
    return _append(db, _state(db), actor, action, detail)

def seal(db, actor):
    """在当前链头封账。同一高度重复调用复用既有封账，不新增记录。

    封账动作本身作为下一条链上留痕入账，并被本次封账覆盖，
    因此重试时链头不变，天然幂等。
    """
    state = _state(db)
    latest = db.scalar(select(LedgerSeal).order_by(LedgerSeal.id.desc()).limit(1))
    if latest and latest.head_seq == state.head_seq:
        return latest, False
    legacy = db.scalar(select(func.count()).select_from(Audit).where(Audit.kind != 'entry')) or 0
    new = LedgerSeal(sealed_at=time.time(), head_seq=state.head_seq + 1, head_hash='',
                     entries=state.head_seq + 1, legacy=legacy, seal_key=secrets.token_hex(32), mac='')
    db.add(new)
    db.flush()
    entry = _append(db, state, actor, 'ledger.seal', {'seal_id': new.id, 'head_seq': new.head_seq})
    new.head_hash = entry.entry_hash
    new.mac = seal_mac(new.seal_key, new.id, new.head_seq, new.head_hash)
    return new, True

def credential_for(seal):
    return {'format': SEAL_FORMAT, 'version': 1, 'seal_id': seal.id, 'sealed_at': seal.sealed_at,
            'head_seq': seal.head_seq, 'head_hash': seal.head_hash, 'entries': seal.entries,
            'key': seal.seal_key, 'mac': seal.mac}

def build_export(db, seal):
    """导出内容只取决于被封账的链上前缀与历史行，重试生成逐字节一致。"""
    entries = db.scalars(select(Audit).where(Audit.kind == 'entry', Audit.seq <= seal.head_seq).order_by(Audit.seq))
    legacy = db.scalars(select(Audit).where(Audit.kind != 'entry').order_by(Audit.id))
    return {'format': EXPORT_FORMAT, 'version': 1, 'seal_id': seal.id, 'exported_at': seal.sealed_at,
            'head': {'seq': seal.head_seq, 'hash': seal.head_hash},
            'entries': [{'seq': e.seq, 'actor': e.actor, 'action': e.action, 'detail': e.detail,
                         'at': e.at, 'prev_hash': e.prev_hash, 'entry_hash': e.entry_hash} for e in entries],
            'legacy': [{'id': e.id, 'actor': e.actor, 'action': e.action, 'detail': e.detail, 'at': e.at} for e in legacy]}

def export_path(seal):
    return os.path.join(ARTIFACT_DIR, 'ledger', f'ledger-seal-{seal.id}.json')

def finalize_pending(db_factory):
    """为所有文件未就绪的封账写入导出文件。临时文件 + fsync + 原子改名，
    中断后重试不产生新封账，也绝不开放残缺文件。返回 (完成的封账id, 最后的异常)。"""
    done, failure = [], None
    with db_factory() as db:
        pending = list(db.scalars(select(LedgerSeal).where(LedgerSeal.file_ready == False).order_by(LedgerSeal.id)))
        for seal in pending:
            try:
                data = canonical(build_export(db, seal)).encode()
                checksum = hashlib.sha256(data).hexdigest()
                path = export_path(seal)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                tmp = path + '.tmp'
                with open(tmp, 'wb') as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
                with open(tmp, 'rb') as f:
                    if hashlib.sha256(f.read()).hexdigest() != checksum:
                        raise IOError('封账文件写入校验失败')
                os.replace(tmp, path)  # 同目录原子改名，读者只会看到完整文件
                seal.file_ready = True
                seal.file_checksum = checksum
                seal.file_bytes = len(data)
                db.commit()
                done.append(seal.id)
            except Exception as e:  # 保留 file_ready=False，等待下次恢复
                db.rollback()
                failure = e
    return done, failure

def _fail(stage, kind, reason, seq=None):
    return {'ok': False, 'failure': {'stage': stage, 'kind': kind, 'reason': reason, 'seq': seq}}

def verify(export, credential):
    """核验导出账本与封账凭据，能发现改写、删行、换序与整段截尾。"""
    try:
        if not isinstance(credential, dict) or credential.get('format') != SEAL_FORMAT:
            return _fail('credential', '凭据无效', '凭据格式无法识别')
        key, seal_id = credential.get('key', ''), credential.get('seal_id')
        head_seq, head_hash = credential.get('head_seq'), credential.get('head_hash')
        if not isinstance(head_seq, int) or not isinstance(head_hash, str) or not key:
            return _fail('credential', '凭据无效', '凭据缺少必要字段')
        expect = seal_mac(key, seal_id, head_seq, head_hash)
        if not hmac.compare_digest(expect, str(credential.get('mac', ''))):
            return _fail('credential', '凭据被改写', '凭据 MAC 校验失败，凭据本身不可信')
        if not isinstance(export, dict) or export.get('format') != EXPORT_FORMAT:
            return _fail('export', '导出无效', '账本导出格式无法识别')
        if export.get('seal_id') != seal_id:
            return _fail('export', '不匹配', '导出文件与凭据不属于同一次封账')
        entries = export.get('entries')
        legacy = export.get('legacy', [])
        if not isinstance(entries, list) or not isinstance(legacy, list):
            return _fail('export', '导出无效', '导出缺少条目列表')
        prev = GENESIS
        for index, e in enumerate(entries):
            seq = index + 1
            if not isinstance(e, dict) or e.get('seq') != seq:
                return _fail('chain', '删行或换序', f"第 {seq} 位出现的序号是 {e.get('seq') if isinstance(e, dict) else '无效条目'}", seq)
            if e.get('prev_hash') != prev:
                return _fail('chain', '删行或换序', f'序号 {seq} 的前置哈希与上一条不衔接', seq)
            try:
                actual = entry_hash(seq, e.get('actor'), e.get('action'), e.get('detail'), e.get('at'), e.get('prev_hash'))
            except (TypeError, ValueError):
                return _fail('chain', '改写', f'序号 {seq} 内容无法规范化', seq)
            if actual != e.get('entry_hash'):
                return _fail('chain', '改写', f'序号 {seq} 的内容哈希与记录不符', seq)
            prev = actual
        if len(entries) < head_seq:
            return _fail('head', '截尾', f'导出仅 {len(entries)} 条，不足封账高度 {head_seq}')
        if entries[head_seq - 1].get('entry_hash') != head_hash:
            return _fail('head', '改写', '封账高度处的链头哈希与凭据不一致', head_seq)
        head = export.get('head') or {}
        if head.get('seq') != head_seq or head.get('hash') != head_hash:
            return _fail('head', '改写', '导出声明的链头与凭据不一致')
        return {'ok': True, 'failure': None, 'seal_id': seal_id, 'checked_entries': len(entries),
                'head_seq': head_seq, 'head_hash': head_hash, 'extra_after_seal': len(entries) - head_seq,
                'legacy_rows': len(legacy),
                'legacy_note': f'{len(legacy)} 条建链前历史记录未参与核验，属未认证历史' if legacy else '无未认证历史记录'}
    except Exception as e:
        return _fail('format', '无法核验', f'文件内容异常：{e}')

def seal_dict(s):
    return {'id': s.id, 'sealed_at': s.sealed_at, 'head_seq': s.head_seq, 'head_hash': s.head_hash,
            'entries': s.entries, 'legacy': s.legacy, 'file_ready': s.file_ready,
            'file_checksum': s.file_checksum, 'file_bytes': s.file_bytes}

def audit_dict(a):
    return {'id': a.id, 'seq': a.seq, 'actor': a.actor, 'action': a.action, 'detail': a.detail,
            'at': a.at, 'kind': a.kind, 'entry_hash': a.entry_hash}
