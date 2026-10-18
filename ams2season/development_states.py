"""Reviewable championship R&D snapshots; only journalled research parameters move."""
from copy import deepcopy
import json
import math
import time
import uuid
from datetime import datetime,timezone

from .bop_files import transactions


class DevelopmentStates:
    def __init__(self, development):
        self.dev=development
        self.prepared={}

    @property
    def path(self):
        return self.dev.lib.root/'balance_of_performance'/'development_states.json'

    def read(self):
        if not self.path.exists():return {'version':1,'managed':False,'active_champ':None,'snapshots':[]}
        value=json.loads(self.path.read_text(encoding='utf-8'))
        if value.get('version')!=1 or not isinstance(value.get('snapshots'),list):
            raise ValueError('The R&D state index is unreadable. Restore its backup before switching states.')
        return value

    def write(self,value):
        self.path.parent.mkdir(exist_ok=True)
        if self.path.exists():
            backup=self.path.with_name('development_states-'+uuid.uuid4().hex+'.backup.json')
            backup.write_bytes(self.path.read_bytes())
        temp=self.path.with_name('development_states-'+uuid.uuid4().hex+'.tmp')
        temp.write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')
        temp.replace(self.path)

    def originals(self):
        """Earliest recorded before-value, including journals later undone."""
        originals={}
        for _,record in reversed(transactions(self.dev.editor.install_dir/'backups')):
            for change in record.get('changes',[]):
                if not change.get('development'):continue
                params=originals.setdefault(change['id'],{})
                for field in change.get('parameters',[]):
                    ident=field.get('id')
                    if ident is None:
                        matches=[p.id for p in self.dev.editor._car(change['id']).parameters if p.label==field['parameter']]
                        if len(matches)!=1:raise ValueError('An older R&D journal has ambiguous parameter names. Its original backup is preserved; automatic restoration is unavailable.')
                        ident=matches[0]
                    params.setdefault(ident,field['before'])
        return originals

    def active(self,value=None):
        value=value or self.read()
        if self.dev.editor.game is None:return bool(value.get('managed')),value.get('active_champ')
        # The game-write journal is authoritative after a crash between game
        # replacements and the small state-index save. Undo also works naturally.
        for _,record in transactions(self.dev.editor.install_dir/'backups'):
            if record.get('id')==value.get('last_transaction') and record.get('status')=='undone':
                return True,None  # an external undo requires an explicit state load
            if record.get('status')!='applied' or record.get('created','')<=value.get('active_updated',''):continue
            for change in record.get('changes',[]):
                state=change.get('development_state')
                if state:return True,state['champ']
        return bool(value.get('managed')),value.get('active_champ')

    def capture(self,cid,name,value):
        params={}
        for ident,fields in self.originals().items():
            car=self.dev.editor._car(ident)
            current={p.id:p.value for p in car.parameters}
            if not set(fields)<=set(current):raise ValueError('Research parameters changed in '+car.name+'. Rescan and review this mod version.')
            params[ident]={key:current[key] for key in fields}
        snapshot={'id':uuid.uuid4().hex,'champ':cid,'name':name,'created':datetime.now(timezone.utc).isoformat(),
                  'cars':params,'human_levels':self.human_levels(cid,value),
                  'source_fingerprints':{k:self.dev.editor._car(k).fingerprint for k in params}}
        value['snapshots'].append(snapshot)
        return snapshot

    def save(self,cid,body):
        with self.dev.lock,self.dev.editor.lock:
            name=str(body.get('name') or 'Championship R&D state').strip()
            if not 1<=len(name)<=100:raise ValueError('Use a state name of 1 to 100 characters.')
            value=self.read();managed,active=self.active(value)
            if managed and active!=cid:raise ValueError('Load this championship or reset research for it before saving its active car state.')
            snapshot=self.capture(cid,name,value)
            value.update(managed=True,active_champ=cid,active_human_levels=snapshot['human_levels'],
                         active_updated=datetime.now(timezone.utc).isoformat())
            self.write(value)
            return snapshot

    def status(self,cid):
        value=self.read();managed,active=self.active(value)
        return {'managed':managed,'active_champ':active,'is_active':not managed or active==cid,
                'snapshots':[{k:s[k] for k in ('id','name','created','champ')}|{'cars':len(s['cars'])}
                             for s in value['snapshots'] if s['champ']==cid]}

    def human_levels(self,cid,value=None):
        value=value or self.read();managed,active=self.active(value)
        if managed and active!=cid:return {}
        levels=dict(value.get('active_human_levels',{})) if managed else {}
        if self.dev.editor.game is None:return levels
        cutoff=value.get('active_updated','') if managed else ''
        for _,record in transactions(self.dev.editor.install_dir/'backups'):
            if record.get('status')!='applied' or record.get('created','')<=cutoff:continue
            marker=next((c.get('development_state') for c in record.get('changes',[]) if c.get('development_state')),None)
            if marker and marker['champ']==cid:
                levels=dict(marker.get('human_levels',{}));cutoff=record['created'];break
        plans={p['id']:p for p in self.dev.plans(cid)}
        for _,record in transactions(self.dev.editor.install_dir/'backups'):
            if record.get('status')!='applied' or record.get('created','')<=cutoff:continue
            for change in record.get('changes',[]):
                ref=change.get('development',{})
                if ref.get('champ')==cid and ref.get('plan') in plans:
                    for area,count in plans[ref['plan']].get('upgrades',{}).items():levels[area]=levels.get(area,0)+count
        return levels

    def preview(self,cid,body):
        with self.dev.lock,self.dev.editor.lock:
            value=self.read();originals=self.originals()
            kind=body.get('kind')
            snapshot=None
            if kind=='load':
                snapshot=next((s for s in value['snapshots'] if s['id']==body.get('state') and s['champ']==cid),None)
                if snapshot is None:raise ValueError('Choose a saved state belonging to this championship.')
            elif kind!='reset':raise ValueError('Choose reset or load.')
            targets=deepcopy(originals)
            if snapshot:
                for ident,fields in snapshot['cars'].items():targets.setdefault(ident,{}).update(fields)
            if not targets:raise ValueError('No journalled R&D changes exist to reset or restore yet.')
            requests=[]
            for ident,params in targets.items():
                if any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in params.values()):
                    raise ValueError('A saved research value is invalid.')
                car=self.dev.editor._car(ident)
                requests.append({'car':ident,'fingerprint':car.fingerprint,'parameters':params})
            review=self.dev.editor.preview(requests)
            marker={'champ':cid,'kind':kind,'state':snapshot['id'] if snapshot else None,
                    'human_levels':snapshot.get('human_levels',{}) if snapshot else {}}
            for change in self.dev.editor.prepared[review['token']]['changes']:
                change['development_state']=marker
            self.prepared={review['token']:{'created':time.monotonic(),'champ':cid,'marker':marker,
                                          'human_levels':snapshot.get('human_levels',{}) if snapshot else {}}}
            return review|{'kind':kind,'state_name':snapshot['name'] if snapshot else 'No R&D',
                           'note':'Only parameters previously changed by R&D are restored. Review intervening BOP changes to those same parameters. All affected files are backed up.'}

    def apply(self,cid,body):
        with self.dev.lock,self.dev.editor.lock:
            token=str(body.get('token'));review=self.prepared.pop(token,None)
            if not review or review['champ']!=cid or time.monotonic()-review['created']>600:
                raise ValueError('Review this championship state again before applying it.')
            from .liveries import _game_running
            if _game_running():raise ValueError('Close AMS2 before changing championship R&D states.')
            from .bop_files import sha
            pending=self.dev.editor.prepared.get(token)
            if pending is None:raise ValueError('Review this championship state again before applying it.')
            if any(sha(path)!=digest for path,digest in pending['guards'].items()):
                raise ValueError('Game files changed after the state review. Rescan and review again.')
            value=self.read();managed,active=self.active(value)
            # Checkpoint the outgoing state before any game change. This also
            # preserves an unsaved legacy championship when switching away.
            outgoing=active
            if not managed:
                outgoing=next((c.get('development',{}).get('champ') for _,r in transactions(self.dev.editor.install_dir/'backups')
                               if r.get('status')=='applied' for c in r.get('changes',[]) if c.get('development')),None)
            if outgoing:self.capture(outgoing,'Before state switch',value)
            self.write(value)
            result=self.dev.editor.apply(token)
            value.update(managed=True,active_champ=cid,active_updated=datetime.now(timezone.utc).isoformat(),
                         last_transaction=result.get('transaction'),active_human_levels=review['human_levels'])
            self.write(value)
            return result|{'active_champ':cid,'kind':review['marker']['kind']}
