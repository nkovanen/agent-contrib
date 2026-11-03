'use strict';
const model = TipjarModel;
const $ = id => document.getElementById(id);
const samples = [
  ['fieldnotes/docs','welcome',['Documentation','Accessibility'],['Keep examples dependency-free']],
  ['little-tools/pathkit','welcome',['Regression tests','Small bug fixes'],['Discuss API changes first']],
  ['common-ground/ui','welcome',['Keyboard navigation','Documentation'],['Follow the contribution guide']],
  ['slow-software/parser','closed',['Tests'],['Agent contributions are currently closed']],
  ['weekend-labs/notebook','undeclared',[],[]],
  ['kindred-dev/seedling','unknown',['Examples'],[]]
];
const demo = () => model.parseSnapshot(JSON.stringify({format:'find-jars-report/1',complete:true,observations:samples.map(([repository,state,wanted,boundaries]) => ({repository,disposition:state,jar:{repository,state,complete:state !== 'unknown',manifest:['welcome','closed'].includes(state) ? {schema_version:'0.1',status:state,wanted,boundaries} : null,commit:null,sha256:null}}))})).reports;
let reports = demo(), isDemo = true, preview = null, lastOpener;
const stateLabel = {welcome:'Welcome',closed:'Closed',undeclared:'Undeclared',unknown:'Unknown / incomplete',excluded:'Excluded'};
const explanations = {excluded:'Excluded by discovery. Stop and inspect the source policies before considering work.',welcome:'A welcome to explore useful work. Read project policies before choosing a task.',closed:'This declaration declines agent contributions. Respect the stop.',undeclared:'No jar declared in this snapshot. Absence grants no approval.',unknown:'The observation is incomplete or unknown. Recheck before choosing work.'};
function el(tag, text, className) { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; }
function badge(row) { return el('span',stateLabel[row.state],'badge '+row.state); }
function notify(text) { $('toast').textContent = text; clearTimeout(notify.timer); notify.timer = setTimeout(() => { $('toast').textContent = ''; },4000); }
function render() {
  const visible = model.filterReports(reports,$('search').value,$('state').value);
  $('result-count').textContent = `${visible.length} of ${reports.length} ${isDemo ? 'sample ' : ''}repositories`;
  $('cards').replaceChildren(); $('empty').hidden = visible.length > 0;
  for (const row of visible) {
    const card = el('article',undefined,'card');
    const top = el('div',undefined,'card-top'); top.append(el('span','⌘','repo-icon'),badge(row));
    const tags = el('div',undefined,'tags');
    for (const text of row.manifest?.wanted || []) tags.append(el('span',text,'tag'));
    const bottom = el('div',undefined,'card-bottom');
    const open = el('button','Explore jar ↗'); open.type = 'button'; open.setAttribute('aria-label','Explore '+row.repository);
    open.addEventListener('click',() => openDetail(row,open));
    bottom.append(el('span',isDemo ? 'Fictional sample' : 'Unverified local snapshot'),open);
    card.append(top,el('h3',row.repository),el('p',explanations[row.state],'description'),tags,bottom);
    $('cards').append(card);
  }
}
function command(text) {
  const box = el('div',undefined,'command'), code = el('code',text), copy = el('button','Copy');
  copy.type = 'button'; copy.setAttribute('aria-label','Copy command: '+text);
  copy.addEventListener('click',async () => {
    try { await navigator.clipboard.writeText(text); copy.textContent = 'Copied'; notify('Command copied. Review it before running.'); }
    catch { const selection = getSelection(), range = document.createRange(); range.selectNodeContents(code); selection.removeAllRanges(); selection.addRange(range); notify('Copy unavailable here. Command selected; use your browser copy shortcut.'); }
  }); box.append(code,copy); return box;
}
function openDetail(row,opener) {
  lastOpener = opener;
  const body = $('detail-content'); body.replaceChildren();
  const title = el('h2',row.repository); title.id = 'detail-title';
  body.append(badge(row),title,el('p',isDemo ? 'Fictional sample — this is not a real invitation.' : 'Imported observation — provenance and claims are not verified by this page.','notice'),el('p',explanations[row.state]));
  for (const [key,label] of [['wanted','Wanted work'],['boundaries','Boundaries']]) {
    body.append(el('h3',label)); const list = el('ul');
    for (const text of row.manifest?.[key] || []) list.append(el('li',text));
    body.append(list.childElementCount ? list : el('p','Nothing declared.'));
  }
  body.append(el('h3','Source & freshness'));
  const source = model.sourceURL(row);
  if (!isDemo) {
    const link = el('a',source ? 'Read the pinned .tipjar.json on GitHub ↗' : 'Open repository on GitHub ↗');
    link.href = source || `https://github.com/${row.repository}`; link.rel = 'noreferrer noopener'; body.append(link);
  }
  body.append(el('p',isDemo ? 'Demo data has no source commit.' : `Commit: ${row.commit || 'not supplied'}\nManifest SHA-256: ${row.sha256 || 'not supplied'}`,'provenance'));
  body.append(el('h3',row.state === 'closed' ? 'Respect this boundary' : 'Your next careful step'));
  if (isDemo) body.append(el('p','These commands contain fictional repository names. Import a real snapshot to choose a real project.'));
  body.append(command(`tipjar jar ${row.repository}`));
  if (['welcome','undeclared'].includes(row.state)) {
    body.append(command(`tipjar discover ${row.repository} --signals`));
    body.append(el('p','After selecting an issue, replace ISSUE_NUMBER with its positive number:'));
    body.append(command(`tipjar inspect '${row.repository}#ISSUE_NUMBER' --ownership`));
    body.append(el('p','Read all repository policies and source instructions. Stop on refusals, incomplete reads, overlapping work, or unresolved claims. Prepare a task contract only after selecting an issue. Human authorization is required before implementation and separately before publication.','notice'));
  } else body.append(el('p','Do not begin agent work from this observation. The inspection command can recheck the current declaration; it grants no authority.','notice'));
  $('jar-detail').showModal();
}
$('close-detail').addEventListener('click',() => $('jar-detail').close());
$('jar-detail').addEventListener('close',() => lastOpener?.focus());
$('search').addEventListener('input',render); $('state').addEventListener('change',render);
$('clear-filters').addEventListener('click',() => { $('search').value=''; $('state').value='all'; render(); $('search').focus(); });
function restoreDemo() { $('import-errors').textContent=''; ++importSequence; reports=demo(); isDemo=true; $('dataset-label').textContent='FICTIONAL DEMO'; $('dataset-description').textContent='Sample projects to explore the flow. No real invitations or endorsements.'; $('reset-demo').hidden=true; $('snapshot').value=''; $('import-status').textContent='Demo restored. No imported data retained.'; $('import-status').classList.remove('error'); render(); }
$('reset-demo').addEventListener('click',restoreDemo);
let importSequence = 0;
async function importFile(file) {
  const sequence = ++importSequence;
  $('import-status').classList.remove('error'); $('import-status').textContent='Reading local snapshot…';
  try {
    if (!file || file.size > model.MAX_BYTES || !/\.json$/i.test(file.name)) throw new Error('Choose one .json file of at most 1 MiB.');
    const text = new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());
    const snapshot = model.parseSnapshot(text), next = snapshot.reports; if (sequence !== importSequence) return;
    reports=next; isDemo=false; $('dataset-label').textContent='LOCAL SNAPSHOT'; $('dataset-description').textContent='Partial indexed batch; never an exhaustive directory. '+(snapshot.complete ? 'Batch reads reported complete. ' : 'Batch reported incomplete. ')+'Unverified observations, never live approval.'; $('reset-demo').hidden=false;
    $('search').value=''; $('state').value='all'; render(); $('import-status').textContent=`Loaded ${next.length} repositories locally; ${snapshot.skippedUnidentifiable} unidentifiable observations skipped. Nothing uploaded.`;
    const searchErrors = {search_failed:'Search failed',search_incomplete:'Search reported incomplete results',short_page:'Search returned a short page'};
    $('import-errors').textContent=snapshot.errors.length ? `Search diagnostics (${snapshot.errors.length}): `+snapshot.errors.map(code => searchErrors[code] || 'Unrecognized search diagnostic').join('; ')+'.' : '';
  } catch (error) { if (sequence !== importSequence) return; $('import-status').textContent=`Could not import: ${error.message} Your current collection is unchanged.`; $('import-status').classList.add('error'); }
}
$('snapshot').addEventListener('change',event => importFile(event.target.files[0]));
for (const type of ['dragenter','dragover']) $('dropzone').addEventListener(type,event => { event.preventDefault(); $('dropzone').classList.add('dragging'); });
for (const type of ['dragleave','drop']) $('dropzone').addEventListener(type,event => { event.preventDefault(); $('dropzone').classList.remove('dragging'); });
$('dropzone').addEventListener('drop',event => { if (event.dataTransfer.files.length !== 1) { $('import-status').textContent='Drop exactly one JSON file.'; $('import-status').classList.add('error'); return; } importFile(event.dataTransfer.files[0]); });
function updateManifest() {
  try { preview=model.makeManifest($('manifest-status').value,$('wanted').value,$('boundaries').value); $('manifest-preview').textContent=JSON.stringify(preview,null,2)+'\n'; $('manifest-error').textContent=''; $('download').disabled=false; }
  catch (error) { preview=null; $('manifest-preview').textContent='Fix the fields above to preview valid JSON.'; $('manifest-error').textContent=error.message; $('manifest-error').classList.add('error'); $('download').disabled=true; }
}
$('manifest-form').addEventListener('input',updateManifest);
$('manifest-form').addEventListener('submit',event => { event.preventDefault(); updateManifest(); if (!preview) return; const url=URL.createObjectURL(new Blob([JSON.stringify(preview,null,2)+'\n'],{type:'application/json'})); const link=el('a'); link.href=url; link.download='.tipjar.json'; document.body.append(link); link.click(); link.remove(); setTimeout(()=>URL.revokeObjectURL(url),1000); notify('Manifest downloaded. Review it before adding it to a repository.'); });
render(); updateManifest();
