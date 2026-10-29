import json,math,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from blitzcam.speed import validate_speed,shooting_duration,mean_rate,rate_integral,shooting_progress
from blitzcam.project import validate_project,edit_project,controls
from blitzcam.server import Workstation
from blitzcam.playback import PositionPlayback
from blitzcam.profile import CameraError

class ReplaySpeedTests(unittest.TestCase):
    def test_default_preserves_paused_workflow(self):
        self.assertEqual(validate_speed()['mode'],'paused')
        self.assertEqual(shooting_duration(8,validate_speed()),8)
    def test_curve_integral_and_both_clock_domains(self):
        s=validate_speed({'mode':'curve'})
        self.assertEqual(mean_rate(s),.4375)
        self.assertEqual(s['camera_clock'],'replay')
        s['camera_clock']='shooting'
        self.assertEqual(shooting_duration(8,s),8)
        s['camera_clock']='replay'
        self.assertAlmostEqual(shooting_duration(3.5,s),8)
    def test_fixed_rate_replay_domain_extends_shooting_duration(self):
        s=validate_speed({'mode':'fixed','rate':.25,'camera_clock':'replay'})
        self.assertEqual(shooting_duration(8,s),32)
        self.assertEqual(shooting_duration(40,s),160)
        s['rate']=.0625
        self.assertEqual(shooting_duration(120,s),1920)
        with self.assertRaises(ValueError):shooting_duration(120.1,s)

    def test_timing_rejection_explains_the_converted_duration(self):
        s=validate_speed({'mode':'fixed','rate':.0625,'camera_clock':'replay'})
        with self.assertRaises(ValueError) as caught:shooting_duration(121,s)
        self.assertIn('1936.000',str(caught.exception))
        self.assertIn('121.000',str(caught.exception))
        self.assertIn('0.0625×',str(caught.exception))
        with self.assertRaisesRegex(ValueError,'延长区间'):
            shooting_duration(.1,validate_speed({'mode':'fixed','rate':1,'camera_clock':'replay'}))
    def test_partial_curve_integrals_and_inverse(self):
        for interpolation in ('smooth','linear'):
            s=validate_speed({'mode':'curve','interpolation':interpolation,
                              'keyframes':[{'progress':0,'rate':.25},{'progress':1,'rate':1}]})
            self.assertAlmostEqual(rate_integral(s,.5),.125+(.75*(.09375 if interpolation=='smooth' else .125)))
            for p in (0,.001,.25,.5,.75,.99,1):
                self.assertAlmostEqual(shooting_progress(s,rate_integral(s,p)/mean_rate(s)),p)
        s=validate_speed({'mode':'fixed','rate':.25})
        self.assertEqual(rate_integral(s,.4),.1)
        self.assertAlmostEqual(shooting_progress(s,.4),.4)
    def test_curve_and_fixed_rate_validation(self):
        invalid=[{'mode':'reverse'},{'rate':True},{'rate':0},{'rate':-.25},{'rate':2},{'rate':float('nan')},
                 {'camera_clock':'wall'},{'interpolation':'bezier'},{'keyframes':[]},
                 {'keyframes':[{'progress':0,'rate':1},{'progress':0,'rate':.25}]},
                 {'keyframes':[{'progress':.1,'rate':1},{'progress':1,'rate':.25}]},
                 {'keyframes':[{'progress':0,'rate':None},{'progress':1,'rate':.25}]}]
        for value in invalid:
            with self.subTest(value=value),self.assertRaises(ValueError):validate_speed(value)
    def test_curve_minimum_rate_and_arbitrary_knots(self):
        s=validate_speed({'mode':'curve','keyframes':[{'progress':0,'rate':.0625},{'progress':.6,'rate':1},{'progress':1,'rate':.25}]})
        self.assertAlmostEqual(mean_rate(s),.56875)
        s['keyframes'][0]['rate']=.5
        self.assertEqual(validate_speed()['keyframes'][0]['rate'],1)
    def test_project_roundtrip_edit_and_backward_compatibility(self):
        data={'keyframes':[{'time_sec':t,'position':[1,2,3],'quaternion':[1,0,0,0],'horizontal_fov_deg':60}for t in (0,8)]}
        p=validate_project(data);self.assertEqual(p.replay_speed['mode'],'paused')
        data['replay_speed']={'mode':'curve','camera_clock':'replay'}
        p=validate_project(data);saved=p.to_dict();self.assertEqual(validate_project(saved).replay_speed,p.replay_speed)
        edit={'keyframes':controls(p),'replay_speed':saved['replay_speed']}
        self.assertEqual(edit_project(edit).replay_speed,p.replay_speed)
    def test_pause_is_explicit_and_only_after_linked_play_started(self):
        m=PositionPlayback('unused')
        with self.assertRaises(CameraError):m.pause()
        m.update(active=True,replay_controlled=True,state='playing');m.pause();self.assertTrue(m.pause_request)
        m.update(state='paused');m.pause(False);self.assertFalse(m.pause_request)
        with self.assertRaises(ValueError):m.pause(1)
    def test_speed_only_keeps_saved_project_and_uses_captured_pose(self):
        with tempfile.TemporaryDirectory()as tmp:
            w=Workstation(Path(tmp)/'p.json');w.stop.set();w.poller.join()
            data=w.project.to_dict();data['replay_speed']={'mode':'fixed','rate':.25,'camera_clock':'replay'};w.set_project(validate_project(data));before=w.project.to_dict()
            ref={'camera':{'position':[1,2,3],'quaternion':[1,0,0,0],'horizontal_fov_deg':70},'replay':{'paused':True}}
            w.session=Mock();w.session.capture.return_value=ref
            try:
                with patch.object(w.playback,'start')as start:
                    w.play(speed_only=True,seconds=12)
                    p=start.call_args.args[0];self.assertEqual(p.duration,12)
                    self.assertEqual(p.replay_speed['camera_clock'],'shooting')
                    self.assertEqual(p.keyframes[0].pose,p.keyframes[1].pose)
                    self.assertEqual(w.project.to_dict(),before)
                for seconds in (True,0,121,float('nan')):
                    with self.assertRaises(ValueError):w.play(speed_only=True,seconds=seconds)
            finally:w.close()

class TransportBoundsTests(unittest.TestCase):
    def test_configuration_writes_cannot_leave_owned_shared_block(self):
        from blitzcam.hook_transport import Remote
        r=Remote.__new__(Remote);r.write_bounds=(1000,1200);r.k=Mock();r.journal=Mock()
        for address,data in [(999,b'x'),(1200,b'x'),(1199,b'xx')]:
            with self.assertRaises(CameraError):r.write(address,data,'fixture')
        r.k.WriteProcessMemory.assert_not_called();r.journal.assert_not_called()
    def test_loaded_code_is_verified_with_aslr_and_corruption_rejected(self):
        from blitzcam.hook_transport import relocated_code,verify_module_code
        from blitzcam.playback import NATIVE
        manifest=json.loads((NATIVE/'position_hook_1121.json').read_text());dll=NATIVE/manifest['dll'];base=0x50000000
        sections=relocated_code(dll,base)
        m=Mock();m.read.side_effect=lambda address,size:bytes(sections[address-base])
        verify_module_code(m,base,dll)
        first=next(iter(sections));sections[first][0]^=1
        # Expected image is reconstructed afresh from disk, independent of fixture corruption.
        with self.assertRaises(CameraError):verify_module_code(m,base,dll)

class SettledFovTests(unittest.TestCase):
    def test_float_ulp_residue_is_accepted_but_visible_target_change_is_not(self):
        from blitzcam.hook_guards import validate_snapshot
        from blitzcam.pose import quaternion_from_angles
        from blitzcam.profile import PROFILE_1121
        s={'build':{'sha256':PROFILE_1121.sha256},'replay':{'paused':True},
           'camera':{'position':[1.,2.,3.],'quaternion':list(quaternion_from_angles(90,0,0)),'horizontal_fov_deg':80.},
           'native_controller':{'target_angles':[0.,0.],'smoothed_angles':[0.,0.],'target_position':[1.,2.,3.],
             'native_roll_radians':0.,'current_interface_fov':64.,'target_interface_fov':64.+.000004},
           'raw_camera':{'base_roll_deg':0.,'interface_fov':64.,'aspect':16/9,'fov_scale':1.25}}
        validate_snapshot(s)
        s['native_controller']['target_interface_fov']=64.001
        with self.assertRaises(CameraError):validate_snapshot(s)
