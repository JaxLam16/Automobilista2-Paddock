/* Private coach controls. Calls are spoken by Paddock itself (standalone) or through Crew Chief. */
window.PaddockCoach = function (ui) {
  'use strict';
  var h=ui.h, api=ui.api, alive=true, busy=false, known=false, status={}, loaded=false, lastEvents='',pendingSpeech=null,pendingUnits=null,epoch=0;
  var chosenVoice=null, lastVoiceOptions='';
  var note=h('p',{class:'hint',role:'status','aria-live':'polite'},'Loading private race coach…');
  var error=h('p',{class:'hint',role:'alert'});
  var speech=h('input',{type:'checkbox','aria-label':'Speak the calls'});
  var tts=h('input',{type:'checkbox','aria-label':'Read calls without a voice clip with text-to-speech'});
  var output=h('select',{'aria-label':'Who speaks the calls'},
    [['paddock','Paddock (standalone)'],['crew_chief','Crew Chief']].map(function(x){return h('option',{value:x[0]},x[1]);}));
  var volume=h('input',{type:'range',min:0,max:100,step:5,'aria-label':'Radio volume',style:{verticalAlign:'middle',maxWidth:'160px'}});
  var windowsVoice=h('select',{'aria-label':'Windows speech voice',style:{maxWidth:'100%'}});
  var spotterBox=h('input',{type:'checkbox','aria-label':'Paddock spotter'});
  spotterBox.onchange=function(){saveSetting({spotter:spotterBox.checked});};
  var baselineVoice=h('select',{'aria-label':'Crew Chief baseline voice'},
    [['paddock','Selected Paddock voice'],['original','Original Crew Chief recordings']].map(function(x){return h('option',{value:x[0]},x[1]);}));
  baselineVoice.onchange=function(){saveSetting({baseline_voice:baselineVoice.value});};
  var baselineHint=h('p',{class:'hint',role:'status'});
  var callsDraft=null,callsRevision=-1,callsDirty=false,callsRendered='';
  var callsNote=h('p',{class:'hint',role:'status','aria-live':'polite'});
  var callsBody=h('div'),callsSave=h('button',{type:'button',class:'btn small'},'Save call preferences');
  var callsRestore=h('button',{type:'button',class:'btn ghost small'},'Restore imported rules');
  var callsLess=h('button',{type:'button',class:'btn ghost small'},'Less chatter preset');
  var callsDiscard=h('button',{type:'button',class:'btn ghost small'},'Discard edits');
  function editCalls(){callsDirty=true;updateCallButtons();}
  function updateCallButtons(){
    callsBody.inert=busy;
    callsSave.disabled=busy||!callsDirty;callsDiscard.disabled=busy||!callsDirty;
    callsRestore.disabled=busy||!known;callsLess.disabled=busy||!known;
  }
  function saveCalls(preset){
    var body={revision:callsRevision};
    if(preset)body.preset=preset;else body.overrides=callsDraft;
    epoch++;busy=true;updateCallButtons();error.textContent='';
    api('/api/coach/calls','POST',body).then(function(value){
      if(alive){status=value;callsDirty=false;callsRendered='';update();}
    }).catch(function(e){if(alive)error.textContent=e.message||String(e);})
      .finally(function(){busy=false;if(alive){update();refresh();}});
  }
  callsSave.onclick=function(){saveCalls();};
  callsRestore.onclick=function(){saveCalls('inherit');};
  callsLess.onclick=function(){saveCalls('less_chatter');};
  callsDiscard.onclick=function(){callsDirty=false;callsRendered='';update();};
  var callsPanel=h('details',{'data-call-controls':'true'},h('summary',null,'Automatic calls & frequency'),
    h('p',{class:'hint'},'Choose Paddock’s automatic reports here. Requested answers and recon laps remain available; the spotter has its own switch in radio settings. Changes apply the next time you Stop and Start the live coach. Your recorder keeps running. A separate Crew Chief application keeps its own preferences.'),
    callsNote,h('div',{class:'actions',style:{flexWrap:'wrap'}},callsSave,callsDiscard,callsLess,callsRestore),callsBody);
  function updateCalls(){
    var config=status.call_controls;if(!config)return;
    callsNote.textContent=config.error||(callsDirty?'Unsaved edits. Save to stage these for the next coach start.':
      config.pending?'Saved — pending next coach Stop/Start. Current calls keep their existing settings.':
      status.running?'Saved call preferences are active.':'Saved preferences will apply when the live coach starts.');
    if(config.managed_by_original&&Object.keys(config.managed_by_original).length)callsNote.textContent+=' Lap-time and tyre baseline reports use the original controls above; overlapping Paddock reports are disabled in standalone mode.';
    if(callsDirty&&config.revision!==callsRevision)callsNote.textContent+=' Preferences changed in another page. Discard edits to reload before saving.';
    var signature=String(config.revision)+'/'+String(!!status.running)+'/'+String(!!config.pending)+'/'+JSON.stringify(config.managed_by_original||{});
    if(!callsDirty&&callsRendered!==signature){
      var openGroups=new Set(Array.from(callsBody.querySelectorAll('details[open]')).map(function(el){
        return el.getAttribute('data-call-family')||el.getAttribute('data-paddock-call')||'paddock';
      }));
      callsRevision=config.revision;callsDraft=JSON.parse(JSON.stringify(config.saved));callsRendered=signature;
      callsBody.replaceChildren();
      function automatic(group,key,label){
        var options=callsDraft[group][key]||{},check=h('input',{type:'checkbox','aria-label':label+' automatic calls'});
        check.checked=options.enabled!==false;
        var interval=h('input',{type:'number',min:0,max:3600,step:1,value:options.min_interval_s||0,
          'aria-label':label+' minimum interval',style:{width:'6em',maxWidth:'100%'}});
        function changed(){callsDraft[group][key]={enabled:check.checked,min_interval_s:Number(interval.value)};editCalls();}
        check.onchange=changed;interval.onchange=changed;
        return h('div',{class:'actions',style:{flexWrap:'wrap',margin:'8px 0'}},h('label',null,check,' Automatic calls'),h('label',null,'Extra minimum spacing (s) ',interval));
      }
      function original(field){
        var inherited=field.type==='boolean'?(field.imported?'On':'Off'):String(field.imported);
        var select=h('select',{'aria-label':field.label,style:{maxWidth:'100%'}},h('option',{value:''},'Imported: '+inherited));
        if(field.type==='boolean'){
          select.append(h('option',{value:'true'},'On'),h('option',{value:'false'},'Off'));
        }else if(field.max===10){
          for(var i=field.min;i<=field.max;i++)select.append(h('option',{value:String(i)},String(i)));
        }else{
          select=h('input',{type:'number',min:field.min,max:field.max,step:1,placeholder:'Imported: '+inherited,
            'aria-label':field.label,style:{width:'12em',maxWidth:'100%'}});
        }
        var saved=callsDraft.native[field.key];select.value=saved===undefined?'':String(saved);
        select.onchange=function(){
          if(select.value==='')delete callsDraft.native[field.key];
          else callsDraft.native[field.key]=field.type==='boolean'?select.value==='true':Number(select.value);
          editCalls();
        };
        return h('label',{style:{display:'flex',gap:'8px',flexWrap:'wrap',alignItems:'center',margin:'6px 0'}},field.label+' ',select,
          h('span',{class:'hint'},status.running?'Active: '+(field.type==='boolean'?(field.active?'On':'Off'):field.active):'Imported rule: '+inherited));
      }
      (config.families||[]).forEach(function(family){
        var fields=(config.native||[]).filter(function(f){return f.family===family.id;});
        var detail=h('details',{'data-call-family':family.id},h('summary',null,family.label),automatic('families',family.id,family.label));
        detail.open=openGroups.has(family.id);
        if(family.primary_setting){
          var primary=fields.find(function(f){return f.key===family.primary_setting;});
          if(primary&&primary.imported===false&&callsDraft.native[primary.key]!==true)
            detail.append(h('p',{class:'hint'},'The imported original switch is off. Enable it below to allow those original updates.'));
        }
        fields.forEach(function(field){detail.append(original(field));});callsBody.append(detail);
      });
      var extra=h('details',null,h('summary',null,'Individual Paddock reports'));
      extra.open=openGroups.has('paddock');
      (config.paddock||[]).forEach(function(rule){
        var row=h('details',{'data-paddock-call':rule.id},h('summary',null,rule.label),automatic('paddock',rule.id,rule.label));
        row.open=openGroups.has(rule.id);extra.append(row);
      });
      callsBody.append(extra,h('p',{class:'hint'},'Original frequency values use Crew Chief’s 0–10 scale where available. Extra minimum spacing only reduces chatter; 0 adds no restriction. Original evidence, cooldowns and safe speaking windows still apply. Muting a family also mutes its automatic warnings. Manual responses still require valid telemetry.'));
    }
    updateCallButtons();
  }
  var fuelMultiplier=h('input',{type:'number',min:0,max:10,step:1,'aria-label':'AMS2 fuel use multiplier',style:{maxWidth:'7em'}});
  fuelMultiplier.onchange=function(){saveSetting({fuel_multiplier:Number(fuelMultiplier.value)});};
  var radioEffect=h('select',{'aria-label':'Radio effect'},[['full','Full pit-wall radio'],['light','Light radio'],['off','Clean (clicks only)']].map(function(x){return h('option',{value:x[0]},x[1]);}));
  var outputHint=h('p',{class:'hint'});
  var voiceStatus=h('p',{class:'hint',role:'status'});
  var coverage=h('p',{class:'hint warnline',role:'note'});
  var readiness=h('div',{'aria-label':'Coach readiness',class:'panel pad',role:'status'});
  var driver=h('span',{class:'muted'});
  var mode=h('select',{'aria-label':'Coach talk mode'},
    [['full','Full'],['race','Race only'],['quiet','Quiet'],['coach','Coach'],['silent','Safety only']].map(function (x) {
      return h('option',{value:x[0]},x[1]);
    }));
  var actions=[];
  function action(label,path,body) {
    var button=h('button',{class:'btn ghost small',onclick:function () {
      if(busy||!known) return;
      busy=true;epoch++; update(); error.textContent='';
      return api(path,'POST',typeof body==='function'?body():body||{}).then(function (value) {
        if(alive) { status=value; update(); }
      }).catch(function (e) { if(alive) error.textContent=e.message||String(e); })
        .finally(function () { busy=false; if(alive) refresh(); });
    }},label);
    actions.push(button);return button;
  }
  var start=action('Start live coach preview','/api/coach/start',function () {return {driver:status.current&&status.current.driver};});
  var stop=action('Stop live coach preview','/api/coach/stop');
  var quiet=action('Quiet for three laps','/api/coach/quiet',{laps:3});
  function engineerButton(label,path){
    var b=h('button',{class:'btn ghost small',onclick:function(){
      if(busy||!known)return;busy=true;epoch++;update();error.textContent='';
      api(path,'POST',{}).catch(function(e){if(alive)error.textContent=e.message||String(e);})
        .finally(function(){busy=false;if(alive)refresh();});
    }},label);
    actions.push(b);return b;
  }
  var engineerStart=engineerButton('Start live engineering','/api/engineer/live/start');
  var engineerStop=engineerButton('Stop live engineering','/api/engineer/live/stop');
  var bothStart=h('button',{class:'btn small',onclick:function(){
    if(busy||!known)return;busy=true;epoch++;update();error.textContent='';
    var steps=[];
    if(!status.running)steps.push(function(){return api('/api/coach/start','POST',{driver:status.current&&status.current.driver});});
    if(!(status.engineer&&status.engineer.running))steps.push(function(){return api('/api/engineer/live/start','POST',{});});
    steps.reduce(function(chain,step){return chain.then(step);},Promise.resolve())
      .catch(function(e){if(alive)error.textContent=e.message||String(e);})
      .finally(function(){busy=false;if(alive)refresh();});
  }},'Start coach and engineering');
  actions.push(bothStart);
  var engineerState=h('span',{class:'muted',role:'status','aria-live':'polite'});
  var setupLink=h('a',{class:'btn ghost small',href:'#/engineer'},'Open active setup session');
  var topBar=h('div',{class:'actions',style:{flexWrap:'wrap',alignItems:'center',margin:'4px 0 10px'},'aria-label':'Live coach and engineering'},
    bothStart,start,stop,engineerStart,engineerStop,engineerState,setupLink);
  /* Talking to the engineer: a wheel button for push-to-talk and optional direct answers. */
  var talkRows=h('div');
  var talkNote=h('p',{class:'hint',role:'status','aria-live':'polite'});
  var talkPanel=h('details',null,h('summary',null,'Talk to the engineer (wheel buttons)'),
    h('p',{class:'hint'},'Hold your radio button, wait for the ready click, then say, for example, \u201cconfirm\u201d, \u201cthis is practice two\u201d, \u201cwhat\u2019s the plan\u201d or \u201crecon lap\u201d. Windows speech recognition listens only while the button is held. Tyre/brake status queries are recognised; their original Crew Chief replies are still being restored. The other buttons answer directly. Press Set, then the button on your wheel.'),
    talkRows,talkNote);
  var talkLabels={ptt:'Radio button (hold to talk)',confirm:'Confirm',negative:'No',plan:'Repeat the plan',progress:'Objective progress',debrief:'Debrief',recon:'Recon lap',overlay_previous:'Garage menu: left',overlay_next:'Garage menu: right',overlay_up:'Garage menu: up',overlay_down:'Garage menu: down',overlay_confirm:'Garage menu: confirm',overlay_toggle:'Garage overlay: hide / show (optional legacy button)',skill_previous:'Skill overlay: previous skill',skill_next:'Skill overlay: next skill',skill_toggle:'Skill overlay: hide / show'};
  var talkSignature='';
  var overlayEnabled=h('input',{type:'checkbox','aria-label':'Practice garage overlay'});
  var overlayPosition=h('select',{'aria-label':'Garage overlay position'},h('option',{value:'right'},'Top right'),h('option',{value:'left'},'Top left'));
  var overlayNote=h('p',{class:'hint',role:'status'}),overlayCard=h('div',{class:'panel pad'});
  var overlayMenu=h('div',{'aria-label':'Garage action menu',role:'group'});
  var overlayMenuButtons=['up','down','confirm'].map(function(a){return h('button',{class:'btn ghost small',onclick:function(){overlayRequest('/api/coach/overlay/action',{action:a});}},a==='up'?'Menu up':a==='down'?'Menu down':'Confirm selected action');});
  function overlayRequest(path,body){return api(path,'POST',body).then(function(v){if(alive){status.overlay=v;update();}}).catch(function(e){if(alive)error.textContent=e.message||String(e);});}
  overlayEnabled.onchange=function(){overlayRequest('/api/coach/overlay',{enabled:overlayEnabled.checked});};
  overlayPosition.onchange=function(){overlayRequest('/api/coach/overlay',{position:overlayPosition.value});};
  var overlayActions=['previous','next','toggle'].map(function(a){return h('button',{class:'btn ghost small',onclick:function(){overlayRequest('/api/coach/overlay/action',{action:a});}},a==='previous'?'Previous instruction':a==='next'?'Next instruction':'Hide / show checklist');});
  var overlayPanel=h('details',{open:true},h('summary',null,'Practice garage checklist'),
    h('label',{},overlayEnabled,' Show the garage overlay'),h('label',{style:{marginLeft:'12px'}},'Position ',overlayPosition),
    h('p',{class:'hint'},'The overlay opens automatically in the stationary practice garage while enabled (AMS2 borderless/windowed). Left/right browses; up/down chooses an action; confirm selects it. Make the change in AMS2 before selecting Applied. Each choice saves immediately; finish with Submit to engineer on the review card. R&D cards appear only for confirmed Practice 2 and review goals. Bind five wheel buttons or hat directions under Talk to the engineer. Use controls not assigned in AMS2, since inputs still reach the game.'),
    overlayNote,overlayCard,overlayMenu,h('div',{class:'actions',style:{flexWrap:'wrap'}},overlayActions,overlayMenuButtons));
  /* Spoken identities are independent of the game's names and raw recordings. */
  var nameQuery=new URLSearchParams((location.hash.split('?')[1]||''));
  var personal=h('input',{type:'text',list:'paddock-personal-names',maxLength:80,
    placeholder:'e.g. Jacks','aria-label':'Personal radio name',style:{maxWidth:'220px'}});
  var nameOptions=h('datalist',{id:'paddock-personal-names'});
  var nameNote=h('p',{class:'hint',role:'status','aria-live':'polite'});
  var nameChamp=h('select',{'aria-label':'Championship for race names',style:{maxWidth:'100%'}},h('option',{value:''},'Choose championship'));
  var nameQuali=h('select',{'aria-label':'Qualifying for race names',style:{maxWidth:'100%'}},h('option',{value:''},'Choose qualifying'));
  var nameRows=h('div'),nameReview=null,nameEpoch=0,nameSelects={};
  function nameError(e){if(alive)nameNote.textContent=e.message||String(e);}
  var savePersonal=h('button',{class:'btn ghost small',onclick:function(){
    api('/api/coach/names/personal','POST',{name:personal.value.trim(),revision:(status.radio_names||{}).revision||''})
      .then(function(value){if(alive){
        status.radio_names=value;if(nameReview)nameReview.revision=value.revision;
        nameNote.textContent='Personal call name saved.';refresh();
      }}).catch(nameError);
  }},'Save call name');
  function loadNames(){
    var generation=++nameEpoch;
    nameReview=null;nameRows.replaceChildren();nameSelects={};
    if(!nameChamp.value||!nameQuali.value)return;
    nameNote.textContent='Loading qualifying entrants…';
    api('/api/coach/names/qualifying?recording='+encodeURIComponent(nameQuali.value)+'&champ='+encodeURIComponent(nameChamp.value))
      .then(function(value){
        if(!alive||generation!==nameEpoch)return;
        nameReview=value;
        value.entrants.forEach(function(p){
          var select=h('select',{'aria-label':'Race name for '+p.name,style:{maxWidth:'100%',minWidth:'0'}},
            h('option',{value:''},p.name+' (AMS2 name)'));
          value.drivers.forEach(function(d){select.appendChild(h('option',{value:d.key},
            (d.display||d.key)+' · '+(d.role==='ai'?'AI':'human')));});
          select.value=value.assignments[p.id]||'';nameSelects[p.id]=select;
          var picture=h('img',{alt:'',style:{width:'100px',height:'48px',objectFit:'contain'},onerror:function(e){e.target.hidden=true;}});
          function paint(){var d=value.drivers.find(function(x){return x.key===select.value;}),l=d&&d.livery;
            picture.hidden=!l;
            if(l)picture.src=l.preview?'data:image/png;base64,'+l.preview:
              '/api/liveries/image?car='+encodeURIComponent(l.car_id)+'&livery='+encodeURIComponent(l.livery_id);
          }
          select.onchange=paint;paint();
          nameRows.appendChild(h('div',{style:{display:'flex',gap:'12px',alignItems:'center',flexWrap:'wrap',padding:'8px 0',borderBottom:'1px solid var(--border)'}},
            h('div',{style:{flex:'1 1 240px',minWidth:'0'}},h('b',null,'P'+p.position+' · '+p.name),
              h('div',{class:'hint'},p.car+(p.best_lap?' · '+p.best_lap.toFixed(3)+' s':''))),picture,select));
        });
        nameNote.textContent='Choose championship drivers, including your friends. Empty entries keep AMS2 names. Save before the race starts.';
      }).catch(nameError);
  }
  nameChamp.onchange=loadNames;nameQuali.onchange=loadNames;
  var saveNames=h('button',{class:'btn small',onclick:function(){
    if(!nameReview)return;
    var assignments={};Object.keys(nameSelects).forEach(function(id){assignments[id]=nameSelects[id].value;});
    api('/api/coach/names/qualifying','POST',{recording:nameReview.recording,champ:nameReview.champ,
      assignments:assignments,revision:nameReview.revision}).then(function(value){
        if(alive){status.radio_names=value;nameReview.revision=value.revision;nameReview.assignments=assignments;
          nameNote.textContent='Race names saved. Matching entrants will use these names in live calls.';refresh();}
      }).catch(nameError);
  }},'Save names for the race');
  var clearNames=h('button',{class:'btn ghost small',onclick:function(){
    api('/api/coach/names/clear','POST',{revision:(status.radio_names||{}).revision||''}).then(function(value){
      if(alive){status.radio_names=value;if(nameReview){nameReview.revision=value.revision;nameReview.assignments={};}
        Object.keys(nameSelects).forEach(function(id){nameSelects[id].value='';});
        nameNote.textContent='Live race names cleared; AMS2 names will be used.';refresh();}
    }).catch(nameError);
  }},'Use AMS2 names');
  var namesPanel=h('details',null,h('summary',null,'Driver names and qualifying assignments'),
    h('p',{class:'hint'},'Choose your personal call name from the installed Crew Chief catalogue. It is used in greetings and encouragement; spotter warnings stay short.'),
    h('div',{class:'actions',style:{flexWrap:'wrap'}},h('label',null,'Call me ',personal),nameOptions,savePersonal),
    h('p',{class:'hint'},'After qualifying, assign championship drivers for the upcoming race. Matches require the same track, layout, car model and recorded entrant name. Changed or unknown entrants keep their AMS2 names. This assignment expires after four hours and is limited to one live race session.'),
    h('div',{class:'actions',style:{flexWrap:'wrap'}},nameChamp,nameQuali),nameNote,nameRows,
    h('div',{class:'actions'},saveNames,clearNames));
  Promise.all([api('/api/coach/names/catalogue'),api('/api/championships'),api('/api/recordings')]).then(function(values){
    if(!alive)return;
    var cat=values[0];personal.value=cat.personal||'';
    (cat.personal_names||[]).forEach(function(n){nameOptions.appendChild(h('option',{value:n}));});
    (values[1].championships||[]).forEach(function(c){nameChamp.appendChild(h('option',{value:c.id},c.name));});
    var qualis=(values[2].recordings||[]).filter(function(r){return r.type==='qualify'&&r.status==='complete';})
      .sort(function(a,b){return String(b.started_at).localeCompare(String(a.started_at));});
    qualis.forEach(function(r){nameQuali.appendChild(h('option',{value:r.id},(r.track||'Track')+' · '+String(r.started_at||r.id)));});
    nameChamp.value=nameQuery.get('champ')||(cat.lineup||{}).champ||'';
    nameQuali.value=nameQuery.get('qualifying')||(cat.lineup||{}).recording||(qualis[0]||{}).id||'';
    nameNote.textContent=(cat.personal_names||[]).length+' personal names · '+(cat.drivers||[]).length+' opponent-name recordings available locally.';
    loadNames();
    if(nameQuery.get('qualifying'))namesPanel.scrollIntoView({block:'start'});
  }).catch(nameError);
  mode.onchange=function () { epoch++;api('/api/coach/settings','POST',{mode:mode.value}).then(function (value) {
    if(alive){status=value;update();}
  }).catch(function(e){if(alive)error.textContent=e.message||String(e);}); };
  speech.onchange=function () { var enabled=speech.checked;pendingSpeech=enabled;epoch++;busy=true;update();api('/api/coach/settings','POST',{audio_enabled:enabled}).then(function(value) {
    if(alive){status=value;update();}
  }).catch(function(e){if(alive){error.textContent=e.message||String(e);speech.checked=!!status.audio_enabled;}})
    .finally(function(){pendingSpeech=null;busy=false;if(alive){update();refresh();}}); };
  tts.onchange=function () { var enabled=tts.checked;epoch++;busy=true;update();api('/api/coach/settings','POST',{tts_fallback:enabled}).then(function(value) {
    if(alive){status=value;update();}
  }).catch(function(e){if(alive){error.textContent=e.message||String(e);tts.checked=status.tts_fallback!==false;}})
    .finally(function(){busy=false;if(alive){update();refresh();}}); };
  function saveSetting(values){
    epoch++;busy=true;update();error.textContent='';
    api('/api/coach/settings','POST',values).then(function(value){if(alive){status=value;update();}})
      .catch(function(e){if(alive)error.textContent=e.message||String(e);})
      .finally(function(){busy=false;if(alive){update();refresh();}});
  }
  output.onchange=function(){saveSetting({output:output.value});};
  volume.onchange=function(){saveSetting({volume:Number(volume.value)/100});};
  radioEffect.onchange=function(){saveSetting({radio_effect:radioEffect.value});};
  windowsVoice.onchange=function(){saveSetting({windows_voice:windowsVoice.value||null});};
  var reloadVoice=action('Reload voice clips','/api/coach/settings',{reload_voice:true});
  var voiceChoice=h('select',{'aria-label':'Engineer voice',style:{maxWidth:'100%',minWidth:'0'},onchange:function(){chosenVoice=voiceChoice.value;update();}});
  var chooseVoice=action('Use selected voice','/api/coach/voice/select',function(){return {key:voiceChoice.value};});
  var cancelVoice=action('Cancel voice download','/api/coach/voice/cancel');
  var packProgress=h('progress',{'aria-label':'Voice download progress',max:1,value:0,style:{maxWidth:'100%'}});
  var packNote=h('p',{class:'hint',role:'status','aria-live':'polite'});
  var packControls=h('div',null,h('div',{class:'actions',style:{flexWrap:'wrap',minWidth:'0'}},
    h('label',{style:{minWidth:'0',maxWidth:'100%'}},'Engineer voice ',voiceChoice),chooseVoice,cancelVoice),packProgress);
  var unitFields={},unitLabels={distance:'Distance',pressure:'Pressure',temperature:'Temperature',fuel:'Fuel'};
  var unitOptions={distance:[['m','Metres'],['ft','Feet']],pressure:[['bar','bar'],['psi','psi']],
    temperature:[['c','Celsius'],['f','Fahrenheit']],fuel:[['litres','Litres'],['us_gallons','US gallons'],['laps','Laps']]};
  var unitExamples=h('p',{class:'hint'});
  function saveUnits() {
    if(busy)return;
    var values={};Object.keys(unitFields).forEach(function(key){values[key]=unitFields[key].value;});
    epoch++;busy=true;pendingUnits=values;update();error.textContent='';
    api('/api/coach/settings','POST',{units:values}).then(function(value){if(alive){status=value;update();}})
      .catch(function(e){if(alive)error.textContent=e.message||String(e);})
      .finally(function(){busy=false;pendingUnits=null;if(alive){update();refresh();}});
  }
  var unitsPanel=h('details',null,h('summary',null,'Coach units'),
    h('div',{class:'actions',style:{flexWrap:'wrap'}},Object.keys(unitOptions).map(function(key){
      var select=h('select',{'aria-label':'Coach '+key+' units',onchange:saveUnits},unitOptions[key].map(function(option){return h('option',{value:option[0]},option[1]);}));
      unitFields[key]=select;return h('label',null,unitLabels[key]+' ',select);
    })),unitExamples);
  var fuelReadout=h('p',{class:'hint',role:'status','aria-label':'Fuel measurement'});
  var fuelPanel=h('details',null,h('summary',null,'Measured fuel use'),fuelReadout,
    h('p',{class:'hint'},'Uses three full clean laps. The estimated range uses recent observed consumption, with no reserve or guarantee. Race-finish fuel targets and pit recommendations are still being built.'));
  var raceReadout=h('p',{class:'hint',role:'status','aria-label':'Race length measurement'});
  var racePanel=h('details',null,h('summary',null,'Race length'),raceReadout,
    h('p',{class:'hint'},'Timed estimates use three observed overall-leader laps and known extra laps. They describe the leader’s flag lap; your own finish depends on where you are when the leader finishes. Fuel-to-finish planning is still being built.'));
  var apexReadout=h('p',{class:'hint',role:'status','aria-label':'Mapped apex measurement'});
  var apexPanel=h('details',null,h('summary',null,'Mapped apex feedback'),apexReadout,
    h('p',{class:'hint'},'Practice only. Compares repeated wider, slower passes with your earlier clean laps at a mapped apex. Requires a matching layout and mapped edges; traffic and invalid laps are excluded.'));
  var speedReadout=h('p',{class:'hint',role:'status','aria-label':'Corner speed measurement'});
  var speedPanel=h('details',null,h('summary',null,'Practice corner speed'),speedReadout,
    h('p',{class:'hint'},'Learns bends from earlier clean speed and steering traces. Unlabelled bends are identified by distance. Reports repeated lower minimum speed with a slower section; it does not infer the cause or tell you to push harder.'));
  var brakeReadout=h('p',{class:'hint',role:'status','aria-label':'Brake input measurement'});
  var brakePanel=h('details',null,h('summary',null,'Practice brake inputs'),brakeReadout,
    h('p',{class:'hint'},'Checks for a sustained brake application at least 8 metres earlier on two of the last three clean intervals, allowing for sample spacing, with lower speed at the same entry point and a slower section. Tiny taps, multiple applications and inconsistent references are withheld. This measures pedal input; it does not establish the cause or recommend braking later.'));
  var sectionReadout=h('p',{class:'hint',role:'status','aria-label':'Section loss measurement'});
  var sectionPanel=h('details',null,h('summary',null,'Biggest section loss'),sectionReadout,
    h('p',{class:'hint'},'Splits each lap halfway between the bends learned from your earlier clean laps. Names the section that is at least 0.15 s slower on two of your last three clean laps, including the latest, when at least two sections were measured. It adds at most one measured fact (earlier braking, lower or higher minimum speed, lower exit speed). It does not infer the cause or tell you what to change.'));
  var wideReadout=h('p',{class:'hint',role:'status','aria-label':'Running wide measurement'});
  var widePanel=h('details',null,h('summary',null,'Running wide'),wideReadout,
    h('p',{class:'hint'},'Uses the game\u2019s own off-track state. Only the game\u2019s lap-invalid flag counts as track limits, so a lap it still counts stays clean. Warns when you run wide at the same spot on two of your last three laps and the lap is still valid a second later. It cannot tell how close the limit is, and stays quiet after impacts, spins or a deleted lap.'));
  var recordings=h('select',{'aria-label':'Recording for coach replay',style:{maxWidth:'100%',minWidth:'0'}},h('option',{value:''},'Choose a completed recording'));
  var replayDriver=h('input',{type:'text',maxLength:64,'aria-label':'Replay driver',placeholder:'Recording driver (default)',style:{maxWidth:'220px'}});
  var speed=h('select',{'aria-label':'Coach replay speed'},[0,1,5,10,20].map(function (n) {
    return h('option',{value:n},n===0?'As fast as possible':n+'× speed');
  }));
  var replay=action('Analyse coach replay','/api/coach/replay',function () {
    return {recording:recordings.value,driver:replayDriver.value||undefined,speed:Number(speed.value)};
  });
  var replayStop=action('Stop replay','/api/coach/replay/stop');
  var replayNote=h('p',{class:'hint',role:'status','aria-live':'polite'});
  var review=h('a',{class:'btn ghost small',target:'_blank',rel:'noopener'},'Open replay decisions');
  review.hidden=true;
  var transcript=h('div',{style:{maxHeight:'370px',overflow:'auto'}});
  /* Practice plan: session goal, typed replies, R&D objectives, briefs and debriefs (coach/program.py). */
  var planGoal=h('p',{role:'status','aria-live':'polite'});
  var planNote=h('p',{class:'hint'});
  var goalButtons=[['practice1','Practice 1: setup & learning'],['practice2','Practice 2: R&D objectives'],['free','Free practice']].map(function(g){
    return h('button',{class:'btn ghost small',type:'button',onclick:function(){
      if(busy)return;busy=true;epoch++;update();error.textContent='';
      api('/api/coach/goal','POST',{goal:g[0]}).then(function(value){if(alive){status=value;update();}})
        .catch(function(e){if(alive)error.textContent=e.message||String(e);})
        .finally(function(){busy=false;if(alive){update();refresh();}});
    }},g[1]);
  });
  var sayInput=h('input',{type:'text',maxLength:200,'aria-label':'Tell the engineer',placeholder:'e.g. No, this is practice session 2',style:{flex:'1 1 220px',minWidth:'0',maxWidth:'100%'}});
  var sayResult=h('p',{class:'hint',role:'status','aria-live':'polite'});
  function sendReply(){
    var text=sayInput.value.trim();
    if(!text||busy)return;
    busy=true;epoch++;update();error.textContent='';
    api('/api/coach/say','POST',{text:text}).then(function(value){
      if(!alive)return;
      sayResult.textContent='Understood: '+value.reply.understood+'. '+value.reply.response;
      sayInput.value='';status=value;update();
    }).catch(function(e){if(alive)sayResult.textContent=e.message||String(e);})
      .finally(function(){busy=false;if(alive){update();refresh();}});
  }
  var sayButton=h('button',{class:'btn small',type:'button',onclick:sendReply},'Send');
  sayInput.onkeydown=function(e){if(e.key==='Enter'){e.preventDefault();sendReply();}};
  var objectiveList=h('div',{'aria-label':'R&D objective progress'});
  var planLines=h('div',{'aria-label':'Recent briefs and debriefs'});
  var planPanel=h('section',{class:'panel pad','aria-label':'Practice plan',style:{minWidth:'0',overflowWrap:'anywhere',margin:'12px 0'}},
    h('b',null,'Practice plan'),planGoal,
    h('div',{class:'actions',style:{flexWrap:'wrap'}},goalButtons),
    h('label',{style:{display:'block',marginTop:'8px'}},'Tell the engineer'),
    h('div',{class:'actions',style:{flexWrap:'wrap',minWidth:'0'}},sayInput,sayButton),sayResult,
    objectiveList,planNote,
    h('details',null,h('summary',null,'Recent briefs and debriefs'),planLines));
  var skillOverlay=window.PaddockSkills?window.PaddockSkills.overlay(ui):null;
  var element=h('section',{class:'panel pad eng-coach',style:{minWidth:'0',overflowWrap:'anywhere'}},
    h('h2',null,'Live engineer & garage'),
    h('p',{class:'hint'},'Start coaching and setup tracking together, or control them individually. Your garage checklist uses the same saved setup session.'),
    topBar,h('p',{class:'hint warnline'},'Crew Chief baseline restoration is in progress. The original spotter is connected; full engineer coverage and Crew Chief voice commands are still being restored.'),
    h('div',{class:'actions',style:{marginTop:'12px',flexWrap:'wrap'}},h('label',null,speech,' Speak the calls'),quiet,h('label',null,'Talk mode ',mode)),
    note,driver,error,callsPanel,planPanel,overlayPanel,skillOverlay?skillOverlay.element:null,
    h('details',null,h('summary',null,'Speech readiness and baseline coverage'),coverage,readiness),namesPanel,talkPanel,
    h('details',null,h('summary',null,'Engineer voice and radio settings'),
      h('div',{class:'actions',style:{flexWrap:'wrap',minWidth:'0'}},
        h('label',null,'Spoken by ',output),h('label',null,'Volume ',volume),h('label',null,'Radio ',radioEffect)),outputHint,
      h('label',{style:{display:'block'}},spotterBox,' Original Crew Chief 4.19.5.4 spotter (disable the external spotter if both apps are running)'),
      h('label',{},'Baseline call voice ',baselineVoice),baselineHint,
      h('label',{},'AMS2 fuel use multiplier ',fuelMultiplier),
      h('p',{class:'hint'},'Match the fuel-use multiplier in AMS2: 0 disables fuel calls. AMS2 does not report this setting. The default is 1; change it with the live coach stopped.'),
      h('p',{class:'hint'},'Ask “what’s my fuel level”, “what’s my fuel usage”, “how’s my fuel”, “how much fuel to the end”, “calculate fuel for five laps”, “how long’s left” or “what lap am I on”. Consumption and race-finish estimates need measured history. Pit-exit traffic strategy is still in development.'),
      h('p',{class:'hint'},'Original pit-stop calls use observed requests, crew readiness, stall occupancy and mandatory-stop windows. Ask “is my pit box occupied” or “do I have a mandatory pit stop”. Unavailable pit speed, box coordinates and since-pit history return “no data”.'),
      h('p',{class:'hint'},'Ask “what’s my position” for your class position. Start feedback uses the observed grid, and pass calls wait for a completed pass. AMS2 does not provide the ratings needed for an expected-finish prediction; that question returns “no data”.'),
      h('p',{class:'hint'},'Original engine temperature monitoring starts after two minutes. Ask “what are my engine temps”, “whats my oil temp”, “whats my water temp” or “how are my engine temps” using push-to-talk or a typed radio request.'),
      h('p',{class:'hint'},'Original penalty calls include drive-through and stop-go reminders. Ask “do I have a penalty”, “do I still have a penalty” or “have I served my penalty”. Missing telemetry or uncertain history is withheld.'),
      h('p',{class:'hint'},'Original Crew Chief weather and engine events use the shared AMS2 telemetry state, including stalled-engine checks. Ask “what’s the air temperature”, “what’s the track temperature”, or “what are my engine temperatures”. Engine heat warnings retain the original two-minute warm-up and averaging. Brake bias currently returns “no data” in the AMS2 baseline.'),
      h('p',{class:'hint'},'Say “keep quiet” to pause automatic engineer updates, “keep me informed” to resume them, or “say again” to repeat the last call that began speaking. Spotter warnings remain available.'),
        h('p',{class:'hint'},'Original damage and puncture calls use AMS2 damage, wheel and pressure data. Ask “damage report”, “how’s my aero”, “how’s my suspension”, “how’s my engine” or “how are my brakes”. Crash checks use actual push-to-talk history; answer “I’m OK” when asked. AMS2 transmission damage is unavailable in the original mapper.'),
      packControls,packNote,
      h('label',{style:{display:'block'}},tts,' Read calls without a voice clip with text-to-speech'),
      h('label',{style:{display:'block'}},'Windows voice for text-to-speech ',windowsVoice),voiceStatus,reloadVoice),
    unitsPanel,fuelPanel,racePanel,apexPanel,speedPanel,brakePanel,sectionPanel,widePanel,
    h('details',null,h('summary',null,'Test on a recording'),
      h('p',{class:'hint'},'Runs through past telemetry in order and saves a private decision log. The original recording is preserved.'),
      h('div',{class:'actions',style:{flexWrap:'wrap',minWidth:'0'}},recordings,replayDriver,speed,replay,replayStop),replayNote,review),
    h('details',null,h('summary',null,'Radio decisions and evidence'),transcript));
  function update() {
    updateCalls();
    var ov=status.overlay||{},card=ov.card;
    overlayEnabled.checked=!!ov.enabled;overlayPosition.value=ov.position||'right';
    overlayEnabled.disabled=!known;overlayPosition.disabled=!known;
    overlayNote.textContent=ov.error||((!ov.enabled?'Overlay off. Press the garage Confirm button in the practice garage to reopen.':ov.reason==='no_advice'?'In the garage. Waiting for an analysed run or Practice 2 plan.':ov.reason==='ready'?'Checklist ready. The desktop overlay appears while AMS2 is in front.':ov.reason==='dismissed'?'Hidden for this garage visit. Press garage Confirm to reopen.':ov.reason==='not_in_garage'?'Overlay on. It opens automatically when you return to the practice garage.':'Overlay on. Waiting for fresh practice garage telemetry.')+(ov.display_delayed?' Display file is busy; retrying automatically.':'')+(ov.note?' '+ov.note:''));
    overlayCard.replaceChildren();
    if(card){overlayCard.append(h('div',{class:'muted'},(ov.index+1)+' / '+ov.total+' · '+card.location),h('h3',null,card.heading),h('b',null,card.action),h('p',null,card.detail),h('p',{class:'hint'},card.why));}
    else overlayCard.append(h('span',{class:'muted'},'Start live engineering to collect setup recommendations.'));
    overlayMenu.replaceChildren();
    if(card)(ov.menu||[]).forEach(function(item,i){overlayMenu.append(h('div',{'aria-current':i===ov.menu_index?'true':null,style:{padding:'3px 8px',fontWeight:i===ov.menu_index?'bold':'normal',borderLeft:i===ov.menu_index?'3px solid #19a7ae':'3px solid transparent'}},(i===ov.menu_index?'▶ ':'')+item.label));});
    overlayActions.concat(overlayMenuButtons).forEach(function(b){b.disabled=!ov.enabled||!card||!!ov.pending;});
    if(!alive)return;
    var live=status.live, ctx=live&&live.context, job=status.replay||{};
    if(status.radio_names&&status.radio_names.error)nameNote.textContent=status.radio_names.error;
    var ready=status.readiness;
    readiness.replaceChildren();
    if(!ready)readiness.appendChild(h('p',null,'Restart Paddock after recording finishes to load coach readiness diagnostics.'));
    else {
      readiness.appendChild(h('b',null,'Speech readiness'));
      var standalone=status.output==='paddock';
      readiness.appendChild(h('p',{class:'hint'},!status.running?'Live coach is off.':!status.audio_enabled?'Silent text preview is running; no sound will be sent.':
        (standalone?'Paddock is speaking the calls itself. ':'Calls go through Crew Chief. ')+
        (ready.tts_fallback?'Voice-pack clips play first; other calls are read by '+(standalone?'Windows speech':'Crew Chief text-to-speech')+'. ':'Only lines the voice pack covers are spoken. ')+
        'A clear radio spot is still required: straights first, a calmer moment after a few seconds.'));
      if(ready.session==='qualify')readiness.appendChild(h('p',{class:'hint warnline'},'In qualifying only running-wide warnings are implemented, and push laps stay silent.'));
      readiness.appendChild(h('p',{class:'hint'},ready.candidates+' candidates · '+ready.selected+' selected · '+(standalone?(ready.speech_queued||0)+' calls played by Paddock':ready.audio_queued+' clips sent to Crew Chief · '+ready.clips_served+' clips fetched · '+(ready.speech_queued||0)+' text-to-speech calls sent')+'. Playing a call does not confirm it was heard.'+
        (ready.latest_hold?' Latest hold: '+ready.latest_hold.replace(/_/g,' ')+'.':'')));
      var missing=(ready.voice_coverage||[]).filter(function(r){return r.coverage==='none';});
      readiness.appendChild(h('p',{class:'hint'},'A voice pack speaks a line when it has every word or phrase in it; anything else is read by text-to-speech when that is on. Live corner comparisons do not yet compensate for tyre temperature.'));
    }
    var program=status.running&&live?live.program:null;
    planPanel.hidden=!status.running;
    goalButtons.forEach(function(b){b.disabled=busy||!program||!program.active;});
    goalButtons[1].disabled=goalButtons[1].disabled||!(program&&program.candidate);
    var canReply=!!status.running&&((program&&program.active)||status.output==='paddock');
    sayButton.disabled=busy||!canReply;sayInput.disabled=!canReply;
    sayInput.placeholder=program&&program.active?'e.g. No, this is practice session 2':'e.g. whats my oil temp';
    if(!program||!program.active){
      planGoal.textContent=program&&program.lookup_error?'R&D plans could not be read: '+program.lookup_error:
        'Starts when you are in a practice session with the live coach running. The engineer asks what the session is for while you are in the pits.';
      objectiveList.replaceChildren();planNote.textContent='';
    } else {
      var source={voice:'confirmed by voice',typed:'confirmed by text',screen:'chosen here',assumed:'no answer, so the detected goal is used'}[program.source]||'';
      planGoal.textContent=program.goal?(program.goal_label+(source?' · '+source:'')):
        'Waiting for your answer: '+(program.detected==='practice2'?'Practice 2 detected':'Practice 1 detected')+'.';
      var cand=program.candidate;
      planNote.textContent=(cand?'R&D plan waiting for Practice 2: '+cand.projects.join(' and ')+' (weekend '+cand.round+').'+
          (program.other_candidates?' '+program.other_candidates+' older waiting plan(s) were not used.':''):
        'No locked R&D plan is waiting for this driver, car, track and layout, so Practice 2 is unavailable.')+' '+
        (status.talk&&status.talk.bindings&&status.talk.bindings.ptt?'Hold your radio button and say “confirm”, “negative”, “this is practice two”, “what\u2019s the plan”, “how am I doing” or “debrief”.':
         program.replies_enabled?'Voice replies are on: hold Crew Chief\u2019s radio button and say “confirm”, “negative”, “this is practice two”, “what\u2019s the plan”, “how am I doing” or “debrief”.':
         'To answer by voice, set your radio button under Talk to the engineer below; or type here.')+
        ' Live progress uses the R&D assessment\u2019s method; official credit is still assessed when Practice 2 is filed in the weekend.';
      objectiveList.replaceChildren();
      (program.objectives||[]).forEach(function(o){
        var value=o.kind==='clean_lap'||o.kind==='endurance'?(o.met?'done':'not yet'):
          o.actual===null||o.actual===undefined?'no counted laps yet':
          o.kind==='corner'?(o.actual>=0?'+':'')+o.actual.toFixed(2)+' km/h average (target +'+o.target.toFixed(1)+')':
          o.kind==='pace'?o.actual.toFixed(3)+' s average (target '+o.target.toFixed(3)+' s)':
          o.kind==='fuel'?o.actual.toFixed(3)+' L/lap (target '+o.target.toFixed(3)+')':o.actual+' counted';
        objectiveList.appendChild(h('div',{style:{padding:'4px 0',borderBottom:'1px solid var(--border)'}},
          h('b',null,(o.met?'Met · ':'Open · ')+o.project+': '),o.text,h('div',{class:'hint'},value+(o.kind==='clean_lap'||o.kind==='endurance'?'':' · '+(o.laps||0)+' lap(s) counted')+(o.corners?' · '+o.corners.join(', '):''))));
      });
      if(program.engineer&&program.engineer.wanted)objectiveList.appendChild(h('p',{class:'hint'},
        status.program_error||('Setup engineer follows each run'+(program.engineer.last?'; last analysed run '+program.engineer.last.run+'.':'.'))));
      planLines.replaceChildren();
      (program.lines||[]).slice().reverse().forEach(function(line){planLines.appendChild(h('p',{class:'hint'},line.code+' · '+line.text));});
      (program.replies||[]).slice().reverse().forEach(function(r){planLines.appendChild(h('p',{class:'hint'},'You ('+r.source+'): “'+r.text+'” → '+r.understood+'. '+(r.response||'')));});
    }
    speedPanel.hidden=!status.capabilities||!status.capabilities.implemented_rules.some(function(rule){return rule.id==='C-09';});
    var cornerSpeed=status.running?live&&live.corner_speed:job.state==='complete'&&job.result.engine?job.result.engine.corner_speed:null;
    speedReadout.textContent=!cornerSpeed?'Start a live preview or analyse a practice recording.':
      (cornerSpeed.clean_intervals_completed||0)+' clean full-lap intervals checked · '+(cornerSpeed.learned_bends||[]).length+
      ' bends learned · '+(cornerSpeed.diagnostics.confirmed_patterns||0)+' repeated patterns · '+(cornerSpeed.reason||'learning').replace(/_/g,' ')+'. Needs two earlier reference intervals and three recent eligible intervals.';
    brakePanel.hidden=!status.capabilities||!status.capabilities.implemented_rules.some(function(rule){return rule.id==='C-05';});
    var braking=status.running?live&&live.braking:job.state==='complete'&&job.result.engine?job.result.engine.braking:null;
    brakeReadout.textContent=!braking?'Start a live preview or analyse a practice recording.':
      (braking.clean_intervals_completed||0)+' clean full-lap intervals checked · '+(braking.diagnostics.confirmed_patterns||0)+
      ' repeated patterns · '+(braking.comparison_reason||'learning').replace(/_/g,' ')+'. Entry is measured 20 metres before the inferred bend minimum. Pedals must share the position timestamp. Tyre-temperature compensation is not available.';
    widePanel.hidden=!status.capabilities||!status.capabilities.implemented_rules.some(function(rule){return rule.id==='C-26';});
    var wide=status.running?live&&live.offtrack:job.state==='complete'&&job.result.engine?job.result.engine.offtrack:null;
    wideReadout.textContent=!wide?'Start a live preview or analyse a recording.':
      (wide.episodes_on_valid_laps||0)+' running-wide moments on laps that still counted'+
      ((wide.spots||[]).length?' (near '+wide.spots.map(function(m){return m+' m';}).join(', ')+')':'')+' · '+
      (wide.diagnostics.confirmed_patterns||0)+' repeated · '+(wide.reason||'learning').replace(/_/g,' ')+'.';
    sectionPanel.hidden=!status.capabilities||!status.capabilities.implemented_rules.some(function(rule){return rule.id==='C-01';});
    var sections=status.running?live&&live.sections:job.state==='complete'&&job.result.engine?job.result.engine.sections:null;
    sectionReadout.textContent=!sections?'Start a live preview or analyse a practice recording.':
      (sections.diagnostics.confirmed_patterns||0)+' repeated section losses · '+(sections.reason||'learning').replace(/_/g,' ')+
      ((sections.ranking||[]).length?' · latest lap against your references: '+sections.ranking.map(function(r){
        return r.distance_m+' m '+(r.latest_slower_by_s>=0?'+':'')+r.latest_slower_by_s.toFixed(2)+' s';}).join(', '):'')+'.';
    apexPanel.hidden=!status.capabilities||!status.capabilities.implemented_rules.some(function(rule){return rule.id==='C-10';});
    var apex=status.running?live&&live.apex:job.state==='complete'&&job.result.engine?job.result.engine.apex:null;
    apexReadout.textContent=!apex?'Start a live preview or analyse a practice recording.':
      apex.map_reason!=='mapped'?'Mapped apex feedback unavailable: '+(apex.map_reason||'matching edge map missing').replace(/_/g,' ')+'.':
      (apex.clean_intervals_completed||0)+' clean full-lap intervals checked · mapped corners '+(apex.supported_corners||[]).join(', ')+
      ' · '+(apex.diagnostics.confirmed_patterns||0)+' repeated patterns · '+(apex.reason||'learning').replace(/_/g,' ')+'.';
    var measurements=status.capabilities&&status.capabilities.implemented_measurements||[];
    racePanel.hidden=!measurements.some(function(m){return m.id==='P-02';});
    var race=status.running?live&&live.race_length:job.state==='complete'&&job.result.engine?job.result.engine.race_length:null;
    var raceValue=race&&(race.current||race.last_estimate);
    raceReadout.textContent=!race?'Start a live preview or analyse a race recording.':
      !raceValue?'No finish estimate · '+(race.reason||'learning').replace(/_/g,' ')+'.':
      (!race.current?'Earlier reading · ':'')+'Overall leader '+(raceValue.state==='observed_finish'?'finished':raceValue.state==='scheduled'?'scheduled to finish':'estimated to finish')+
      ' on lap '+raceValue.finish_lap_low+(raceValue.finish_lap_low!==raceValue.finish_lap_high?'–'+raceValue.finish_lap_high:'')+
      (raceValue.mode==='timed'&&raceValue.additional_laps!==null?' · '+raceValue.additional_laps+' additional laps after the timer':'')+'.';
    fuelPanel.hidden=!status.capabilities||!status.capabilities.implemented_rules.some(function(rule){return rule.id==='S-16';});
    var fuelSource=status.running?'Live':job.state==='complete'?'At replay end':null;
    var fuel=status.running?live&&live.fuel:job.state==='complete'&&job.result.engine?job.result.engine.fuel:null;
    var estimate=fuel&&fuel.estimate,formatted=fuel&&fuel.formatted;
    fuelReadout.textContent=!fuel?'Start a live preview or analyse a completed recording to measure fuel use.':
      !estimate||!formatted?(fuelSource+' · '+Math.min(fuel.clean_samples||0,3)+' of three clean fuel samples · '+(fuel.reason||'learning').replace(/_/g,' ')+'.'+
        (fuel.last_calibration?' Earlier measured '+fuel.last_calibration.use.text+' on lap '+fuel.last_calibration.lap+'. No current range is available.':'')):
      fuelSource+' · '+formatted.use.text+' · observed use '+formatted.minimum_use.text+' to '+formatted.maximum_use.text+
      ' · '+(formatted.remaining_is_estimate?'estimated ':'')+formatted.remaining.text+' remaining · estimated range '+estimate.range_low_laps.toFixed(1)+'–'+estimate.range_high_laps.toFixed(1)+' laps at observed use.';
    var capability=status.capabilities;
    coverage.textContent=capability?'Development preview. Available calls: '+capability.implemented_rules.map(function(rule){return rule.label;}).join(', ')+
      '. Still being built: '+capability.not_yet_available.join(', ')+'.':
      'Development preview: observed rival pit entry is the only call rule currently implemented. Corner/apex, braking/throttle, pace and strategy coaching are still being built.';
    actions.forEach(function(b){b.disabled=busy||!known;});
    mode.value=status.mode||'full';
    mode.disabled=busy||!known;
    unitsPanel.hidden=!status.units;
    Object.keys(unitFields).forEach(function(key){unitFields[key].disabled=busy;unitFields[key].value=(pendingUnits||status.units||{})[key]||unitOptions[key][0][0];});
    var examples=status.format_examples||{};
    unitExamples.textContent='Format examples (not live readings): '+['distance','pressure','temperature','fuel'].map(function(key){return examples[key]?examples[key].text:'';}).filter(Boolean).join(' · ')+'. Fuel in laps needs measured consumption.';
    speech.checked=pendingSpeech===null?!!status.audio_enabled:pendingSpeech;
    speech.disabled=busy||!known||(!status.audio_enabled&&status.tts_fallback===false&&(!status.voice||!status.voice.clips));
    tts.checked=status.tts_fallback!==false;
    tts.disabled=busy||status.tts_fallback===undefined;
    output.value=status.output||'crew_chief';output.disabled=busy||status.output===undefined;
    volume.value=Math.round((status.volume==null?1:status.volume)*100);volume.disabled=busy||status.output!=='paddock';
    radioEffect.value=status.radio_effect||'full';radioEffect.disabled=busy||status.output!=='paddock';
    spotterBox.checked=!!status.spotter;spotterBox.disabled=busy||status.output!=='paddock'||status.spotter===undefined;
    baselineVoice.value=status.baseline_voice||'paddock';baselineVoice.disabled=busy||status.output!=='paddock';
    fuelMultiplier.value=status.fuel_multiplier==null?1:status.fuel_multiplier;fuelMultiplier.disabled=busy||!known||status.running;
    var ba=status.baseline_audio||{}, em=status.engine_monitor||{};
    baselineHint.textContent=(baselineVoice.value==='paddock'
      ?'Selected voice covers '+(ba.covered||0)+' of '+(ba.variants||0)+' implemented original phrases. Uncovered variants use the original local recording; no live synthesis delays warnings.'
      :'Baseline calls use the original locally installed recordings.')+' Engine monitor: '+(em.state||'waiting')+'.'+(em.error?' '+em.error:'');
    var pen=status.penalties||{};
    baselineHint.textContent+=' Penalties: '+(pen.state||'waiting')+'.'+(pen.error?' '+pen.error:'');
    var flags=status.flags||{};
    baselineHint.textContent+=' Flags: '+(flags.state||'waiting')+'.';
    var originalCore=status.original_core||{};
    if(originalCore.queue&&originalCore.queue.keep_quiet)baselineHint.textContent+=' Keep-quiet mode is active.';
      baselineHint.textContent+=' Damage: '+(originalCore.damage_state||'waiting').replace(/_/g,' ')+'.';
      baselineHint.textContent+=' Fuel: '+(originalCore.fuel_state||'waiting').replace(/_/g,' ')+'. Race time: '+(originalCore.race_time_state||'waiting').replace(/_/g,' ')+'.';
      baselineHint.textContent+=' Pit stops: '+(originalCore.pit_state||'waiting').replace(/_/g,' ')+'.';
      baselineHint.textContent+=' Position: '+(originalCore.position_state||'waiting').replace(/_/g,' ')+'.';
      baselineHint.textContent+=' Race starts and laps: '+(originalCore.lap_counter_state||'waiting').replace(/_/g,' ')+'.';
      baselineHint.textContent+=' Gaps: '+(originalCore.timings_state||'waiting').replace(/_/g,' ')+'.';
      if(originalCore.timings&&originalCore.timings.mode)baselineHint.textContent+=' Timing mode: '+originalCore.timings.mode+'.';
      baselineHint.textContent+=' Tyres and brakes: '+(originalCore.tyres_state||'waiting').replace(/_/g,' ')+'.';
      baselineHint.textContent+=' Lap and sector reports: '+(originalCore.lap_times_state||'waiting').replace(/_/g,' ')+'.';
      baselineHint.textContent+=' Session finish: '+(originalCore.session_end_state||'waiting').replace(/_/g,' ')+'.';
      if(originalCore.waiting_for_driver_ok)baselineHint.textContent+=' Waiting for your crash response.';
    baselineHint.textContent+=' Weather: '+(originalCore.state||'waiting').replace(/_/g,' ')+'.'+(originalCore.error?' '+originalCore.error:'');
    if(ba.selection==='original_4.19.5.4')baselineHint.textContent+=' Original clip and number selection active.';
    if(ba.uncaptioned_files)baselineHint.textContent+=' '+ba.uncaptioned_files+' original WAV variants have no known caption and still use original local audio.';
    if(ba.selection_error)baselineHint.textContent+=' Clip selection: '+ba.selection_error;
    if(ba.uncaptioned_personalisation_files)baselineHint.textContent+=' '+ba.uncaptioned_personalisation_files+' personal-name clips use the original local recordings.';
    if(ba.numeric&&ba.numeric.variants){
      baselineHint.textContent+=' Number phrases: '+ba.numeric.covered+'/'+ba.numeric.variants+' cached.';
      if(ba.numeric.time_values)baselineHint.textContent+=' Compound time values: '+ba.numeric.time_values_cached+'/'+ba.numeric.time_values+' cached in the selected voice.';
      var numericFallback=ba.numeric.uncaptioned_fallback_folders===undefined?ba.numeric.uncaptioned_folders:ba.numeric.uncaptioned_fallback_folders;
      if(numericFallback)baselineHint.textContent+=' '+numericFallback+' uncaptioned number folders still use original local audio.';
    }
    if(status.spotter_status&&status.spotter_status.error)error.textContent='Spotter: '+status.spotter_status.error;
    var local=status.local_radio||{},voices=local.windows_voices||[];
    var voiceSignature=JSON.stringify(voices)+'|'+(status.windows_voice||'');
    if(windowsVoice.dataset.signature!==voiceSignature){
      windowsVoice.dataset.signature=voiceSignature;windowsVoice.replaceChildren(h('option',{value:''},'Windows default'));
      voices.concat(status.windows_voice&&voices.indexOf(status.windows_voice)<0?[status.windows_voice]:[]).forEach(function(v){windowsVoice.appendChild(h('option',{value:v},v));});
    }
    windowsVoice.value=status.windows_voice||'';windowsVoice.disabled=busy||status.output!=='paddock'||!status.tts_fallback;
    outputHint.textContent=status.output==='paddock'
      ?'Paddock plays the calls itself on Windows\u2019 default sound device, as a team radio sounds (key click, squelch, compressed voice, static and pit-wall noise; a click when you key your radio): lap times, cold tyres and brakes, deleted laps, low fuel and the coaching calls. Keep Crew Chief running for its spotter if you like; Paddock waits while Crew Chief is talking.'+(local.error?' Last radio error: '+local.error:'')+(local.speech_error?' '+local.speech_error:'')
      :'Crew Chief plays Paddock\u2019s calls in its own radio queue. Set up cached audio in the Crew Chief panel first. Crew Chief keeps making its own calls too.';
    var sdk=status.sdk||{},voice=status.voice||{};
    voiceStatus.textContent=!status.voice?'Restart Paddock after your recording finishes to load the cached-speech update.':
      voice.errors&&voice.errors.length?'Voice cache: '+voice.errors.join('; '):
      (voice.voice_name?voice.voice_name+' · ':'')+(voice.clips||0)+' verified clips'+(voice.fragments?' ('+voice.fragments+' phrases and words to build lines from)':'')+' · '+(!status.audio_enabled?'speech off':
       status.output==='paddock'?(local.busy?'Paddock radio talking':'Paddock radio ready')+(sdk.available?(sdk.busy?' · Crew Chief talking':' · Crew Chief idle'):''):
       !sdk.available?'waiting for fresh Crew Chief shared memory':sdk.busy?'Crew Chief radio is busy':'Crew Chief radio observed idle');
    var packs=status.voice_packs||{},packJob=packs.job||{},packBusy=!!packs.busy;
    var packSupported=Array.isArray(packs.available)&&!!packs.job;
    packControls.hidden=!packSupported;
    var options=[{key:'jim-private',name:'Private Jim pilot',local:true}];
    (packs.installed||[]).forEach(function(p){options.push({key:p.key,name:p.name+' · '+p.version,local:true});});
    (packs.importable||[]).forEach(function(p){
      options.push({key:p.key,name:p.name+' · on this PC · install '+size(p.bytes),local:false,importing:true});
    });
    (packs.available||[]).forEach(function(p){
      if(!options.some(function(o){return o.key===p.key;}))options.push({key:p.key,name:p.name+' · '+p.version+' · download '+size(p.bytes),local:false});
    });
    if(packs.selected&&!options.some(function(o){return o.key===packs.selected;}))options.push({key:packs.selected,name:'Selected voice unavailable',local:true});
    var optionSignature=JSON.stringify(options);
    if(lastVoiceOptions!==optionSignature){lastVoiceOptions=optionSignature;voiceChoice.replaceChildren();options.forEach(function(o){voiceChoice.appendChild(h('option',{value:o.key},o.name));});}
    if(packs.selected&&(chosenVoice===null||!options.some(function(o){return o.key===chosenVoice;})))chosenVoice=packs.selected;
    voiceChoice.value=chosenVoice||packs.selected||'jim-private';
    var selectedOption=options.find(function(o){return o.key===chosenVoice;});
    voiceChoice.disabled=busy||packBusy||!!status.running;
    chooseVoice.textContent=selectedOption&&selectedOption.importing?'Install and use voice':selectedOption&&!selectedOption.local?'Download and use voice':'Use selected voice';
    chooseVoice.disabled=busy||packBusy||!!status.running||chosenVoice===packs.selected;
    cancelVoice.hidden=!packBusy;
    cancelVoice.disabled=busy||packJob.state==='cancelling'||packJob.state==='activating';
    packProgress.hidden=!packBusy;
    packProgress.max=packJob.total_bytes||1;packProgress.value=packJob.received_bytes||0;
    var packMessage=!packSupported?'Restart Paddock after your recording finishes to load engineer voice selection.':
      packJob.state==='cancelling'?'Cancelling the voice change. Your previous voice remains selected.':
      packBusy?(packJob.state==='downloading'?'Downloading '+packJob.name+' · '+size(packJob.received_bytes||0)+' / '+size(packJob.total_bytes||0):
        packJob.state==='verifying'?'Verifying '+packJob.name+' before switching voices.':'Activating '+packJob.name+'.'):
      packJob.state==='failed'?'Voice change failed: '+packJob.error+'. Your previous voice remains selected.':
      packJob.state==='cancelled'?'Voice change cancelled. Your previous voice remains selected.':
      packJob.state==='complete'?'Selected '+(voice.voice_name||packJob.name)+'.':'';
    if(packSupported)packMessage+=(packMessage?' ':'')+(status.running?'Stop the live coach to change voices. ':'' )+
      (!packs.available.length?'No downloadable voice packs are published yet. ':'')+
      'After a successful switch, Paddock keeps only the selected managed pack. Private references and audition files are preserved.';
    if(packs.catalogue_error)packMessage+=' '+packs.catalogue_error;
    if(packs.warnings&&packs.warnings.length)packMessage+=' '+packs.warnings.join('; ');
    packNote.textContent=packMessage;
    reloadVoice.disabled=busy||packBusy||!!status.running;
    start.hidden=!!status.running;stop.hidden=!status.running;
    var eng=status.engineer||{};
    engineerStart.hidden=!!eng.running;engineerStop.hidden=!eng.running;
    engineerStart.disabled=busy||!status.current;
    bothStart.hidden=!!status.running&&!!eng.running;
    bothStart.disabled=busy||packBusy||!status.current||!status.current.driver;
    engineerState.textContent=!known?'Loading live status…':(status.running?'Coach on':'Coach off')+' · '+(status.audio_enabled?'Voice on':'Voice off')+' · '+(eng.running?'Setup tracking on':'Setup tracking off')+' · '+(ov.enabled?'Overlay on':'Overlay off')+
      (status.running&&status.live&&status.live.context&&status.live.context.session==='practice'&&!eng.running?' (starts by itself in practice)':'');
    setupLink.hidden=!eng.key;setupLink.href=eng.key?'#/engineer/'+encodeURIComponent(eng.key):'#/engineer';
    var talk=status.talk||{},bindings=talk.bindings||{};
    var signature=JSON.stringify([bindings,talk.capturing,busy]);
    if(signature!==talkSignature){
      talkSignature=signature;talkRows.replaceChildren();
      (talk.roles||Object.keys(talkLabels)).forEach(function(role){
        var b=bindings[role];
        talkRows.appendChild(h('div',{class:'actions',style:{flexWrap:'wrap',alignItems:'center',minWidth:'0'}},
          h('span',{style:{minWidth:'190px'}},talkLabels[role]||role),
          h('span',{class:'muted',style:{minWidth:'0',overflowWrap:'anywhere'}},talk.capturing===role?'Press the button now\u2026':b?b.label:'Not set'),
          h('button',{class:'btn ghost small',disabled:busy||!!talk.capturing,onclick:function(){
            talkNote.textContent='Waiting for a button press\u2026';
            api('/api/coach/buttons/capture','POST',{role:role}).then(function(v){if(alive){status=v;update();}})
              .catch(function(e){if(alive)talkNote.textContent='Could not start: '+(e.message||String(e))+(/Unknown coach request/.test(String(e.message||e))?' Restart Paddock to load wheel-button setup.':'');});
          }},b?'Change':'Set'),
          b?h('button',{class:'btn ghost small',disabled:busy,onclick:function(){
            api('/api/coach/buttons/clear','POST',{role:role}).then(function(v){if(alive){status=v;update();}})
              .catch(function(e){if(alive)talkNote.textContent=e.message||String(e);});
          }},'Clear'):null));
      });
    }
    if(!status.talk){talkNote.textContent='Restart Paddock to load wheel-button setup (the page is newer than the running Paddock).';}
    var heard=talk.last_heard;
    talkNote.textContent=[talk.note,
      talk.state==='starting'?'Preparing microphone\u2026 wait for the radio click.':talk.state==='listening'?'Listening\u2026':talk.state==='thinking'?'Working out what you said\u2026':'',
      heard?(heard.text?'Last heard: \u201c'+heard.text+'\u201d'+(heard.understood?'':' (not sure enough to act on it)'):'Last press: '+(heard.problem||'nothing recognised')+'.'):'',
      talk.buttons_error||'',talk.speech_error||'',
      talk.controllers?('Controllers Windows sees: '+(talk.controllers.length?talk.controllers.join(', '):'none')+'.'):''].filter(Boolean).join(' ');
    if(!status.talk)talkNote.textContent='Restart Paddock to load wheel-button setup (the page is newer than the running Paddock).';
    start.textContent=status.audio_enabled?'Start live race coach':'Start live coach preview';
    stop.textContent=status.audio_enabled?'Stop live race coach':'Stop live coach preview';
    start.disabled=busy||packBusy||!status.current||!status.current.driver;
    quiet.disabled=busy||!status.running||!ctx||!ctx.active;
    replay.disabled=busy||!recordings.value||job.state==='running';
    replayStop.hidden=job.state!=='running';
    driver.textContent=status.running&&live?'Following '+live.driver:(status.current&&status.current.driver?'Current driver: '+status.current.driver:'');
    note.textContent=status.error||(!status.running?'Coach preview is off. Start it while you are in your car.':
      !ctx?'Waiting for telemetry.':!ctx.active?'Waiting: '+ctx.reason.replace(/_/g,' ')+'.':
      'Lap '+ctx.lap+' · '+(live.window_validation_pending?'saved radio windows await a fresh clean lap':
       (live.learned_laps||0)+' of two clean laps learned for radio windows')+' · '+live.pending+' waiting calls.'+
       (live.window_cache_error?' Saved windows unavailable; learning fresh laps.':''));
    replayNote.textContent=job.state==='running'?'Replaying '+job.recording+' · '+(job.ticks||0)+' snapshots processed.':
      job.state==='failed'?'Replay failed: '+job.error:job.state==='stopped'?'Replay stopped.':
      job.state==='complete'?'Replay complete · '+(job.result.recording||job.recording||'Recording')+' · '+job.result.ticks+' snapshots · '+(job.result.counts.would_say||0)+' simulated calls. '+
        (job.result.speech_simulation==='cached_voice'?'Checked against the selected cached voice; radio assumed idle. ':'Text preview; cached voice availability was not tested. ')+
        (job.result.explanation?job.result.explanation.text:
         !(job.result.counts.queued||job.result.counts.would_say)?'No call candidates were generated. This preview currently runs observed rival pit-entry rules only.':'See the replay evidence timeline for held or dropped calls.'):'';
    review.hidden=job.state!=='complete';
    if(!review.hidden)review.href='/coach-review?run='+encodeURIComponent(job.result.directory.replace(/\\/g,'/').split('/').pop());
    var events=status.events||[], signature=JSON.stringify(events);
    if(signature!==lastEvents) {
      lastEvents=signature;transcript.replaceChildren();
      if(!events.length)transcript.appendChild(h('p',{class:'hint'},'No decisions yet. Radio windows are learned from two clean laps. Pit calls require an observed pit-entry transition.'));
      else events.slice().reverse().forEach(function(e){
        transcript.appendChild(h('div',{style:{padding:'8px 0',borderBottom:'1px solid var(--border)'}},
          h('b',null,(e.code||'Coach')+' · lap '+e.lap+' · '+e.state.replace(/_/g,' ')),
          h('div',null,e.text||(e.reason||'Queued').replace(/_/g,' ')),
          e.evidence?h('details',null,h('summary',null,'Evidence'),h('pre',{style:{whiteSpace:'pre-wrap'}},JSON.stringify(e.evidence,null,2))):null));
      });
    }
  }
  function size(bytes){return bytes>=1048576?(bytes/1048576).toFixed(1)+' MB':Math.ceil(bytes/1024)+' KB';}
  recordings.onchange=function(){update();};
  function refresh() {
    if(!alive||loaded)return Promise.resolve();
    loaded=true;var observedEpoch=epoch;
    return api('/api/coach').then(function(value){if(alive&&observedEpoch===epoch){known=true;status=value;update();}})
      .catch(function(e){if(alive)note.textContent='Coach preview unavailable: '+(e.message||String(e));})
      .finally(function(){loaded=false;});
  }
  api('/api/recordings').then(function(value){
    if(!alive)return;
    (value.recordings||[]).filter(function(r){return r.status==='complete';}).forEach(function(r){
      recordings.appendChild(h('option',{value:r.id},(r.track||'Track')+' · '+r.type+' · '+String(r.started_at||r.id)));
    });update();
  }).catch(function(e){if(alive)error.textContent='Recording list: '+(e.message||String(e));});
  update();refresh();var timer=setInterval(refresh,1500);
  return {element:element,destroy:function(){alive=false;clearInterval(timer);if(skillOverlay)skillOverlay.close();}};
};
