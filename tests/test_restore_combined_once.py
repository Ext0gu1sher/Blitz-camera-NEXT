"""No live writes: bound combined stages and stop after partial/state failures."""
from contextlib import ExitStack
from copy import deepcopy
import ctypes as C
import importlib.util
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

SPEC=importlib.util.spec_from_file_location('combined_restore_under_test',
    Path(__file__).resolve().parents[1]/'research/scripts/restore_combined_1121_once.py')
r=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(r)


def snapshot(displaced=False):
    yaw,pitch,fov=(1043.,7.,59.)if displaced else(1063.,2.,54.)
    xyz=[105.,200.,30.]if displaced else[100.,200.,30.]
    scale=1.2668826580047607
    return {'build':{'sha256':r.PROFILE_1121.sha256},'session_id':'same','addresses':{'camera':'0x1000'},
        'replay':{'paused':True,'time':23.,'origin':9.,'rate':1.},
        'camera':{'position':xyz,'quaternion':list(r.quaternion_from_angles(90-yaw,-pitch,0)),
                  'horizontal_fov_deg':fov*scale},
        'native_controller':{'target_angles':[yaw,pitch],'smoothed_angles':[yaw,pitch],
            'native_roll_radians':0.,'current_interface_fov':fov,'target_interface_fov':fov,
            'target_position':xyz[:],'input_vector_80':[0.,0.,0.],'input_vector_9c':[0.,0.,0.]},
        'raw_camera':{'direction':[-.2,.97,-.03],'base_roll_deg':0.,'aspect':1.8,'fov_scale':scale,'interface_fov':fov},
        'quality':{'eye_error':0.,'rotation_error':0.,'vp_error':0.}}


def extra():
    return {'input_bytes_10_2d':[0]*30,'bounds_min':[-1000.]*3,'bounds_max':[1000.]*3,
            'position_boxes_begin_end':['0x0','0x0'],'scene_related_pointer_08':'0x99'}


class PlanChecks(unittest.TestCase):
    def test_displacement_is_planned_five_units_only(self):
        a=snapshot();g=r.make_goal(a,'prepare-displacement')
        self.assertTrue(g['planned_not_captured']);self.assertAlmostEqual(r.math.dist(a['camera']['position'],g['position']),5.,places=4)
        self.assertEqual(g['position'][2],a['camera']['position'][2])
        self.assertEqual([(n,o,len(b))for n,o,b in r.payloads(g,'prepare-displacement')],[('position',0xac,12)])

    def test_restore_exact_three_fields_and_no_roll(self):
        a=snapshot();g=r.make_goal(a,'restore');p=r.payloads(g,'restore')
        self.assertEqual([(n,o,len(b))for n,o,b in p],[('angles',0x58,8),('position',0xac,12),('fov',0x114,8)])
        self.assertEqual(p[0][2],struct.pack('<2f',1063.,2.));self.assertEqual(p[2][2],struct.pack('<2f',54.,54.))
        self.assertEqual(r.compare_pre(a,snapshot(True),'restore')['position_difference'],5.)

    def test_reject_wrong_mode_roll_identity_clock_or_scale(self):
        for parent,key,value in [('replay','paused',False),('replay','time',24.),('addresses','camera','other'),
            ('build','sha256','other'),('native_controller','native_roll_radians',.01),('raw_camera','aspect',2.)]:
            b=snapshot(True);b[parent][key]=value
            with self.subTest(key=key),self.assertRaises(r.CameraError):r.compare_pre(snapshot(),b,'restore')

    def test_reject_missing_component_excessive_displacement_or_turn_crossing(self):
        for parent,key,value in [('camera','position',[100.,200.,30.]),('camera','position',[130.,200.,30.]),
            ('native_controller','target_angles',[1083.,7.]),('camera','horizontal_fov_deg',54.*1.2668826580047607)]:
            b=snapshot(True);b[parent][key]=value
            with self.subTest(key=key),self.assertRaises(r.CameraError):r.compare_pre(snapshot(),b,'restore')
        with self.assertRaises(r.CameraError):r.compare_pre(snapshot(),snapshot(True),'prepare-displacement')

    def test_exact_segment_test_detects_thin_region_between_sample_points(self):
        self.assertTrue(r.segment_intersects([0.,0.,0.],[1.,0.,0.],[.0123,-1.,-1.,.0125,1.,1.]))
        self.assertFalse(r.segment_intersects([0.,2.,0.],[1.,2.,0.],[.0123,-1.,-1.,.0125,1.,1.]))
        s=Mock();e=extra();e['position_boxes_begin_end']=['0x2000','0x2018']
        s.memory.read.return_value=struct.pack('<6f',.0123,-1.,-1.,.0125,1.,1.)
        with self.assertRaises(r.CameraError):r.check_path(s,e,[0.,0.,0.],[1.,0.,0.])

    def test_expanded_trial_accepts_current_magnitude_but_keeps_hard_bounds(self):
        a=snapshot();b=snapshot(True)
        def pose(distance,yaw):
            b['camera']['position']=[100.+distance,200.,30.]
            b['native_controller']['target_position']=b['camera']['position'][:]
            b['native_controller']['target_angles']=[1063.-yaw,7.]
            b['native_controller']['smoothed_angles']=[1063.-yaw,7.]
            b['camera']['quaternion']=list(r.quaternion_from_angles(90-(1063.-yaw),-7.,0))
        pose(42.,53.5)
        with self.assertRaises(r.CameraError):r.compare_pre(a,b,'restore')
        limits=r.trial_limits(50.,60.)
        self.assertEqual(r.compare_pre(a,b,'restore',limits)['position_difference'],42.)
        for distance,yaw in [(51.,53.5),(42.,61.)]:
            pose(distance,yaw)
            with self.subTest(distance=distance,yaw=yaw),self.assertRaises(r.CameraError):
                r.compare_pre(a,b,'restore',limits)

    def test_trial_limit_configuration_rejects_nonfinite_or_excessive_values(self):
        for distance,yaw in [(float('nan'),45.),(25.,float('inf')),(50.1,45.),(25.,60.1),(.4,45.),(25.,9.)]:
            with self.subTest(distance=distance,yaw=yaw),self.assertRaises(r.CameraError):
                r.trial_limits(distance,yaw)


class SequenceChecks(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.k=Mock();self.k.OpenProcess.return_value=123
        self.stack.enter_context(patch.object(r.C,'WinDLL',return_value=self.k))
        self.stack.enter_context(patch.object(r,'identity',return_value={'pid':1}))
        self.stack.enter_context(patch.object(r,'guard_battle'))
        self.stack.enter_context(patch.object(r,'controller_extra',side_effect=lambda s:extra()))
        self.stack.enter_context(patch.object(r,'verify_pre',return_value=(snapshot(True),{}, {},extra())))
        self.mem={0x1058:struct.pack('<2f',1043.,7.),0x10ac:struct.pack('<3f',105.,200.,30.),0x1114:struct.pack('<2f',59.,59.)}
        self.calls=[];self.partial=None;self.protection=4;self.size=0x1000
        def query(h,address,ptr,size):
            m=C.cast(ptr,C.POINTER(r.MEMORY_BASIC_INFORMATION)).contents
            m.BaseAddress=0x1000;m.RegionSize=self.size;m.State=0x1000;m.Type=0x20000;m.Protect=self.protection
            return size
        def read(address,size):return self.mem[address][:size]
        def write(h,address,buf,size,count):
            payload=C.string_at(buf,size);self.calls.append((address.value,payload,size))
            n=size-4 if self.partial==len(self.calls)else size
            C.cast(count,C.POINTER(C.c_size_t)).contents.value=n
            self.mem[address.value]=payload[:n]+self.mem[address.value][n:]
            return 1
        self.k.VirtualQueryEx.side_effect=query;self.k.WriteProcessMemory.side_effect=write
        self.s=Mock();self.s.info.pid=1;self.s.objects.spectator_controller=0x1000;self.s.memory.read.side_effect=read
        self.s._clock.return_value=snapshot()['replay'];self.s._native_controller.return_value=snapshot(True)['native_controller']
        self.s._camera.return_value=snapshot()['raw_camera'];self.anim=Mock();self.anim.observe.return_value={'observed_quiescent':True}
        self.w=r.BoundedWriteSequence();self.reserve=Mock();self.progress=Mock()

    def commit(self,operation='restore'):
        return self.w.commit(self.s,snapshot(),operation,r.make_goal(snapshot(),operation),{},self.anim,{'pid':1},Mock(),self.reserve,self.progress)

    def test_exact_order_sizes_and_no_second_sequence(self):
        result=self.commit();self.assertTrue(result['all_stages_fully_written'])
        self.assertEqual([(a,n)for a,b,n in self.calls],[(0x1058,8),(0x10ac,12),(0x1114,8)])
        self.reserve.assert_called_once();self.k.CloseHandle.assert_called_once_with(123)
        with self.assertRaises(r.CameraError):self.commit()
        self.assertEqual(len(self.calls),3)

    def test_prepare_writes_position_only(self):
        self.assertTrue(self.commit('prepare-displacement')['all_stages_fully_written'])
        self.assertEqual([(a,n)for a,b,n in self.calls],[(0x10ac,12)])

    def test_partial_at_each_stage_stops_remaining_and_prevents_retry(self):
        for index in (1,2,3):
            with self.subTest(index=index):
                self.mem.update({0x1058:struct.pack('<2f',1043.,7.),0x10ac:struct.pack('<3f',105.,200.,30.),0x1114:struct.pack('<2f',59.,59.)})
                self.calls=[];self.partial=index;self.w=r.BoundedWriteSequence()
                self.assertFalse(self.commit()['all_stages_fully_written'])
                self.assertEqual(len(self.calls),index)
                with self.assertRaises(r.CameraError):self.commit()

    def test_pause_change_between_stages_stops(self):
        changed=deepcopy(snapshot()['replay']);changed['paused']=False
        self.s._clock.side_effect=[snapshot()['replay'],changed]
        with self.assertRaises(r.CameraError):self.commit()
        self.assertEqual(len(self.calls),1)

    def test_completed_or_pending_target_mutation_stops(self):
        for address,payload in [(0x1058,struct.pack('<2f',1043.,7.)),(0x1114,struct.pack('<2f',60.,60.))]:
            with self.subTest(address=address):
                self.mem.update({0x1058:struct.pack('<2f',1043.,7.),0x10ac:struct.pack('<3f',105.,200.,30.),0x1114:struct.pack('<2f',59.,59.)})
                self.w=r.BoundedWriteSequence();self.calls=[]
                def progress(value):
                    if value.get('completed_stage')=='angles':self.mem[address]=payload
                self.progress.side_effect=progress
                with self.assertRaises(r.CameraError):self.commit()
                self.assertEqual(len(self.calls),1)

    def test_existing_budget_or_unsafe_page_prevents_all_calls(self):
        self.reserve.side_effect=FileExistsError('budget exists')
        with self.assertRaises(FileExistsError):self.commit()
        self.reserve.side_effect=None;self.protection=2
        with self.assertRaises(r.CameraError):self.commit()
        self.protection=4;self.size=0xb0
        with self.assertRaises(r.CameraError):self.commit()
        self.assertEqual(self.calls,[])

    def test_exception_during_second_stage_never_retries(self):
        original=self.k.WriteProcessMemory.side_effect
        def failing(*args):
            if len(self.calls)==1:raise OSError('synthetic stage two failure')
            return original(*args)
        self.k.WriteProcessMemory.side_effect=failing
        with self.assertRaises(OSError):self.commit()
        self.assertEqual(self.w.attempts,2)
        with self.assertRaises(r.CameraError):self.commit()
        self.k.CloseHandle.assert_called_once_with(123)


class ObserveChecks(unittest.TestCase):
    def observe(self,transition=False,rebound=False):
        now=[0.];calls=[0];saved=snapshot();goal=r.make_goal(saved,'restore')
        def capture(*args):
            calls[0]+=1;s=snapshot()
            if transition and calls[0]==1:s['camera']['horizontal_fov_deg']=59.*s['raw_camera']['fov_scale']
            if rebound and calls[0]==40:
                s['raw_camera']['interface_fov']=59.;s['camera']['horizontal_fov_deg']=59.*s['raw_camera']['fov_scale']
            return s,{}
        s=Mock();s.objects.spectator_controller=0x1000
        targets={0x1000+o:b for n,o,b in r.payloads(goal,'restore')};s.memory.read.side_effect=lambda a,n:targets[a]
        with TemporaryDirectory()as d,patch.object(r,'bracketed_capture',side_effect=capture),\
             patch.object(r.time,'perf_counter',side_effect=lambda:now[0]),\
             patch.object(r.time,'sleep',side_effect=lambda dt:now.__setitem__(0,now[0]+dt)):
            return r.observe(s,saved,goal,'restore',{},Mock(),Path(d),0.)

    def test_joint_pose_and_fov_hold_passes(self):
        self.assertTrue(self.observe()['return_and_hold_passed'])

    def test_projection_transition_dropped_without_false_early_arrival(self):
        result=self.observe(transition=True)
        self.assertTrue(result['return_and_hold_passed']);self.assertEqual(result['dropped_samples'],1)
        self.assertEqual(result['arrival_seconds_since_last_write_return'],.02)

    def test_single_valid_rebound_fails_without_new_hold(self):
        result=self.observe(rebound=True)
        self.assertFalse(result['return_and_hold_passed']);self.assertTrue(result['hold_failed'])


if __name__=='__main__':unittest.main()
