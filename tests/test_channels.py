import ctypes as C
import json
import unittest
from copy import deepcopy
from blitzcam.project import validate_project, edit_project, controls
from blitzcam.channels import ScalarTrack, track_controls
from blitzcam.playback import compile_positions
from blitzcam.pose import quaternion_from_angles
from blitzcam.hook_layout import plain


def fixture():
    data = {'keyframes':[{'time_sec':t,'position':[t,0,10],'quaternion':[1,0,0,0],'horizontal_fov_deg':60} for t in (0,8)],
            'position_interpolation':'linear','replay_speed':{'mode':'fixed','rate':.25}}
    data['camera_tracks'] = track_controls(validate_project(data))
    return data


class IndependentTrackTests(unittest.TestCase):
    def test_smooth_track_does_not_invent_reversal_after_a_close_key(self):
        # A large move over 22 ms followed by a small return used to inherit
        # the wrong tangent and travel another 27 units away before returning.
        for easing in ('linear','ease_in','ease_out','ease_in_out'):
            with self.subTest(easing=easing):
                track=ScalarTrack([{'time_sec':t,'value':v} for t,v in
                                   ((47.9,-58.5014),(47.922483,147.0458),(54.437395,138.2534))],
                                  'y',True,easing)
                values=[track.sample(47.922483+(54.437395-47.922483)*i/1000) for i in range(1001)]
                self.assertTrue(all(138.2534-1e-10<=v<=147.0458+1e-10 for v in values))
                self.assertTrue(all(b<=a+1e-10 for a,b in zip(values,values[1:])))

    def test_smooth_track_preserves_extrema_holds_and_two_point_lines(self):
        for values in ((0,1,1,2),(0,8,-1,4),(0,0,0,0),(8,2,1,-4)):
            track=ScalarTrack([{'time_sec':t,'value':v} for t,v in zip((0,.03,2,8),values)],'x',True,'linear')
            for i,(a,b) in enumerate(zip(track.rows,track.rows[1:])):
                with self.subTest(values=values,segment=i):
                    samples=[track.sample(a['time_sec']+(b['time_sec']-a['time_sec'])*j/100) for j in range(101)]
                    self.assertTrue(all(min(a['value'],b['value'])-1e-10<=v<=max(a['value'],b['value'])+1e-10 for v in samples))
                    self.assertAlmostEqual(samples[0],a['value'])
                    self.assertAlmostEqual(samples[-1],b['value'])
        two=ScalarTrack([{'time_sec':0,'value':10},{'time_sec':8,'value':-6}],'x',True,'linear')
        for t in (0,1,2,4,7,8):self.assertAlmostEqual(two.sample(t),10-2*t)
        hold=ScalarTrack([{'time_sec':4,'value':7}],'x',True,'linear')
        self.assertEqual([hold.sample(t) for t in (0,4,10)],[7,7,7])

    def test_compiled_smooth_path_stays_inside_each_authored_interval(self):
        data=fixture();data['position_interpolation']='smooth'
        data['camera_tracks']['x']=[{'time_sec':0,'value':-58.5},{'time_sec':.0225,'value':147},{'time_sec':8,'value':138}]
        trajectory=validate_project(data);rows,_=compile_positions(trajectory)
        tail=[r for r in rows if r.time>=.0225+1e-6]
        values=[r.position.x for r in tail]
        self.assertTrue(all(138-1e-5<=v<=147+1e-5 for v in values))
        self.assertTrue(all(b<=a+1e-5 for a,b in zip(values,values[1:])))

    def test_seven_independent_times_and_roundtrip(self):
        data=fixture()
        data['camera_tracks']['x'][1]['time_sec']=4
        data['camera_tracks']['zoom']=[{'time_sec':0,'value':60},{'time_sec':6,'value':90}]
        t=validate_project(data)
        self.assertEqual(t.duration,8)
        self.assertEqual(t.sample(4).position[0],8)
        self.assertEqual(t.sample(3).horizontal_fov_deg,75)
        self.assertEqual(t.keyframe_times(),[0,4,6,8])
        saved=t.to_dict()
        self.assertEqual(validate_project(json.loads(json.dumps(saved))).to_dict(),saved)
        self.assertEqual(edit_project({'keyframes':controls(t),'camera_track_controls':track_controls(t),
                                      'position_interpolation':'linear','replay_speed':t.replay_speed}).to_dict(),saved)

    def test_native_compiler_keeps_union_knots_and_evaluates_actual_tracks(self):
        data=fixture();data['camera_tracks']['zoom'].insert(1,{'time_sec':3.123,'value':85})
        data['camera_tracks']['yaw']=[{'time_sec':0,'value':0},{'time_sec':8,'value':360}]
        t=validate_project(data);rows,duration=compile_positions(t)
        key=next(r for r in rows if r.time==C.c_float(3.123).value)
        self.assertEqual(key.horizontal_fov,85)
        self.assertAlmostEqual(t.children['yaw'].sample(4),180)
        self.assertEqual(t.replay_speed['camera_clock'],'replay')
        self.assertEqual(duration,8)

    def test_bad_channels_cannot_silently_fall_back_to_full_pose(self):
        for change in ({'x':[]},{'pitch':[{'time_sec':0,'value':91}]},
                       {'zoom':[{'time_sec':0,'value':True}]},
                       {'x':[{'time_sec':1,'value':1},{'time_sec':1,'value':2}]}):
            data=fixture();data['camera_tracks'].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):validate_project(data)
        data=fixture();data['camera_tracks']['unexpected']=[]
        with self.assertRaises(ValueError):validate_project(data)

    def test_slowing_replay_does_not_retime_parameter_keys(self):
        data=fixture();a=validate_project(data)
        data['replay_speed']['rate']=.125;b=validate_project(data)
        self.assertEqual(a.camera_tracks,b.camera_tracks)
        self.assertEqual(a.sample(3),b.sample(3))

    def test_full_turn_is_preserved_by_scalar_angle_track_and_native_table(self):
        data=fixture()
        data['camera_tracks']['pitch']=[{'time_sec':0,'value':0}]
        data['camera_tracks']['yaw']=[{'time_sec':0,'value':0},{'time_sec':8,'value':360}]
        t=validate_project(data);rows,_=compile_positions(t)
        for when,angle in ((0,0),(2,90),(4,180),(6,270),(8,360)):
            expected=quaternion_from_angles(angle,0,t.children['roll'].sample(when))
            row=next(r for r in rows if r.time==when)
            dot=abs(sum(a*b for a,b in zip(expected,plain(row.quaternion))))
            self.assertAlmostEqual(dot,1,places=6)

class EaseSegmentTests(unittest.TestCase):
    def test_ease_rows_validated(self):
        for bad in ([.5,.5,.5], [.5,.5,.5,'x'], [-.1,0,1,1], [0,0,1.1,1], [0,-.1,1,1], [.1,.2,.3,'4']):
            with self.subTest(ease=bad):
                with self.assertRaises(ValueError):
                    ScalarTrack([{'time_sec':0,'value':0,'ease':bad},{'time_sec':1,'value':1}],'x',False,'linear')

    def test_ease_round_trips_through_project(self):
        data=fixture()
        data['camera_tracks']['x']=[{'time_sec':0,'value':0,'ease':[.42,0,.58,1]},{'time_sec':8,'value':20}]
        t=validate_project(data)
        self.assertEqual(t.camera_tracks['x'][0]['ease'],[.42,0,.58,1])
        self.assertEqual(t.to_dict()['camera_tracks']['x'][0]['ease'],[.42,0,.58,1])

    def test_ease_diagonal_is_linear_and_overrides_track_settings(self):
        for smooth,easing in ((False,'linear'),(True,'ease_in'),(True,'ease_in_out')):
            track=ScalarTrack([{'time_sec':0,'value':0,'ease':[0,0,1,1]},{'time_sec':4,'value':10}],'x',smooth,easing)
            for u in (0,.25,.5,.75,1):
                with self.subTest(smooth=smooth,easing=easing,u=u):
                    self.assertAlmostEqual(track.sample(4*u),10*u,places=6)

    def test_ease_known_curve_and_exact_endpoints(self):
        track=ScalarTrack([{'time_sec':2,'value':5,'ease':[.42,0,.58,1]},{'time_sec':6,'value':15}],'pitch',True,'ease_in')
        expected={0.1:0.019722453484501225,0.25:0.12916193122300323,0.5:0.5,
                  0.75:0.8708380687769968,0.9:0.9802775465154988}
        for u,progress in expected.items():
            with self.subTest(u=u):
                self.assertAlmostEqual(track.sample(2+4*u),5+10*progress,places=6)
        self.assertAlmostEqual(track.sample(2),5)
        self.assertAlmostEqual(track.sample(6),15)

    def test_segments_without_ease_unchanged(self):
        rows=[{'time_sec':0,'value':0},{'time_sec':2,'value':10,'ease':[.42,0,.58,1]},{'time_sec':6,'value':20}]
        eased=ScalarTrack(rows,'x',True,'ease_in')
        base=ScalarTrack([{k:v for k,v in r.items() if k!='ease'} for r in rows],'x',True,'ease_in')
        for u in (0.1,0.5,0.9):
            self.assertNotAlmostEqual(eased.sample(2+4*u),base.sample(2+4*u),places=3)
            self.assertAlmostEqual(eased.sample(2*u),base.sample(2*u),places=9)
