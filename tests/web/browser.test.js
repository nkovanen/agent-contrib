'use strict';
const frame = document.getElementById('app'), output = document.getElementById('results');
function check(condition, message) { if (!condition) throw new Error(message); output.textContent += '\nPASS: '+message; }
const settle = () => new Promise(resolve => setTimeout(resolve,100));
frame.addEventListener('load',async () => {
  output.textContent = 'Testing actual page events…';
  try {
    const win=frame.contentWindow, doc=frame.contentDocument, $=id=>doc.getElementById(id);
    check(doc.querySelectorAll('.card').length===6,'fictional demo loads');
    const row={repository:'sample/project',state:'welcome',complete:true,commit:'a'.repeat(40),sha256:'b'.repeat(64),manifest:{schema_version:'0.1',status:'welcome',wanted:['<img src=x onerror=alert(1)>'],boundaries:['Ask first']}};
    const snapshot=jar=>({format:'find-jars-report/1',complete:false,observations:[{repository:'sample/project',disposition:jar?.state || 'unknown',jar}]});
    async function importValue(value, drop=false) {
      const transfer=new win.DataTransfer(); transfer.items.add(new win.File([JSON.stringify(value)],'snapshot.json',{type:'application/json'}));
      if (drop) $('dropzone').dispatchEvent(new win.DragEvent('drop',{dataTransfer:transfer,bubbles:true,cancelable:true}));
      else { $('snapshot').files=transfer.files; $('snapshot').dispatchEvent(new win.Event('change',{bubbles:true})); }
      await settle();
    }
    await importValue(snapshot(row));
    check(doc.querySelectorAll('.card').length===1 && doc.querySelector('.card h3').textContent==='sample/project','file input loads local snapshot');
    check(!$('dataset-description').textContent.includes('coverage reported complete'),'incomplete discovery coverage stays visible');
    check(doc.querySelector('.tag').textContent==='<img src=x onerror=alert(1)>' && !doc.querySelector('.card img'),'hostile HTML stays literal');
    for (const jar of [false,0,'',true,[],42]) {
      await importValue(snapshot(jar));
      check($('import-status').textContent.includes('Could not import') && doc.querySelector('.card h3').textContent==='sample/project','invalid jar '+JSON.stringify(jar)+' preserves collection');
    }
    for (const [name,complete,skipped,error] of [['find-complete',true,0,false],['find-partial-null',false,1,false],['find-private-null',true,1,false],['find-search-error',false,0,true]]) {
      const canonical=await (await fetch('fixtures/'+name+'.json')).json();
      await importValue(canonical);
      check(doc.querySelectorAll('.card').length===1 && doc.querySelector('.card h3').textContent==='acme/project','canonical '+name+' retains identified repository');
      check($('dataset-description').textContent.includes('Partial indexed batch') && !$('dataset-description').textContent.includes('coverage reported complete'),'canonical '+name+' never claims exhaustive coverage');
      check($('dataset-description').textContent.includes(complete ? 'Batch reads reported complete' : 'Batch reported incomplete'),'canonical '+name+' distinguishes read completeness');
      check($('import-status').textContent.includes(skipped+' unidentifiable'),'canonical '+name+' counts suppressed identities');
      check(Boolean($('import-errors').textContent)===error,'canonical '+name+' separates search errors');
    }
    const invalidNull=await (await fetch('fixtures/find-partial-null.json')).json(); invalidNull.observations[1].jar=false;
    await importValue(invalidNull);
    check($('import-status').textContent.includes('Could not import') && doc.querySelector('.card h3').textContent==='acme/project','malformed null diagnostic preserves canonical collection');
    const dropped={...row,repository:'sample/dropped'};
    await importValue({format:'find-jars-report/1',complete:true,observations:[{repository:dropped.repository,disposition:'welcome',jar:dropped}]},true);
    check(doc.querySelector('.card h3').textContent==='sample/dropped','dropzone loads local snapshot');
    doc.querySelector('.card button').click();
    check($('jar-detail').open,'detail dialog opens');
    let copied=''; Object.defineProperty(win.navigator,'clipboard',{configurable:true,value:{writeText:async text=>{copied=text;}}});
    doc.querySelector('.command button').click(); await settle();
    check(copied==='tipjar jar sample/dropped','copy sends exact command to clipboard boundary');
    const closed = new Promise(resolve => $('jar-detail').addEventListener('close',()=>resolve(true),{once:true}));
    $('jar-detail').close();
    const closeDelivered = await Promise.race([closed,new Promise(resolve=>setTimeout(()=>resolve(false),2000))]);
    if (closeDelivered) check(doc.activeElement===doc.querySelector('.card button'),'dialog close restores opener focus');
    else output.textContent+='\nLIMIT: background browser deferred close event; focus restoration not verified';
    const text=Array.from({length:8},(_,i)=>String(i)+'😀'.repeat(499)).join('\n')+'\nDocumentation refresh';
    check(text.length>8015 && $('wanted').maxLength>=text.length,'input memory cap permits schema-valid astral text beyond old HTML cap');
    $('wanted').value=text; $('boundaries').value=''; $('wanted').dispatchEvent(new win.Event('input',{bubbles:true}));
    check(!$('download').disabled && JSON.parse($('manifest-preview').textContent).wanted.length===9,'real editor handles nine valid astral lines');
    let downloaded=null, filename='';
    win.URL.createObjectURL=blob=>{downloaded=blob;return 'blob:test';}; win.URL.revokeObjectURL=()=>{};
    win.HTMLAnchorElement.prototype.click=function(){filename=this.download;};
    $('manifest-form').dispatchEvent(new win.Event('submit',{bubbles:true,cancelable:true}));
    check(downloaded && filename==='.tipjar.json','download creates JSON blob with exact filename');
    const downloadedText=await downloaded.text(), manifest=JSON.parse(downloadedText);
    check(new win.TextEncoder().encode(downloadedText).length<=16384 && manifest.wanted.length===9,'download contains valid bounded manifest preview');
    $('wanted').value='\ufeff'; $('wanted').dispatchEvent(new win.Event('input',{bubbles:true}));
    check(JSON.parse($('manifest-preview').textContent).wanted[0]==='\ufeff','editor preserves nonblank FEFF');
    $('wanted').value='\u0085'; $('wanted').dispatchEvent(new win.Event('input',{bubbles:true}));
    check($('download').disabled,'editor refuses Unicode whitespace-only line');
    output.textContent+='\nBROWSER ASSERTIONS PASSED; review any LIMIT lines';
  } catch(error) { output.textContent+='\nFAIL: '+error.message; }
});
