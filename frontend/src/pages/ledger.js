import {ledger} from '../api/entities.js';
import {downloadFile,saveJson} from '../api/client.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {esc,date,notify} from '../utils/dom.js';
const hash=v=>'<code class="hash">'+esc((v||'').slice(0,16))+'…</code>';
const kind=a=>a.kind==='entry'?'<span class="badge ok">链上 #'+a.seq+'</span>':'<span class="badge muted">未认证历史</span>';
export async function ledgerPage(){
 const [s,seals]=await Promise.all([ledger.status(),session.user.role==='admin'?ledger.seals():Promise.resolve([])]);
 const admin=session.user.role==='admin';
 return heading('06 / AUDIT LEDGER','审计账本与封账核验','接入、调查、批准与分发动作逐条接入哈希链；封账凭据离线保存，可随时核验账本是否被改写、删行、换序或截尾。',admin?'<button class="button primary" id="seal-now">立即封账 ⏺</button>':'')
 +'<section class="overview-hero ledger-hero"><div class="narrative"><p class="eyebrow">当前链头</p><h2>高度 #'+s.head_seq+' · '+hash(s.head_hash)+'</h2><p>每条留痕携带上一条的哈希，任何改动都会断链。封账后仍可继续记账，旧凭据对旧高度持续有效。</p></div><div class="numbers">'+[['链上留痕',s.entries],['未认证历史',s.legacy],['封账次数',s.seals],['当前高度','#'+s.head_seq]].map(([k,v])=>'<div><span>'+k+'</span><strong>'+v+'</strong></div>').join('')+'</div></section>'
 +'<div class="two-columns ledger-grid"><section class="panel"><div class="section-title"><h2>封账记录</h2><span>'+(admin?seals.length+' 次封账':'仅负责人可见')+'</span></div>'
 +(admin?(seals.length?'<div class="table-wrap"><table><thead><tr><th>封账</th><th>时间</th><th>高度</th><th>链头哈希</th><th>文件</th><th></th></tr></thead><tbody>'+seals.map(x=>'<tr><td>#'+x.id+'</td><td>'+date(x.sealed_at)+'</td><td>#'+x.head_seq+'</td><td>'+hash(x.head_hash)+'</td><td>'+(x.file_ready?'<span class="badge ok">完整 '+x.file_bytes+' B</span>':'<span class="badge warn">待恢复</span>')+'</td><td class="actions"><button class="text-button" data-credential="'+x.id+'">凭据 ↓</button><button class="text-button" data-export="'+x.id+'">账本导出 ↓</button></td></tr>').join('')+'</tbody></table></div>':'<p class="empty">尚未封账。点击右上角「立即封账」生成首份凭据，并立即离线保存。</p>'):'<p class="empty">封账与凭据下载仅业务负责人可用；当前账号可查看链状态与留痕。</p>')
 +'<p class="hint">凭据包含该高度的链头哈希与核验密钥，请下载后离线妥善保存；它是发现账本被改动的唯一锚点。若导出文件因中断缺失，重新封账即可恢复，不会新增封账。</p></section>'
 +(admin?'<section class="panel"><div class="section-title"><h2>离线核验</h2><span>上传导出与凭据</span></div><div class="verify-box"><label>账本导出文件<input type="file" id="verify-export" accept=".json"></label><label>封账凭据文件<input type="file" id="verify-credential" accept=".json"></label><button class="primary" id="verify-run">开始核验</button><button class="text-button" id="verifier-download">下载离线核验脚本 verify_ledger.py ↓</button></div><div id="verify-result"></div><p class="hint">离线环境请运行：python3 verify_ledger.py 账本导出.json 封账凭据.json。结论一致：通过、或指出改写 / 删行 / 换序 / 截尾的位置。</p></section>':'<section class="method-sheet compact"><p class="eyebrow">HOW VERIFICATION WORKS</p><h3>凭据即锚点</h3><p>负责人在封账时下载凭据并离线保存。凭据记录该高度的链头哈希与核验密钥；之后任何时候，用凭据对照账本导出重算哈希链，即可发现改写、删行、换序与整段截尾。</p><p>建链前的历史留痕标注为「未认证历史」，不参与链式核验，也不作为可信起点。</p></section>')
 +'</div>'
 +'<section class="panel"><div class="section-title"><h2>最近留痕</h2><span>最新 50 条 · 链上 / 未认证历史</span></div><div class="table-wrap"><table><thead><tr><th>状态</th><th>动作</th><th>账号</th><th>时间</th><th>条目哈希</th></tr></thead><tbody>'+s.recent.map(a=>'<tr><td>'+kind(a)+'</td><td><strong>'+esc(a.action)+'</strong></td><td>'+esc(a.actor)+'</td><td>'+date(a.at)+'</td><td>'+(a.kind==='entry'?hash(a.entry_hash):'<span class="muted-text">—</span>')+'</td></tr>').join('')+'</tbody></table></div></section>'
 +(s.legacy_rows.length?'<section class="panel"><div class="section-title"><h2>未认证历史</h2><span>'+s.legacy+' 条 · 建链前留痕，不参与核验，不作可信起点</span></div><div class="table-wrap"><table><thead><tr><th>状态</th><th>动作</th><th>账号</th><th>时间</th></tr></thead><tbody>'+s.legacy_rows.map(a=>'<tr><td><span class="badge muted">未认证历史</span></td><td><strong>'+esc(a.action)+'</strong></td><td>'+esc(a.actor)+'</td><td>'+date(a.at)+'</td></tr>').join('')+'</tbody></table></div></section>':'');
}
async function readText(input){const f=input.files[0];if(!f)throw new Error('请先选择文件');return f.text();}
export function bindLedger(refresh){
 document.querySelector('#seal-now')?.addEventListener('click',async()=>{try{const r=await ledger.seal();saveJson(r.credential,'ledger-seal-'+r.seal.id+'-credential.json');notify(r.created?'封账 #'+r.seal.id+' 完成（高度 #'+r.seal.head_seq+'），凭据已下载，请离线保存':'当前高度已有封账 #'+r.seal.id+'，已恢复文件并重新下载凭据');await refresh();}catch(e){notify(e.message,true);}});
 document.querySelectorAll('[data-credential]').forEach(b=>b.onclick=()=>downloadFile('/ledger/seals/'+b.dataset.credential+'/credential','ledger-seal-'+b.dataset.credential+'-credential.json').catch(e=>notify(e.message,true)));
 document.querySelectorAll('[data-export]').forEach(b=>b.onclick=()=>downloadFile('/ledger/seals/'+b.dataset.export+'/export','ledger-seal-'+b.dataset.export+'-export.json').catch(e=>notify(e.message,true)));
 document.querySelector('#verifier-download')?.addEventListener('click',()=>downloadFile('/ledger/verifier','verify_ledger.py').catch(e=>notify(e.message,true)));
 document.querySelector('#verify-run')?.addEventListener('click',async()=>{
  const box=document.querySelector('#verify-result');
  try{
   const exportText=await readText(document.querySelector('#verify-export')),credentialText=await readText(document.querySelector('#verify-credential'));
   const c=await ledger.verify({export_text:exportText,credential_text:credentialText});
   box.innerHTML=c.ok?'<div class="verify-result ok"><strong>✓ 核验通过</strong><p>封账 #'+c.seal_id+' · 高度 #'+c.head_seq+' · 共核 '+c.checked_entries+' 条，哈希链完整连续。</p><p>'+esc(c.legacy_note)+'</p></div>'
    :'<div class="verify-result fail"><strong>✗ 核验失败：'+esc(c.failure.kind)+'</strong><p>'+esc(c.failure.reason)+(c.failure.seq?'（序号 '+c.failure.seq+'）':'')+'</p><p>账本可能遭遇篡改，请冻结当前数据并追查来源。</p></div>';
  }catch(e){box.innerHTML='<div class="verify-result fail"><strong>✗ 无法核验</strong><p>'+esc(e.message)+'</p></div>';}
 });
}
