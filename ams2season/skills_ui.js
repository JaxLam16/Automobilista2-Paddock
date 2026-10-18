/* Local skill measurements. No inferred optimal score, audio or game control. */
window.PaddockSkills = (function(){
  'use strict';
  function option(select,h,id,label){
    if(!Array.prototype.some.call(select.options,function(o){return o.value===id;}))select.append(h('option',{value:id},label));
  }
  function referenceLabel(r){
    var date=r.started_at?String(r.started_at).slice(0,16).replace('T',' '):'';
    return (r.source==='imported_pack'?'Imported • ':'')+(r.kind==='exact_car'?'Exact car':'Same class')+' • '+r.driver+' • '+r.car+(date?' • '+date:'');
  }
  function packImport(ui,onImported){
    var h=ui.h,api=ui.api,note=h('span',{class:'hint',role:'status'}),busy=false;
    var file=h('input',{type:'file',accept:'.paddockref',style:{maxWidth:'100%'},'aria-label':'Import corner reference pack'});
    file.onchange=function(){
      if(busy||!file.files.length)return;var chosen=file.files[0];
      if(chosen.size>512*1024){note.textContent='Choose a reference pack at most512 KB.';file.value='';return;}
      busy=true;file.disabled=true;note.textContent='Checking private reference pack…';
      chosen.arrayBuffer().then(function(buffer){var bytes=new Uint8Array(buffer),binary='';
        for(var i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode.apply(null,bytes.subarray(i,i+32768));
        return api('/api/skills/packs/import','POST',{data:btoa(binary)});
      }).then(function(r){note.textContent=(r.already_imported?'Already imported: ':'Imported: ')+r.driver+' • '+r.car+' • '+r.traces+' input snippets. '+r.verification;onImported(r);})
        .catch(function(e){note.textContent=e.message||String(e);}).finally(function(){busy=false;file.disabled=false;file.value='';});
    };
    return h('div',{style:{minWidth:'0',margin:'10px 0'}},h('label',null,'Import reference pack ',file),h('p',null,note));
  }
  function tracePlot(h,trace){
    function svg(tag,attrs){var el=document.createElementNS('http://www.w3.org/2000/svg',tag);Object.keys(attrs||{}).forEach(function(k){el.setAttribute(k,attrs[k]);});return el;}
    var el=svg('svg',{viewBox:'0 0 600 164',role:'img','aria-label':'Reference brake, throttle and signed steering input by distance',style:'width:100%;height:auto;max-height:240px;display:block'}),xs=trace.x,min=xs[0],span=xs[xs.length-1]-min;
    function x(v){return 24+(v-min)/span*552;}
    el.append(svg('line',{x1:24,x2:576,y1:70,y2:70,stroke:'#a3afbf','stroke-width':.5}));
    if(min<=0&&min+span>=0)el.append(svg('line',{x1:x(0),x2:x(0),y1:8,y2:132,stroke:'#a3afbf','stroke-dasharray':'3 3'}));
    [['brake','#c34856'],['throttle','#27a973'],['steering','#638ae8']].forEach(function(pair){
      var points='',open=false;
      trace[pair[0]].forEach(function(v,i){if(v==null){open=false;return;}points+=(open?' L':' M')+x(xs[i]).toFixed(2)+' '+(70-v*.6).toFixed(2);open=true;});
      el.append(svg('path',{d:points,fill:'none',stroke:pair[1],'stroke-width':1.7}));
    });
    [min,0,min+span].filter(function(v,i,a){return v>=min&&v<=min+span&&a.indexOf(v)===i;}).forEach(function(v){var text=svg('text',{x:x(v),y:153,'text-anchor':'middle','font-size':11,fill:'currentColor'});text.textContent=Math.round(v)+' m';el.append(text);});
    return h('details',null,h('summary',null,'Reference inputs • source lap '+trace.lap),h('p',{class:'hint'},'Brake (red), throttle (green), signed steering (blue), normalized input %. Distance is relative to the corner landmark. Selected input traces are sampled every5 m without pedal shift filtering.'),el);
  }
  function metric(h,m){
    m=m||{label:'Skill',detail:'Waiting for evidence.',status:'unavailable'};
    var scale=m.scale,bar=h('div',{style:{display:'flex',gap:'3px',height:'19px',margin:'14px 0 8px'},'aria-hidden':'true'});
    for(var i=0;i<28;i++){var balanced=scale&&scale.bands,edge=Math.abs((i+.5)/28-.5),marked=scale&&scale.fraction!=null&&i===Math.min(27,Math.floor(scale.fraction*28));bar.append(h('span',{style:{flex:'1',minWidth:'0',borderRadius:'2px',background:marked?'#eef4fb':balanced?(edge>.32?'#a33740':edge>.16?'#a28b36':'#26864a'):'#344555',boxShadow:marked?'0 0 0 1px #17212c':null}}));}
    return h('div',{'data-skill-readout':m.label,style:{border:'1px solid var(--line)',borderRadius:'10px',padding:'18px',minWidth:'0',overflowWrap:'anywhere'}},
      h('small',{class:'muted'},m.label),h('div',{style:{fontSize:'1.5em',fontWeight:'700',marginTop:'8px'}},m.value==null?'Evidence unavailable':m.value+' '+(m.unit||'')),bar,
      h('small',{class:'muted'},scale?scale.left+' → '+scale.right:'Measurement • no optimal target'),m.feedback?h('div',{style:{textAlign:'center',fontWeight:'700',marginTop:'8px'}},m.feedback):null,h('p',{class:'hint'},m.detail));
  }
  function overlay(ui){
    var h=ui.h,api=ui.api,alive=true,loaded=false,dirty=false,state={},saving=false;
    var form=h('div'),preview=h('div'),note=h('p',{class:'hint',role:'status'});
    var enabled=h('input',{type:'checkbox','aria-label':'Show live skill overlay'}),selected=h('select',{'aria-label':'Selected overlay skill'});
    var timing=h('select',{'aria-label':'Skill feedback timing'},[['exit','After corner exit'],['both','Live and after exit'],['live','Live only']].map(function(v){return h('option',{value:v[0]},v[1]);}));
    var duration=h('input',{type:'number',min:2,max:20,value:6,'aria-label':'Skill result duration',style:{width:'6em'}});
    var position=h('select',{'aria-label':'Skill overlay position'},[['center','Centre screen'],['right','Top right'],['left','Top left']].map(function(v){return h('option',{value:v[0]},v[1]);}));
    var opacity=h('input',{type:'range',min:40,max:100,step:5,'aria-label':'Skill overlay opacity'});
    var size=h('select',{'aria-label':'Skill overlay size'},h('option',{value:'compact'},'Minimal strip'),h('option',{value:'normal'},'Detailed panel'));
    var reference=h('select',{'aria-label':'Live skill coaching reference',style:{maxWidth:'100%',minWidth:'0'}},h('option',{value:''},'Telemetry technique indicators (default)'));
    var skills={},sessions={},cornerChecks={},cornerBox=h('div'),all=h('input',{type:'checkbox',checked:true,'aria-label':'Every corner'});
    function edit(){dirty=true;note.textContent='Unsaved overlay changes.';}
    function cycle(action){api('/api/skills/overlay/action','POST',{action:action}).then(function(s){selected.value=s.selected;paint(s);}).catch(fail);}
    function fail(e){note.textContent=e.message||String(e);}
    function corners(s){
      var known=s.corners||[], signature=JSON.stringify(known);
      if(cornerBox.dataset.signature===signature)return;
      cornerBox.dataset.signature=signature;cornerBox.replaceChildren();
      known.forEach(function(c){var old=cornerChecks[c];var box=h('input',{type:'checkbox',checked:old?old.checked:(s.settings.corners||[]).indexOf(c)>=0,onchange:edit});cornerChecks[c]=box;cornerBox.append(h('label',{style:{display:'inline-block',margin:'6px 14px 6px 0'}},box,' '+c));});
      if(!known.length)cornerBox.append(h('span',{class:'hint'},'Corner names appear from a saved map or after one clean lap. Every corner is enabled by default.'));
      cornerBox.hidden=all.checked;
    }
    function paint(s){
      if(!alive)return;state=s;
      if(!loaded){
        loaded=true;var cfg=s.settings;enabled.checked=cfg.enabled;selected.replaceChildren();
        (s.catalog||[]).forEach(function(c){selected.append(h('option',{value:c.id},c.label));var b=h('input',{type:'checkbox',checked:cfg.skills.indexOf(c.id)>=0,onchange:edit});skills[c.id]=b;skillBox.append(h('label',{style:{display:'inline-block',margin:'5px 15px 5px 0'}},b,' '+c.label));});
        selected.value=cfg.selected;timing.value=cfg.timing;duration.value=cfg.duration_s;position.value=cfg.position;opacity.value=Math.round(cfg.opacity*100);size.value=cfg.size;all.checked=!cfg.corners.length;
        if(cfg.reference){option(reference,h,cfg.reference,cfg.reference.indexOf('pack:')===0?'Saved imported reference':cfg.reference);reference.value=cfg.reference;}
        Object.keys(sessions).forEach(function(k){sessions[k].checked=cfg.sessions.indexOf(k)>=0;});
      }
      var choices=s.reference_choices||[],signature=JSON.stringify(choices);
      if(reference.dataset.signature!==signature){var previous=reference.value;reference.dataset.signature=signature;reference.replaceChildren(h('option',{value:''},'Telemetry technique indicators (default)'));choices.forEach(function(r){option(reference,h,r.id,referenceLabel(r));});if(previous&&!choices.some(function(r){return r.id===previous;}))option(reference,h,previous,previous.indexOf('pack:')===0?'Saved imported reference':previous);reference.value=previous;}
      corners(s);preview.replaceChildren(h('b',null,s.corner||'Live skill preview'),h('p',{class:'hint'},s.reference||'Telemetry default'),metric(h,s.metric));
      if(!dirty)note.textContent=s.error||(s.reference_info&&s.reference_info.error)||(!s.enabled?'Skill overlay off. Configure and save to enable it.':s.reason==='ready'?'Overlay ready. AMS2 must be in front (borderless/windowed).':(s.reason||'Waiting').replace(/_/g,' '));
    }
    var skillBox=h('div'),sessionBox=h('div');
    [['practice','Practice'],['qualify','Qualifying'],['race','Race']].forEach(function(v){var b=h('input',{type:'checkbox',onchange:edit});sessions[v[0]]=b;sessionBox.append(h('label',{style:{marginRight:'15px'}},b,' '+v[1]));});
    [enabled,selected,timing,duration,position,opacity,size,all,reference].forEach(function(el){el.onchange=function(){edit();cornerBox.hidden=all.checked;};});
    form.append(h('label',null,enabled,' Show the skill overlay'),
      h('div',{class:'actions',style:{flexWrap:'wrap',margin:'12px 0'}},h('label',null,'Selected skill ',selected),h('button',{class:'btn ghost small',onclick:function(){cycle('previous');}},'Previous skill'),h('button',{class:'btn ghost small',onclick:function(){cycle('next');}},'Next skill')),
      h('details',null,h('summary',null,'Skills included when cycling'),skillBox),
      h('label',{style:{display:'block',maxWidth:'100%'}},'Coaching reference ',reference),
      packImport(ui,function(r){if(!alive)return;option(reference,h,r.id,'Imported • '+r.driver+' • '+r.car);reference.value=r.id;edit();}),
      h('p',{class:'hint'},'Choose a local recording or imported reference pack from the live car/layout. Paddock selects fast clean corners across laps, with technique-specific examples and linked corners considered together. Exact car first; same class is available. Imported figures are not independently verified. Green means matching the chosen comparison, not proven optimal driving. Without a reference, supported release/traction indicators give feedback; other skills show Target needed.'),
      h('div',{class:'actions',style:{flexWrap:'wrap',margin:'12px 0'}},h('label',null,'When ',timing),h('label',null,'Hold result (s) ',duration),h('label',null,'Position ',position),h('label',null,'Size ',size),h('label',null,'Opacity ',opacity)),
      h('div',null,h('label',null,all,' Every corner'),cornerBox),h('p',{class:'hint'},'Show in:'),sessionBox,
      h('button',{class:'btn',style:{margin:'12px 0'},onclick:function(){if(saving||!loaded)return;saving=true;
        var cfg={enabled:enabled.checked,selected:selected.value,skills:Object.keys(skills).filter(function(k){return skills[k].checked;}),corners:all.checked?[]:Object.keys(cornerChecks).filter(function(k){return cornerChecks[k].checked;}),timing:timing.value,duration_s:Number(duration.value),position:position.value,opacity:Number(opacity.value)/100,size:size.value,reference:reference.value,sessions:Object.keys(sessions).filter(function(k){return sessions[k].checked;})};
        if(!all.checked&&!cfg.corners.length){saving=false;return fail(new Error('Select a corner, or enable Every corner.'));}
        api('/api/skills/overlay','POST',cfg).then(function(s){dirty=false;paint(s);}).catch(fail).finally(function(){saving=false;});
      }},'Save skill overlay'),note);
    var element=h('details',{'data-skill-overlay':'true',open:true},h('summary',null,'Corner skill overlay'),
      h('p',{class:'hint'},'One skill at a time, every corner by default. A thin title, bar and axis-label strip appears after the exit. Details stay in Driving style. Independent of engineer speech and the garage checklist. Small controlled rotations are not scored as errors.'),form,preview,
      h('p',{class:'hint'},'Bind Previous skill, Next skill and Hide/show under Talk to the engineer. Inputs still reach AMS2; use unused wheel controls.'));
    function refresh(){if(alive&&!saving)api('/api/skills/overlay').then(paint).catch(fail);}
    refresh();var timer=setInterval(refresh,1200);
    return {element:element,close:function(){alive=false;clearInterval(timer);}};
  }
  function recorded(ui,data,driver,recording){
    var h=ui.h,api=ui.api,passes=data&&data.passes||[],catalog=data&&data.catalog||[],comparison=null;
    if(!passes.length)return h('section',{class:'panel pad'},h('h2',null,'Corner skills'),h('p',{class:'hint'},'No complete clean corner passes with safely attributed local inputs. One clean lap is sufficient.'));
    var skill=h('select',{'aria-label':'Recorded skill'},catalog.map(function(c){return h('option',{value:c.id},c.label);}));skill.value='steering';
    var lap=h('select',{'aria-label':'Skill lap'},h('option',{value:''},'Average of clean laps'));
    Array.from(new Set(passes.map(function(p){return p.lap;}))).sort(function(a,b){return a-b;}).forEach(function(n){lap.append(h('option',{value:String(n)},'Lap '+n));});
    var reference=h('select',{'aria-label':'Skill reference',style:{maxWidth:'100%',minWidth:'0'}},h('option',{value:''},'Telemetry only (default)'));
    var refNote=h('p',{class:'hint'},'Measurements are not optimality ratings. Exact-car references are preferred; same-class laps are optional comparisons.'),box=h('div');
    function draw(){
      box.replaceChildren();var names=Array.from(new Set(passes.map(function(p){return p.corner;})));
      names.forEach(function(c){
        var rows=passes.filter(function(p){return p.corner===c&&(!lap.value||p.lap===Number(lap.value));});
        if(!rows.length)return;var metrics=rows.map(function(p){return p.metrics[skill.value];}),valid=metrics.filter(function(m){return m&&m.value!=null;}),m=Object.assign({},valid.length?valid[valid.length-1]:metrics[metrics.length-1]);
        if(!lap.value&&valid.length){var values=valid.map(function(m){return m.value;});m.value=Math.round(values.reduce(function(a,b){return a+b;},0)/values.length*100)/100;m.scale=null;m.detail='Average of '+valid.length+' measured pass(es). Latest measured pass: '+m.detail;}
        var diffs=comparison&&comparison.differences.filter(function(p){return p.corner===c&&(!lap.value||p.lap===Number(lap.value));}).map(function(p){return p.metrics[skill.value];}).filter(Boolean)||[];
        var trace=comparison&&diffs.length&&(comparison.reference_traces||[]).find(function(t){return t.corner===c&&t.lap===diffs[0].reference_lap;});
        box.append(h('article',{style:{margin:'14px 0'}},h('h3',null,c),metric(h,m),diffs.length?h('p',{class:'hint'},'Reference'+(diffs[0].reference_lap!=null?' from lap '+diffs[0].reference_lap:'')+': '+diffs[0].reference_value+' '+diffs[0].unit+'. '+(lap.value?'Difference: '+(diffs[0].difference>0?'+':'')+diffs[0].difference+' '+diffs[0].unit+'.':'Select a lap for a direct difference.')):null,trace?tracePlot(h,trace):null));
      });
    }
    skill.onchange=draw;lap.onchange=draw;
    reference.onchange=function(){comparison=null;if(!reference.value){refNote.textContent='Telemetry only. No optimal target assumed.';return draw();}
      var wanted=reference.value;api('/api/skills/references?recording='+encodeURIComponent(recording)+'&reference='+encodeURIComponent(wanted)).then(function(r){if(reference.value!==wanted)return;comparison=r;refNote.textContent=r.driver+' • '+r.car+' • '+(r.reference_method==='corner_by_corner_per_skill'?'corner-specific targets':('reference lap '+r.reference_lap))+'. '+r.note+' '+(r.reference_verification||'');draw();}).catch(function(e){refNote.textContent=e.message||String(e);});
    };
    api('/api/skills/references?recording='+encodeURIComponent(recording)).then(function(r){(r.references||[]).forEach(function(x){option(reference,h,x.id,referenceLabel(x));});}).catch(function(){});
    draw();
    return h('section',{class:'panel pad','data-recorded-skills':'true'},h('h2',null,'Corner skills • '+(driver||'recording driver')),
      h('p',{class:'hint'},'Actual local steering, pedals and vehicle motion. Other cars do not export their pedal/steering traces. No AI or personal-best lap is assumed to be a professional target.'),
      h('details',null,h('summary',null,'Private reference packs'),h('p',{class:'hint'},'Export calculated corner statistics and selected 5 m input snippets for another Paddock installation. Full recordings and voice files remain on this PC. Automatic league synchronization is not configured.'),
        h('a',{class:'btn ghost small',href:'/api/skills/packs/export?recording='+encodeURIComponent(recording),download:'paddock-corner-reference.paddockref'},'Export reference pack'),
        packImport(ui,function(r){if(!box.isConnected)return;api('/api/skills/references?recording='+encodeURIComponent(recording)).then(function(data){var found=(data.references||[]).find(function(x){return x.id===r.id;});if(found){option(reference,h,r.id,referenceLabel(found));reference.value=r.id;reference.onchange();}else refNote.textContent='Imported into the private reference library. This car/layout does not match the current recording.';});})),
      h('div',{class:'actions',style:{flexWrap:'wrap'}},h('label',null,'Skill ',skill),h('label',null,'View ',lap),h('button',{class:'btn ghost small',onclick:function(){lap.selectedIndex=(lap.selectedIndex+1)%lap.options.length;draw();}},'Next lap'),h('label',null,'Compare ',reference)),refNote,box);
  }
  return {overlay:overlay,recorded:recorded,metric:metric};
}());
