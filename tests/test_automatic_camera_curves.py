"""Camera curve regression checks; no connection to a game or user project."""
from copy import deepcopy
import json
import math
from pathlib import Path
import random
import shutil
import subprocess
import unittest

from blitzcam.channels import CHANNELS, ScalarTrack, track_controls
from blitzcam.project import controls, edit_project, validate_project
from blitzcam.playback import compile_positions


PRESETS = [[0,0,1,1], [.42,0,.58,1], [.42,0,1,1], [0,0,.58,1],
           [.83,0,.17,1], [.87,0,.13,1], [.55,0,1,.55], [0,.55,.45,1]]


def rows_at(points, ease=None):
    return [dict(time_sec=t, value=v, curve='auto', **({'ease':ease[:]} if ease else {}))
            for t,v in points]


def endpoint_state(piece, end):
    _,h,_,b = piece
    if end:
        return 5*(b[5]-b[4])/h,20*(b[5]-2*b[4]+b[3])/h**2
    return 5*(b[1]-b[0])/h,20*(b[2]-2*b[1]+b[0])/h**2


class AutomaticCameraCurvesTests(unittest.TestCase):
    def assert_join(self, track, t, expected=None):
        epsilon = min(t-track.times[0], track.times[-1]-t, .01)*.001
        left = (track.sample(t)-track.sample(t-epsilon))/epsilon
        right = (track.sample(t+epsilon)-track.sample(t))/epsilon
        self.assertAlmostEqual(left, right, delta=max(.015,abs(left)*.003))
        if expected is not None:
            self.assertAlmostEqual(left, expected, delta=.02)

    def test_templates_pass_through_instead_of_stopping_at_every_key(self):
        for preset in PRESETS:
            for name in CHANNELS:
                with self.subTest(preset=preset, channel=name):
                    track = ScalarTrack(rows_at([(0,10),(1,20),(3,40),(6,70)],preset),name,False,'ease_in_out')
                    self.assert_join(track,1,10)
                    self.assert_join(track,3,10)
                    for row in track.rows:
                        self.assertEqual(track.sample(row['time_sec']),row['value'])

    def test_nonuniform_times_values_reversals_and_holds(self):
        rng = random.Random(51)
        for preset in [None,*PRESETS]:
            for values in ([0,10,10,30],[0,10,-5,8],[30,20,19,-10],*[sorted(rng.uniform(-20,40) for _ in range(4)) for _ in range(8)]):
                track = ScalarTrack(rows_at(zip([0,.02,2,9],values),preset),'yaw',False,'ease_in')
                for a,b in zip(track.rows,track.rows[1:]):
                    samples = [track.sample(a['time_sec']+(b['time_sec']-a['time_sec'])*j/200) for j in range(201)]
                    self.assertTrue(all(math.isfinite(v) and min(a['value'],b['value'])-1e-7<=v<=max(a['value'],b['value'])+1e-7 for v in samples))
                    direction = 1 if b['value']>=a['value'] else -1
                    self.assertTrue(all((y-x)*direction>=-1e-7 for x,y in zip(samples,samples[1:])))
                # Include template subdivision knots, not just authored keys.
                pieces=[p for span in track.smooth_curves for p in span]
                for left,right in zip(pieces,pieces[1:]):
                    for a,b in zip(endpoint_state(left,True),endpoint_state(right,False)):
                        self.assertAlmostEqual(a,b,delta=1e-7*max(1,abs(a)))

    def test_selected_segment_matches_compatible_legacy_neighbors(self):
        rows=[{'time_sec':t,'value':10*t} for t in (0,1,3,4)]
        rows[1].update(curve='auto',ease=[.83,0,.17,1])
        track=ScalarTrack(rows,'x',False,'linear')
        self.assert_join(track,1,10)
        self.assert_join(track,3,10)
        for t in (.3,.8,3.2,3.9):self.assertAlmostEqual(track.sample(t),10*t)

    def test_template_keeps_its_rhythm_with_gentler_endpoint_acceleration(self):
        points=[(2,5),(6,15)]
        rows=rows_at(points,PRESETS[1])
        auto=ScalarTrack(rows,'x',False,'linear')
        legacy=ScalarTrack([{k:v for k,v in row.items() if k!='curve'} for row in rows],'x',False,'linear')
        # Auto mode is allowed to soften a template, but its quarter-point
        # rhythm remains anchored and the change stays small for this preset.
        for i in range(101):self.assertAlmostEqual(auto.sample(2+i/25),legacy.sample(2+i/25),delta=.15)
        for t in (2,3,4,5,6):self.assertAlmostEqual(auto.sample(t),legacy.sample(t),places=7)
        self.assertEqual(endpoint_state(auto.smooth_curves[0][0],False),(0,0))
        self.assertEqual(endpoint_state(auto.smooth_curves[0][-1],True),(0,0))
        plain=ScalarTrack(rows_at(points),'x',False,'ease_in_out')
        self.assertLess((plain.sample(2.001)-plain.sample(2))/.001,.003)
        self.assertLess((plain.sample(6)-plain.sample(5.999))/.001,.003)

    def test_all_properties_roundtrip_and_native_table_uses_new_curves(self):
        data={'easing':'ease_in_out','position_interpolation':'smooth',
              'keyframes':[{'time_sec':t,'position':[t,0,10],'quaternion':[1,0,0,0],'horizontal_fov_deg':60} for t in (0,1,3,6)]}
        data['camera_tracks']=track_controls(validate_project(data))
        for name in CHANNELS:
            data['camera_tracks'][name]=rows_at([(0,10),(1,20),(3,40),(6,70)],PRESETS[1])
        project=validate_project(data)
        saved=project.to_dict()
        restored=validate_project(json.loads(json.dumps(saved)))
        self.assertEqual(restored.to_dict(),saved)
        edited=edit_project({'keyframes':controls(project),'camera_track_controls':track_controls(project),
                             'position_interpolation':'smooth','easing':'ease_in_out','replay_speed':project.replay_speed})
        self.assertEqual(edited.to_dict(),saved)
        compiled,_=compile_positions(project)
        self.assertGreater(len(compiled),100)
        for row in compiled:
            pose=project.sample(row.time)
            self.assertAlmostEqual(row.position.x,pose.position[0],delta=1e-4)
            self.assertAlmostEqual(row.horizontal_fov,pose.horizontal_fov_deg,delta=1e-4)

    def test_invalid_mode_rejected_and_legacy_metadata_untouched(self):
        for mode in (None,False,1,'unknown'):
            with self.subTest(mode=mode),self.assertRaises(ValueError):
                ScalarTrack([{'time_sec':0,'value':1,'curve':mode}],'x',True,'linear')
        old=[{'time_sec':0,'value':1,'ease':PRESETS[1]},{'time_sec':2,'value':7}]
        source=deepcopy(old)
        self.assertEqual(ScalarTrack(old,'x',True,'ease_in').rows,source)
        self.assertEqual(old,source)

    def test_browser_and_python_evaluate_identically(self):
        node=shutil.which('node')
        if not node:self.skipTest('node unavailable')
        cases=[]
        for preset in [None,*PRESETS]:
            for smooth in (False,True):
                rows=rows_at([(0,10),(.02,30),(2,40),(9,60)],preset)
                cases.append(dict(rows=rows,smooth=smooth,easing='ease_in_out',times=[i/137*10-.1 for i in range(151)]))
                mixed=deepcopy(rows);del mixed[1]['curve']
                cases.append(dict(rows=mixed,smooth=smooth,easing='ease_in',times=cases[-1]['times']))
        proc=subprocess.run([node,str(Path(__file__).parent/'fixtures/curve_parity.mjs')],input=json.dumps(cases),capture_output=True,text=True,timeout=30)
        self.assertEqual(proc.returncode,0,proc.stderr)
        results=json.loads(proc.stdout)
        for case,values in zip(cases,results):
            track=ScalarTrack(case['rows'],'x',case['smooth'],case['easing'])
            for time,value in zip(case['times'],values):
                self.assertAlmostEqual(track.sample(time),value,places=8)


if __name__=='__main__':unittest.main()
