#!/usr/bin/env python3
"""冷链温区偏离调查 · 审计账离线核验脚本（仅依赖 Python 标准库，可离线运行）。

用法：
    python3 verify_ledger.py <账本导出.json> <封账凭据.json>

核验内容：
    1. 凭据自身 MAC，确认凭据未被改写；
    2. 逐条重算哈希链，发现改写、删行、换序；
    3. 对照封账高度与链头哈希，发现整段截尾；
    4. 建链前历史记录仅列为“未认证历史”，不参与核验。

退出码：0 核验通过；1 核验失败；2 文件读取或用法错误。
请在封账时妥善保存本脚本与凭据；凭据是核验的唯一信任锚点。
"""
import hashlib
import hmac
import json
import math
import sys

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
    return json.dumps(_norm(value), sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def entry_hash(seq, actor, action, detail, at, prev_hash):
    payload = {'seq': seq, 'actor': actor, 'action': action, 'detail': detail or {}, 'at': at, 'prev_hash': prev_hash}
    return hashlib.sha256(canonical(payload).encode()).hexdigest()


def seal_mac(key_hex, seal_id, head_seq, head_hash):
    message = f'{MAC_DOMAIN}|{seal_id}|{head_seq}|{head_hash}'.encode()
    return hmac.new(bytes.fromhex(key_hex), message, hashlib.sha256).hexdigest()


def fail(stage, kind, reason, seq=None):
    return {'ok': False, 'failure': {'stage': stage, 'kind': kind, 'reason': reason, 'seq': seq}}


def verify(export, credential):
    try:
        if not isinstance(credential, dict) or credential.get('format') != SEAL_FORMAT:
            return fail('credential', '凭据无效', '凭据格式无法识别')
        key, seal_id = credential.get('key', ''), credential.get('seal_id')
        head_seq, head_hash = credential.get('head_seq'), credential.get('head_hash')
        if not isinstance(head_seq, int) or not isinstance(head_hash, str) or not key:
            return fail('credential', '凭据无效', '凭据缺少必要字段')
        expect = seal_mac(key, seal_id, head_seq, head_hash)
        if not hmac.compare_digest(expect, str(credential.get('mac', ''))):
            return fail('credential', '凭据被改写', '凭据 MAC 校验失败，凭据本身不可信')
        if not isinstance(export, dict) or export.get('format') != EXPORT_FORMAT:
            return fail('export', '导出无效', '账本导出格式无法识别')
        if export.get('seal_id') != seal_id:
            return fail('export', '不匹配', '导出文件与凭据不属于同一次封账')
        entries = export.get('entries')
        legacy = export.get('legacy', [])
        if not isinstance(entries, list) or not isinstance(legacy, list):
            return fail('export', '导出无效', '导出缺少条目列表')
        prev = GENESIS
        for index, e in enumerate(entries):
            seq = index + 1
            if not isinstance(e, dict) or e.get('seq') != seq:
                return fail('chain', '删行或换序', f"第 {seq} 位出现的序号是 {e.get('seq') if isinstance(e, dict) else '无效条目'}", seq)
            if e.get('prev_hash') != prev:
                return fail('chain', '删行或换序', f'序号 {seq} 的前置哈希与上一条不衔接', seq)
            try:
                actual = entry_hash(seq, e.get('actor'), e.get('action'), e.get('detail'), e.get('at'), e.get('prev_hash'))
            except (TypeError, ValueError):
                return fail('chain', '改写', f'序号 {seq} 内容无法规范化', seq)
            if actual != e.get('entry_hash'):
                return fail('chain', '改写', f'序号 {seq} 的内容哈希与记录不符', seq)
            prev = actual
        if len(entries) < head_seq:
            return fail('head', '截尾', f'导出仅 {len(entries)} 条，不足封账高度 {head_seq}')
        if entries[head_seq - 1].get('entry_hash') != head_hash:
            return fail('head', '改写', '封账高度处的链头哈希与凭据不一致', head_seq)
        head = export.get('head') or {}
        if head.get('seq') != head_seq or head.get('hash') != head_hash:
            return fail('head', '改写', '导出声明的链头与凭据不一致')
        return {'ok': True, 'failure': None, 'seal_id': seal_id, 'checked_entries': len(entries),
                'head_seq': head_seq, 'head_hash': head_hash, 'extra_after_seal': len(entries) - head_seq,
                'legacy_rows': len(legacy),
                'legacy_note': f'{len(legacy)} 条建链前历史记录未参与核验，属未认证历史' if legacy else '无未认证历史记录'}
    except Exception as e:
        return fail('format', '无法核验', f'文件内容异常：{e}')


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    try:
        with open(argv[1], encoding='utf-8') as f:
            export = json.load(f)
        with open(argv[2], encoding='utf-8') as f:
            credential = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f'无法读取文件：{e}')
        return 2
    conclusion = verify(export, credential)
    print(json.dumps(conclusion, ensure_ascii=False, indent=2))
    if conclusion['ok']:
        print(f"\n核验通过：封账 #{conclusion['seal_id']}，高度 {conclusion['head_seq']}，"
              f"链头 {conclusion['head_hash'][:16]}…，共核 {conclusion['checked_entries']} 条。")
        print(conclusion['legacy_note'])
        return 0
    failure = conclusion['failure']
    where = f"（序号 {failure['seq']}）" if failure.get('seq') else ''
    print(f"\n核验失败：{failure['kind']}{where} — {failure['reason']}")
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
