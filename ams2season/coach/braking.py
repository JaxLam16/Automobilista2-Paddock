"""Measured early brake inputs in practice; no causal or later-braking prescription."""
from statistics import median

from .corner_speed import CornerSpeedWatch
from .model import finite


class BrakingWatch(CornerSpeedWatch):
    def clear(self,reason='learning'):
        super().clear(reason)
        self.checks=[];self.comparison_reason='need_five_clean_intervals'

    @staticmethod
    def safe(tick,player):
        brake=finite(tick.local.get('brake'))
        age=finite(tick.local.get('local_sample_age_s'))
        return (CornerSpeedWatch.safe(tick,player) and brake is not None and 0<=brake<=1
                and age is not None and 0<=age<=1e-6)

    def feed(self,tick,player,*,active=True,reason='inactive'):
        age=finite(tick.local.get('local_sample_age_s'))
        if active and tick.session=='practice' and (age is None or not 0<=age<=1e-6):
            # A merely fresh as-of pedal row is not synchronized to this position.
            self.diagnostics['unaligned_pedal_samples']+=1
        return super().feed(tick,player,active=active,reason=reason)

    @staticmethod
    def phase(record,index):
        """One sustained brake episode, bracketed by released pedal, on a fixed section.

        Ignore tiny/brief taps. Two separate applications are ambiguous. Exact5m
        crossings interpolate the5% onset; this is pedal input, not brake pressure.
        Entry is20m before the inferred speed minimum, not a mapped turn-in/apex.
        """
        cells=record['cells'];lo,hi=index-40,index+12
        if not all(i in cells and finite(cells[i].get('brake')) is not None
                   and 0<=cells[i]['brake']<=1 for i in range(lo,hi+1)):return None
        episodes=[]
        for j in range(lo+3,hi-2):
            if not (cells[j-1]['brake']<.05<=cells[j]['brake']
                    and all(cells[k]['brake']>=.05 for k in range(j,j+4))
                    and max(cells[k]['brake'] for k in range(j-3,j))<=.05
                    and sum(cells[k]['brake']<=.02 for k in range(j-3,j))>=2):continue
            released=next((k for k in range(j+4,hi-1)
                           if all(cells[n]['brake']<=.02 for n in range(k,k+3))),None)
            if released is None:return None
            peak=max(cells[k]['brake'] for k in range(j,released))
            if peak<.15:continue
            part=(.05-cells[j-1]['brake'])/(cells[j]['brake']-cells[j-1]['brake'])
            episodes.append({'onset_m':(j-1+part)*5,'release_m':released*5,'brake_peak':peak,
                             'onset_low_m':min(cells[k]['sample_lo_m'] for k in (j-1,j)),
                             'onset_high_m':max(cells[k]['sample_hi_m'] for k in (j-1,j))})
        if len(episodes)!=1 or episodes[0]['onset_m']>(index-6)*5:return None
        return {'lap':record['lap'],'start_t':cells[lo]['t'],'end_t':cells[hi]['t'],
                'seconds':cells[hi]['t']-cells[lo]['t'],**episodes[0],
                'entry_m':(index-4)*5,
                'entry_speed_m_s':median(cells[k]['speed'] for k in range(index-5,index-2)),
                'approach_speed_m_s':median(cells[k]['speed'] for k in range(lo,lo+5))}

    def _patterns(self,tick):
        self.patterns={};self.checks=[];history,earlier,chosen=self.comparison_set(tick)
        self.comparison_reason=('need_five_clean_intervals' if len(history)<5
            or not all(r['clean'] for r in history[-3:]) else 'need_two_earlier_references'
            if len(earlier)<2 else 'no_repeatable_bends' if not chosen else 'no_repeated_early_brake_pattern')
        events=[]
        for index in chosen:
            self.diagnostics['sections_checked']+=1
            # Choose both references before looking at the recent brake inputs.
            records=sorted(earlier,key=lambda r:r['seconds'])[:2]
            refs=[self.phase(r,index) for r in records]
            recent=[self.phase(r,index) for r in history[-3:]]
            check={'distance_m':index*5,'reason':'ambiguous_or_incomplete_brake_phase'}
            self.checks.append(check)
            if any(r is None for r in refs+recent):
                self.diagnostics['ambiguous_or_incomplete_phases']+=1;continue
            check.update(reference_sections=refs,recent=recent)
            if (abs(refs[0]['onset_m']-refs[1]['onset_m'])>5
                    or abs(refs[0]['entry_speed_m_s']-refs[1]['entry_speed_m_s'])>.6
                    or abs(refs[0]['approach_speed_m_s']-refs[1]['approach_speed_m_s'])>1
                    or abs(refs[0]['seconds']-refs[1]['seconds'])>.15):
                check['reason']='reference_phases_disagree';continue
            onset=min(r['onset_m'] for r in refs);earliest=min(r['onset_low_m'] for r in refs)
            entry=min(r['entry_speed_m_s'] for r in refs)
            seconds=median(r['seconds'] for r in refs);approach=median(r['approach_speed_m_s'] for r in refs)
            for r in recent:
                r.update(earlier_by_m=onset-r['onset_m'],earlier_at_least_m=earliest-r['onset_high_m'],
                         entry_down_kph=(entry-r['entry_speed_m_s'])*3.6,
                         slower_by_s=r['seconds']-seconds,approach_comparable=abs(r['approach_speed_m_s']-approach)<=2)
            misses=[r for r in recent if r['earlier_at_least_m']>=8 and r['entry_down_kph']>=4
                    and r['slower_by_s']>=.15 and r['approach_comparable']]
            if len(misses)<2 or recent[-1] not in misses:
                check['reason']='no_repeated_early_brake_pattern';continue
            check['reason']='confirmed_pattern';key=str(index)
            value={'key':key,'distance_m':index*5,'reference_sections':refs,'recent':recent,
                   'earlier_by_m':min(r['earlier_by_m'] for r in misses),
                   'earlier_at_least_m':min(r['earlier_at_least_m'] for r in misses),
                   'entry_down_kph':min(r['entry_down_kph'] for r in misses),
                   'source':'earlier_local_speed_steering_and_brake_input',
                   'scope':'practice_local_self_comparison','entry_definition':'20m_before_inferred_speed_minimum',
                   'cause_attributed':False,'later_braking_recommended':False,'thermal_compensation':False,
                   'measured_t':tick.t,'token':f"brake:{index}:{history[-1]['lap']}:{tick.t}"}
            self.patterns[key]=value;events.append(value)
        if events:self.comparison_reason='confirmed_pattern'
        self.diagnostics['confirmed_patterns']+=len(events)
        return sorted(events,key=lambda v:v['earlier_by_m'],reverse=True)[:1]

    def status(self):
        return {**super().status(),'comparison_reason':self.comparison_reason,'last_checks':self.checks}
