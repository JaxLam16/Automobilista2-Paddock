/* Optional Crew Chief connection panel shared by both engineer views. */
window.PaddockCrewChief = function (ui) {
  'use strict';
  var h = ui.h, api = ui.api, alive = true, busy = false, status = {}, initialized = false, gameSession = null;
  function sessionState(recorder) {
    // A stopped recorder cannot establish whether Crew Chief has a session.
    // The game itself remains usable with recording switched off.
    if (!recorder.running) return null;
    if (recorder.current) return true;
    if (!recorder.connected || [0, 1, 5, 6, 7].indexOf(recorder.game_state) !== -1) return false;
    return null;
  }
  function checkSession() {
    return api('/api/recorder').then(function (recorder) {
      gameSession = sessionState(recorder);
      if (gameSession === false) throw new Error('Crew Chief custom speech requires an active AMS2 session. Enter practice, qualifying or a race, wait for Crew Chief to recognize it, then send the check.');
    });
  }
  var title = h('h3', null, 'Crew Chief radio');
  var label = h('p', {class:'hint',role:'status','aria-live':'polite'}, 'Checking the installed Crew Chief…');
  var result = h('p', {class:'hint',role:'status'});
  var exe = h('input', {type:'text','aria-label':'Crew Chief executable',style:{maxWidth:'100%'}});
  var base = h('select', {'aria-label':'Copy Crew Chief profile'});
  var port = h('input', {type:'number',min:1024,max:65535,'aria-label':'Crew Chief local port',value:48643});
  var setupHint = h('p', {class:'hint'});
  var baseField = h('label', {class:'field'}, h('span', null, 'Copy settings from'), base);
  var fields = h('details', null, h('summary', null, 'Connection setup'),
    setupHint,
    h('label', {class:'field'}, h('span', null, 'Crew Chief executable'), exe),
    baseField,
    h('label', {class:'field'}, h('span', null, 'Local port'), port));
  var buttons = [];
  function button(text, action, body, after) {
    var b = h('button', {class:'btn ghost small',onclick:function () {
      busy = true; update();
      // Recheck at click time as well as in polling: the driver may have left
      // the session since the last status refresh.
      (action === 'test' ? checkSession() : Promise.resolve()).then(function () {
        return api('/api/crew-chief/' + action, 'POST', body ? body() : {});
      }).then(function (value) {
        if (after) return after(value);
        if (value.message && alive) result.textContent = value.message;
      }).catch(function (err) { if (alive) result.textContent = err.message || String(err); })
        .finally(function () { busy = false; if (alive) refresh(); });
    }}, text);
    buttons.push(b);
    return b;
  }
  var configure = button('Set up local connection', 'configure', function () {
    return {exe:exe.value,base_profile:base.value,port:Number(port.value)};
  }, function () { return api('/api/crew-chief/start', 'POST', {}).then(function () {
    if (alive) result.textContent = 'Connection ready. Open Crew Chief with the Paddock profile, then start its AMS2 application.';
  }); });
  fields.appendChild(configure);
  var open = button('Open Crew Chief', 'launch');
  var start = button('Start connection', 'start');
  var stop = button('Stop connection', 'stop');
  var test = button('Send radio check', 'test', null, function () {
    if (alive) result.textContent = 'Radio check sent. Crew Chief must have recognized an active AMS2 session for this custom message to play.';
  });
  var heard = button('I heard it', 'heard', function () { return {id:status.last_test.id}; });
  var prepareAudio = button('Set up cached audio', 'prepare-audio', null, function () {
    if (alive) result.textContent = 'Cached audio is configured. Open Crew Chief with the Paddock profile, start AMS2 in Crew Chief, then enable cached speech in the private coach panel.';
  });
  var audioHint = h('p',{class:'hint'});
  /* Voice replies (V-24): Crew Chief macros pass "confirm", "this is practice two" and so on to Paddock. */
  var prepareReplies = button('Set up voice replies', 'prepare-replies', null, function () {
    if (alive) result.textContent = 'Voice replies are set up. Open Crew Chief with the Paddock profile; hold its radio button to answer the engineer.';
  });
  var updateReplies = button('Update voice replies (no pop-up window)', 'prepare-replies', null, function () {
    if (alive) result.textContent = 'Voice replies updated: no window opens any more and the game keeps focus. Open Crew Chief with the Paddock profile again.';
  });
  var restoreReplies = button('Remove voice replies', 'restore-replies', null, function () {
    if (alive) result.textContent = 'Voice replies removed. Your other Crew Chief macros and settings were kept.';
  });
  var spotterOnly = button('Crew Chief: spotter and flags only', 'prepare-spotter-only', null, function () {
    if (alive) result.textContent = 'Crew Chief keeps its spotter, flags, damage and race calls; Paddock now makes the lap-time, temperature and fuel calls.';
  });
  var spotterRestore = button('Give those calls back to Crew Chief', 'restore-spotter-only', null, function () {
    if (alive) result.textContent = 'Crew Chief\u2019s lap-time, temperature and fuel calls are back as they were.';
  });
  var spotterHint = h('p', {class:'hint'});
  var spotterDetails = h('details', null, h('summary', null, 'Paddock speaking for itself'), spotterHint,
    h('div', {class:'actions'}, spotterOnly, spotterRestore));
  var repliesList = h('ul', {class:'hint',style:{margin:'4px 0 0 18px'}});
  var repliesHint = h('p', {class:'hint'});
  var repliesDetails = h('details', null, h('summary', null, 'Voice replies to the engineer'), repliesHint,
    h('div', {class:'actions'}, prepareReplies, updateReplies, restoreReplies), repliesList);
  var restore = button('Restore previous connection settings', 'restore');
  var restoreDetails = h('details', null, h('summary', null, 'Restore Crew Chief settings'),
    h('p', {class:'hint'}, 'Close Crew Chief first. Restores the previous MQTT settings and any reused Paddock profile; a profile created during setup is removed. Newer edits are preserved and reported.'), restore);
  var element = h('section', {class:'panel pad eng-radio',style:{overflowWrap:'anywhere'}}, title, label, fields,
    h('div', {class:'actions'}, open, start, stop, test, heard, prepareAudio), result, audioHint,
    h('details', null, h('summary', null, 'Radio check received but silent?'),
      h('p', {class:'hint'}, 'Crew Chief acknowledges delivery before deciding whether to play audio. Custom MQTT messages require a recognized AMS2 session, even though Crew Chief’s own startup speech works without one. Enter practice, qualifying or a race and wait for Crew Chief to recognize it. Also check its audio device, volume, mute and TTS setting (Only when necessary or Any time). Release the talk button before testing.')),
    h('p', {class:'hint'}, 'Crew Chief keeps its usual race calls and spotting. Paddock\u2019s live coach calls play through this connection; set them up in Private race coach below.'), spotterDetails, repliesDetails, restoreDetails);
  function update() {
    if (!alive) return;
    buttons.forEach(function (b) { b.disabled = busy; });
    fields.hidden = !!status.configured;
    baseField.hidden = !!status.profile_exists;
    setupHint.textContent = status.profile_exists
      ? 'Close Crew Chief before setup. Your existing Paddock.json profile will be reused, keeping its preferences. Both the profile and MQTT settings are backed up first.'
      : 'Close Crew Chief before setup. Paddock copies your chosen profile and backs up the MQTT connection settings. Other profiles and sound packs are kept.';
    restoreDetails.hidden = !status.configured;
    prepareAudio.hidden = !status.configured || typeof status.cached_audio_configured!=='boolean' || status.cached_audio_configured;
    prepareAudio.disabled = busy || !!status.running;
    audioHint.hidden = !status.configured || typeof status.cached_audio_configured!=='boolean';
    audioHint.textContent = status.cached_audio_configured
      ? 'Cached audio is prepared. Crew Chief plays Paddock clips through its own radio queue. The private coach controls whether new calls are sent.'
      : 'Close Crew Chief before cached-audio setup so it saves its current preferences. Setup backs up its files, enables local audio and the shared-memory radio observer; other preferences and sound packs are preserved.';
    spotterDetails.hidden = !status.configured || typeof status.spotter_only !== 'boolean';
    spotterOnly.hidden = !!status.spotter_only;
    spotterRestore.hidden = !status.spotter_only;
    spotterOnly.disabled = spotterRestore.disabled = busy || !!status.running;
    spotterHint.textContent = (status.spotter_only
      ? 'Crew Chief\u2019s lap times, tyre and brake temperatures, fuel, tyre wear and pace comments are off in the Paddock profile, so Paddock makes those calls. Its spotter, flags, damage, positions and race calls are unchanged. '
      : 'When Paddock speaks the calls itself, switch off Crew Chief\u2019s overlapping calls (lap times, tyre and brake temperatures, fuel, tyre wear, pace comments) so you don\u2019t hear both. Only the Paddock profile changes; its spotter, flags and race calls stay, and you can give them back at any time. ') +
      (status.running ? 'Close Crew Chief to change this.' : 'Close Crew Chief first.');
    var replies = status.voice_replies;
    repliesDetails.hidden = !status.configured || !replies;
    if (replies) {
      prepareReplies.hidden = replies.configured;
      updateReplies.hidden = !replies.needs_update;
      restoreReplies.hidden = !replies.configured;
      prepareReplies.disabled = updateReplies.disabled = restoreReplies.disabled = busy || !!status.running;
      repliesDetails.open = repliesDetails.open || !!replies.needs_update;
      repliesHint.textContent = (replies.needs_update
        ? 'Your voice replies use the first version, which runs a command in a console window: it pops up and takes focus from the game for a moment. Close Crew Chief and press Update: each reply then presses two spare keys instead (F24, then one of F13\u2013F20), no window opens, and Crew Chief\u2019s \u201crun commands from macros\u201d preference goes back to how it was. '
        : replies.configured
        ? 'Set up. Hold Crew Chief\u2019s radio button and say one of these phrases; Paddock hears the meaning within a fraction of a second. You can also type replies in the practice plan below. '
        : 'Lets you answer the engineer by voice: Crew Chief recognises the phrases below on its radio button and passes them to Paddock. Close Crew Chief first. Setup backs up your macro file and the Paddock profile, adds Paddock\u2019s reply macros and turns on command macros in the Paddock profile only. ') +
        (replies.needs_update ? '' : 'Each reply presses two spare keys (F24, then one of F13\u2013F20) that ordinary keyboards don\u2019t have; Paddock notices them without taking them from the game, and AMS2 ignores them unless you bind them. No window opens. ') +
        (replies.error ? replies.error + ' Typed replies still work. ' : '') +
        'Remove voice replies to take the macros out again; your own macros are kept.' +
        (status.running ? ' Close Crew Chief to change this.' : '');
      repliesList.replaceChildren();
      replies.phrases.forEach(function (r) {
        repliesList.appendChild(h('li', null, {confirm:'Yes',negative:'No',practice1:'Practice 1',practice2:'Practice 2',free:'Free practice',plan:'Repeat the plan',progress:'Objective progress',debrief:'Debrief'}[r.token] + ': “' + r.phrases.join('”, “') + '”'));
      });
    }
    open.disabled = busy || !status.installed;
    start.hidden = !status.configured || status.listening;
    stop.hidden = !status.listening;
    test.disabled = busy || !status.connected || gameSession === false;
    test.title = gameSession === false ? 'Enter an AMS2 session before testing custom speech.' : '';
    heard.hidden = !status.last_test || status.last_test.heard;
    label.textContent = status.error || (status.connected
      ? gameSession === false ? 'Connected to Crew Chief. Waiting for an active AMS2 session before testing speech.'
        : gameSession === true ? 'Connected to Crew Chief. AMS2 session detected.'
        : 'Connected to Crew Chief. Session status is unavailable; custom speech requires an active AMS2 session.'
      : status.listening ? 'Connection listening. Open Crew Chief with the Paddock profile and start AMS2 in Crew Chief.'
      : status.configured ? 'Connection is stopped.' : status.installed ? 'Crew Chief detected. Set up the local connection below.'
      : 'Choose your installed CrewChiefV4.exe in Connection setup.');
    if (status.last_test && status.last_test.heard) result.textContent = 'Radio check heard and confirmed.';
    else if (status.last_test && status.last_test.received) result.textContent = 'Crew Chief acknowledged delivery. Audio playback is not confirmed; click “I heard it” only after hearing the check.';
  }
  function refresh() {
    return Promise.all([api('/api/crew-chief'), api('/api/recorder')]).then(function (values) {
      if (!alive) return;
      var s = values[0];
      status = s; gameSession = sessionState(values[1]);
      if (!initialized) {
        exe.value = s.exe || ''; port.value = s.port;
        s.profiles.forEach(function (p) { base.appendChild(h('option',{value:p,selected:p==='defaultSettings.json'},p)); });
        fields.open = !s.configured;
        initialized = true;
      }
      update();
    }).catch(function (err) { if (alive) label.textContent = err.message || String(err); });
  }
  refresh();
  var timer = setInterval(refresh, 2500);
  return {element:element,destroy:function () { alive=false;clearInterval(timer); }};
};
