"""Rate-based AI research, restricted to explicitly AI-exclusive car models."""
import json
import math
import re
import uuid
from .weekends import connection,weekends
from .bop_files import transactions


def normalized(value):return re.sub(r'[^a-z0-9]','',str(value).lower())


class AIResearch:
    AREAS=('power','drag','efficiency','reliability','cooling','weight')
    def __init__(self,development):self.dev=development

    def read(self,cid):
        con=connection(self.dev.lib._db(cid))
        try:
            row=con.execute("SELECT value FROM meta WHERE key='ai_development'").fetchone()
            return json.loads(row['value']) if row else {'enabled':False,'rate_pct':100,'start_round':1,'ledger':{},'processed':[],'jobs':[]}
        finally:con.close()

    def write(self,cid,value):
        con=connection(self.dev.lib._db(cid))
        try:
            with con:con.execute("INSERT INTO meta(key,value) VALUES('ai_development',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(value,allow_nan=False),))
        finally:con.close()

    def eligibility(self,cid):
        cfg=self.dev.lib.champ_config(cid)
        human=set();ai=set();unknown=[]
        for driver in cfg.drivers:
            binding=driver.get('livery') or {}
            name=binding.get('recorded_car') or binding.get('car_name') or driver.get('car')
            if driver.get('role','human')=='ai':
                if name:ai.add(normalized(name))
            elif name:human.add(normalized(name))
            else:unknown.append(driver.get('display',driver.get('key','Human')))
        # Include real recorded human model use as well as roster assignments.
        con=connection(self.dev.lib._db(cid))
        try:
            human.update(normalized(r['car']) for r in con.execute("SELECT DISTINCT car FROM entrant WHERE is_ai=0 AND car IS NOT NULL"))
        finally:con.close()
        binding=self.dev.config(cid)
        if binding.get('telemetry_car'):human.add(normalized(binding['telemetry_car']))
        matches={}
        for car in self.dev.editor.cars.values():matches.setdefault(normalized(car.name),[]).append(car)
        human_sources={(role,source.canonical) for name in human for car in matches.get(name,[])
                       for role,sources in car.sources.items() if role in ('cdf','edf','gdf') for source in sources}
        eligible=[];held=[]
        for name in sorted(ai):
            options=matches.get(name,[])
            if unknown:reason='Assign cars to all human drivers before AI-only physics changes.'
            elif name in human:reason='This car model is also used by a human.'
            elif len(options)!=1:reason='The assigned AI model does not match one unambiguous installed car.'
            elif any((role,source.canonical) in human_sources for role,sources in options[0].sources.items()
                     if role in ('cdf','edf','gdf') for source in sources):
                reason='This AI model shares editable physics with a human car.'
            else:
                eligible.append(options[0].id);continue
            held.append({'model':options[0].name if options else name,'reason':reason})
        return eligible,held,unknown

    def status(self,cid):
        value=self.read(cid);eligible,held,unknown=self.eligibility(cid)
        return {**value,'eligible_cars':[{'id':k,'name':self.dev.editor._car(k).name} for k in eligible],
                'held_cars':held,'unassigned_humans':unknown,
                'rate_description':'100% earns one minor upgrade level per eligible car per weekend, distributed across supported research areas. No AI practice goals are evaluated.'}

    def configure(self,cid,body):
        enabled=body.get('enabled');rate=body.get('rate_pct')
        if not isinstance(enabled,bool) or isinstance(rate,bool) or not isinstance(rate,(int,float)) or not math.isfinite(rate) or not 0<=rate<=200:
            raise ValueError('AI research needs an on/off choice and a rate from 0 to 200%.')
        with self.dev.lock,self.dev.lib.lock,self.dev.editor.lock:
            value=self.read(cid)
            if enabled and not value['enabled']:
                completed=[w['round'] for w in weekends(self.dev.lib,cid) if w.get('race')]
                value['start_round']=max(completed,default=0)+1
            value.update(enabled=enabled,rate_pct=float(rate))
            self.write(cid,value)
            return self.status(cid)

    def advance(self,cid):
        from .development import eligible_fields,MAX_LEVEL,BY_ID
        from .liveries import _game_running
        with self.dev.lock,self.dev.lib.lock,self.dev.editor.lock:
            value=self.read(cid)
            if not value['enabled'] or value['rate_pct']==0:return
            if self.dev.editor.game is None:self.dev.editor.scan()
            managed,active=self.dev.states.active()
            if managed and active!=cid:return
            eligible,_,_=self.eligibility(cid)
            for weekend in weekends(self.dev.lib,cid):
                if weekend['round']<value['start_round'] or not (weekend.get('practice2') or weekend.get('race')):continue
                role='practice2' if weekend.get('practice2') else 'race'
                if (weekend.get('sessions',{}).get(role) or {}).get('status')!='complete':continue
                for ident in eligible:
                    key=str(weekend['round'])+':'+ident
                    if key in value['processed']:continue
                    car=self.dev.editor._car(ident)
                    ledger=value['ledger'].setdefault(ident,{'credit':0.,'levels':{}})
                    total=ledger['credit']+value['rate_pct']/100
                    count=int(total+1e-9);ledger['credit']=round(total-count,6)
                    upgrades={}
                    for _ in range(count):
                        areas=[a for a in self.AREAS if ledger['levels'].get(a,0)<MAX_LEVEL and eligible_fields(car,a)[0]]
                        if not areas:break
                        area=min(areas,key=lambda a:(ledger['levels'].get(a,0),self.AREAS.index(a)))
                        ledger['levels'][area]=ledger['levels'].get(area,0)+1
                        upgrades[area]=upgrades.get(area,0)+1
                    if upgrades:value['jobs'].append({'id':uuid.uuid4().hex,'car':ident,'round':weekend['round'],
                        'upgrades':upgrades,'fingerprint':car.fingerprint,'state':'queued'})
                    value['processed'].append(key)
            self.write(cid,value)  # reserve exactly-once work before game mutations
            if _game_running():return
            journal=[r for _,r in transactions(self.dev.editor.install_dir/'backups') if r.get('status')=='applied']
            for job in value['jobs']:
                if job['state']=='applied' or job['car'] not in eligible:continue
                existing=next((r for r in journal if any(c.get('development',{}).get('ai_job')==job['id'] for c in r.get('changes',[]))),None)
                if existing:
                    job.update(state='applied',transaction=existing['id']);continue
                car=self.dev.editor._car(job['car'])
                if car.fingerprint!=job['fingerprint']:
                    job.update(state='blocked',error='Car physics changed after the AI upgrade was queued. Review its BOP before retrying.');continue
                params={}
                for area,levels in job['upgrades'].items():
                    for field in eligible_fields(car,area)[0]:
                        target=field.value*BY_ID[area][4]**levels
                        if field.fmt!='f' and not field.promotable:target=round(target)
                        if target!=field.value:params[field.id]=target
                if not params:
                    job.update(state='blocked',error='No representable supported upgrade.');continue
                review=self.dev.editor.preview([{'car':car.id,'fingerprint':car.fingerprint,'parameters':params}])
                for change in self.dev.editor.prepared[review['token']]['changes']:
                    change['development']={'champ':cid,'ai_job':job['id'],'round':job['round'],'rate_pct':value['rate_pct']}
                result=self.dev.editor.apply(review['token'])
                job.update(state='applied',transaction=result.get('transaction'));self.write(cid,value)
                # Multiple reserved rounds for the same model form a sequence,
                # but an unrelated edit must still invalidate the first guard.
                for following in value['jobs']:
                    if following['state']=='queued' and following['car']==car.id and following['fingerprint']==car.fingerprint:
                        following['fingerprint']=self.dev.editor._car(car.id).fingerprint
            self.write(cid,value)
