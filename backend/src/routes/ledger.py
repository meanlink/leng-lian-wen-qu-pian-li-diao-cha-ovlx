import hashlib, json, os
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import select, func
from src.config.database import get_db, Session
from src.models import Audit, LedgerState, LedgerSeal
from src.middlewares.auth import current_user, admin_only
from src.services import ledger
from src.services.audit import record
router = APIRouter(prefix='/ledger')

@router.get('')
def status(db=Depends(get_db), u=Depends(current_user)):
    state = db.get(LedgerState, 1)
    recent = db.scalars(select(Audit).order_by(Audit.id.desc()).limit(50))
    legacy = db.scalars(select(Audit).where(Audit.kind != 'entry').order_by(Audit.id.desc()).limit(50))
    return {'head_seq': state.head_seq if state else 0, 'head_hash': state.head_hash if state else ledger.GENESIS,
            'entries': db.scalar(select(func.count()).select_from(Audit).where(Audit.kind == 'entry')) or 0,
            'legacy': db.scalar(select(func.count()).select_from(Audit).where(Audit.kind != 'entry')) or 0,
            'seals': db.scalar(select(func.count()).select_from(LedgerSeal)) or 0,
            'recent': [ledger.audit_dict(a) for a in recent],
            'legacy_rows': [ledger.audit_dict(a) for a in legacy]}

@router.post('/seal', status_code=201)
def seal(db=Depends(get_db), u=Depends(admin_only)):
    new, created = ledger.seal(db, u.email)
    db.commit()
    done, failure = ledger.finalize_pending(Session)  # 恢复此前中断的封账文件，并写入本次文件
    if failure:
        raise HTTPException(500, '封账已入账但导出文件写入失败，请重新封账以恢复；重复操作不会新增封账')
    return {'seal': ledger.seal_dict(new), 'created': created, 'credential': ledger.credential_for(new),
            'recovered': [i for i in done if i != new.id]}

@router.get('/seals')
def seals(db=Depends(get_db), u=Depends(admin_only)):
    return [ledger.seal_dict(s) for s in db.scalars(select(LedgerSeal).order_by(LedgerSeal.id.desc()))]

def _seal_or_404(db, id):
    s = db.get(LedgerSeal, id)
    if not s:
        raise HTTPException(404, '封账记录不存在')
    return s

@router.get('/seals/{id}/credential')
def credential(id: int, db=Depends(get_db), u=Depends(admin_only)):
    s = _seal_or_404(db, id)
    return Response(ledger.canonical(ledger.credential_for(s)), media_type='application/json',
                    headers={'Content-Disposition': f'attachment; filename="ledger-seal-{s.id}-credential.json"'})

@router.get('/seals/{id}/export')
def export(id: int, db=Depends(get_db), u=Depends(admin_only)):
    s = _seal_or_404(db, id)
    path = ledger.export_path(s)
    ready = s.file_ready and os.path.exists(path)
    if ready:
        with open(path, 'rb') as f:
            ready = hashlib.sha256(f.read()).hexdigest() == s.file_checksum
    if not ready:
        raise HTTPException(409, '封账文件缺失或不完整，请重新执行封账以恢复；不会新增封账')
    return FileResponse(path, filename=f'ledger-seal-{s.id}-export.json', media_type='application/json')

class VerifyInput(BaseModel):
    # 原始文件文本：避免浏览器重新序列化 JSON 改变数字文本形式
    export_text: str
    credential_text: str

@router.post('/verify')
def verify(data: VerifyInput, db=Depends(get_db), u=Depends(admin_only)):
    try:
        export, credential = json.loads(data.export_text), json.loads(data.credential_text)
        conclusion = ledger.verify(export, credential)
    except json.JSONDecodeError as e:
        conclusion = {'ok': False, 'failure': {'stage': 'format', 'kind': '无法核验', 'reason': f'文件不是有效 JSON：{e}', 'seq': None}}
    record(db, u.email, 'ledger.verify', {'seal_id': conclusion.get('seal_id'), 'ok': conclusion['ok'],
                                          'kind': conclusion['failure']['kind'] if conclusion['failure'] else ''})
    db.commit()
    return conclusion

@router.get('/verifier')
def verifier(u=Depends(admin_only)):
    path = Path(__file__).resolve().parents[2] / 'scripts' / 'verify_ledger.py'
    if not path.exists():
        raise HTTPException(404, '离线核验脚本缺失')
    return FileResponse(path, filename='verify_ledger.py', media_type='text/x-python')
