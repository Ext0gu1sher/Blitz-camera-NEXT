"""Synthetic Windows calls only: R3-F must never write position or orientation."""
from contextlib import ExitStack
from copy import deepcopy
import ctypes as C
import importlib.util
import json
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

SPEC=importlib.util.spec_from_file_location('fov_restore_under_test',
    Path(__file__).resolve().parents[1]/'research/scripts/restore_fov_1121_once.py')
r=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(r)


def snapshot(fov=54.):
    scale=1.2668826580047607
    return {'build':{'sha256':r.PROFILE_1121.sha256},'session_id':'same',
        'addresses':{'camera':'0x1000'},'replay':{'paused':True,'time':23.,'origin':9.,'rate':1.},
        'camera':{'position':[1.,2.,3.],'quaternion':list(r.quaternion_from_angles(-978.,-2.,0)),
                  'horizontal_fov_deg':fov*scale},
        'native_controller':{'target_angles':[1068.,2.],'smoothed_angles':[1068.,2.],
            'native_roll_radians':0.,'current_interface_fov':fov,'target_interface_fov':fov,
            'target_position':[1.,2.,3.],'input_vector_80':[0.,0.,0.],'input_vector_9c':[0.,0.,0.]},
        'raw_camera':{'base_roll_deg':0.,'aspect':1.8,'fov_scale':scale,'interface_fov':fov,'view':[1.,0.,0.,1.]}}


def animation(quiet=True):
    return {'owner':'0x123','field':'0x1114','jobs':{'reserved_id':1,'completed_id':1},
            'containers':[],'registered_or_chained_count':0,'observed_quiescent':quiet,'relevant':[]}


class FovPairChecks(unittest.TestCase):
    def test_valid_zoom_and_quaternion_sign(self):
        b=snapshot(59.);b['camera']['quaternion']=[-x for x in b['camera']['quaternion']]
        result=r.validate_pair(snapshot(),b)
        self.assertEqual(result['position_difference'],0.)
        self.assertEqual(result['orientation_difference_deg'],0.)
        self.assertAlmostEqual(result['horizontal_fov_difference_deg'],6.334413290023804)

    def test_pose_clock_hash_viewport_or_target_changes_rejected(self):
        cases=[('camera','position',[1.000001,2.,3.]),('native_controller','target_position',[2.,2.,3.]),
            ('native_controller','target_angles',[1068.0001,2.]),('native_controller','smoothed_angles',[1068.0001,2.]),
            ('native_controller','native_roll_radians',.001),('raw_camera','base_roll_deg',.001),
            ('raw_camera','view',[1.,0.,0.,1.000001]),('raw_camera','aspect',1.7),
            ('raw_camera','fov_scale',1.3),('replay','paused',False),('replay','time',24.),
            ('replay','origin',8.),('replay','rate',2.),('addresses','camera','other'),('build','sha256','other')]
        for parent,key,value in cases:
            with self.subTest(key=key):
                b=snapshot(59.);b[parent][key]=value
                with self.assertRaises(r.CameraError):r.validate_pair(snapshot(),b)

    def test_tiny_large_and_outside_native_fov_rejected(self):
        for fov in (54.,55.,70.,100.,float('nan')):
            with self.subTest(fov=fov),self.assertRaises(r.CameraError):r.validate_pair(snapshot(),snapshot(fov))

    def test_unsettled_or_wrong_projection_fov_rejected(self):
        for parent,key,value in [('native_controller','target_interface_fov',60.),
                                 ('raw_camera','interface_fov',54.),('camera','horizontal_fov_deg',72.)]:
            b=snapshot(59.);b[parent][key]=value
            with self.subTest(key=key),self.assertRaises(r.CameraError):r.validate_pair(snapshot(),b)


class CaptureChecks(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(r,'guard_battle'))
        self.extra=self.stack.enter_context(patch.object(r,'controller_extra',return_value={'input_bytes_10_2d':[0]*30}))
        self.session=Mock();self.session.capture.return_value=snapshot(59.)
        self.anim=Mock();self.anim.observe.return_value=animation()

    def test_busy_or_unknown_animation_path_rejected(self):
        self.anim.observe.return_value=animation(False)
        with self.assertRaises(r.CameraError):r.bracketed_capture(self.session,{},self.anim)

    def test_task_structure_changed_across_capture_rejected(self):
        after=animation();after['jobs']['reserved_id']=2
        self.anim.observe.side_effect=[animation(),after]
        with self.assertRaises(r.IncoherentSample):r.bracketed_capture(self.session,{},self.anim)

    def test_input_bytes_or_vectors_rejected(self):
        self.extra.return_value={'input_bytes_10_2d':[1]+[0]*29}
        with self.assertRaises(r.CameraError):r.bracketed_capture(self.session,{},self.anim)
        self.extra.return_value={'input_bytes_10_2d':[0]*30}
        self.session.capture.return_value['native_controller']['input_vector_80']=[1.,0.,0.]
        with self.assertRaises(r.CameraError):r.bracketed_capture(self.session,{},self.anim)


class OneWriteChecks(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.k=Mock();self.k.OpenProcess.return_value=123
        self.stack.enter_context(patch.object(r.C,'WinDLL',return_value=self.k))
        self.stack.enter_context(patch.object(r,'identity',return_value={'pid':1}))
        self.verify=self.stack.enter_context(patch.object(r,'verify_live',return_value=(snapshot(59.),animation(),{})))
        self.protection=4;self.byte_count=8;self.region_size=0x1000;self.calls=[]
        def query(handle,address,ptr,size):
            m=C.cast(ptr,C.POINTER(r.MEMORY_BASIC_INFORMATION)).contents
            m.BaseAddress=0x1000;m.RegionSize=self.region_size;m.State=0x1000;m.Type=0x20000;m.Protect=self.protection
            return size
        def write(handle,address,buffer,size,count):
            self.calls.append((address.value,C.string_at(buffer,size),size))
            C.cast(count,C.POINTER(C.c_size_t)).contents.value=self.byte_count
            return 1
        self.k.VirtualQueryEx.side_effect=query;self.k.WriteProcessMemory.side_effect=write
        self.session=SimpleNamespace(info=SimpleNamespace(pid=1),objects=SimpleNamespace(spectator_controller=0x1000),memory=Mock())
        self.session.memory.read.return_value=struct.pack('<2f',59.,59.)
        self.writer=r.OneFovWrite();self.journal=Mock();self.budget=Mock()

    def commit(self):
        return self.writer.commit(self.session,snapshot(),{},Mock(),{'pid':1},self.journal,self.budget)

    def test_exact_fov_pair_only_once_and_handle_closed(self):
        self.assertTrue(self.commit()['full_payload_written'])
        self.assertEqual(self.calls,[(0x1114,struct.pack('<2f',54.,54.),8)])
        self.budget.assert_called_once();self.k.OpenProcess.assert_called_once_with(0x438,False,1)
        self.k.CloseHandle.assert_called_once_with(123)
        with self.assertRaises(r.CameraError):self.commit()
        self.assertEqual(len(self.calls),1)

    def test_partial_write_or_exception_consumes_budget(self):
        self.byte_count=4
        self.assertFalse(self.commit()['full_payload_written'])
        with self.assertRaises(r.CameraError):self.commit()
        self.assertEqual(len(self.calls),1)
        self.writer=r.OneFovWrite();self.k.WriteProcessMemory.side_effect=OSError('synthetic')
        with self.assertRaises(OSError):self.commit()
        with self.assertRaises(r.CameraError):self.commit()
        self.assertEqual(self.budget.call_count,2)

    def test_readonly_or_truncated_region_never_written(self):
        for protection,size in [(2,0x1000),(4,0x118)]:
            self.protection=protection;self.region_size=size
            with self.assertRaises(r.CameraError):self.commit()
        self.k.WriteProcessMemory.assert_not_called();self.budget.assert_not_called()

    def test_identity_or_target_changes_after_journal_rejected(self):
        with patch.object(r,'identity',side_effect=[{'pid':1},{'pid':2}]):
            with self.assertRaises(r.CameraError):self.commit()
        self.session.memory.read.side_effect=[b'a'*8,b'b'*8]
        with self.assertRaises(r.CameraError):self.commit()
        self.k.WriteProcessMemory.assert_not_called()

    def test_mode_or_animation_changes_after_journal_rejected(self):
        self.verify.side_effect=[(snapshot(59.),animation(),{}),r.CameraError('no longer idle/paused')]
        with self.assertRaises(r.CameraError):self.commit()
        self.k.WriteProcessMemory.assert_not_called();self.budget.assert_not_called()

    def test_existing_budget_prevents_windows_call(self):
        self.budget.side_effect=FileExistsError('already consumed')
        with self.assertRaises(FileExistsError):self.commit()
        self.k.WriteProcessMemory.assert_not_called()


class HoldChecks(unittest.TestCase):
    def run_observe(self,bounce=False,projection_transition=False,persistent_mismatch=False,pose_change=False):
        now=[0.];calls=[0]
        def capture(*args):
            calls[0]+=1
            s=snapshot()
            if bounce and calls[0]==40:
                s['raw_camera']['interface_fov']=59.;s['camera']['horizontal_fov_deg']=59.*s['raw_camera']['fov_scale']
            if persistent_mismatch or (projection_transition and calls[0]==1):
                s['camera']['horizontal_fov_deg']=59.*s['raw_camera']['fov_scale']
            if pose_change:
                s['camera']['position'][0]+=.000001
            return s,animation()
        session=Mock();session.objects.spectator_controller=0x1000
        session.memory.read.return_value=struct.pack('<2f',54.,54.)
        with TemporaryDirectory() as d,patch.object(r,'bracketed_capture',side_effect=capture),\
             patch.object(r.time,'perf_counter',side_effect=lambda:now[0]),\
             patch.object(r.time,'sleep',side_effect=lambda value:now.__setitem__(0,now[0]+value)):
            return r.observe(session,snapshot(),{},Mock(),Path(d),0.)

    def test_correct_projection_and_unchanged_pose_hold_passes(self):
        result=self.run_observe()
        self.assertTrue(result['fov_return_and_hold_passed']);self.assertGreaterEqual(result['hold_valid_samples'],150)

    def test_single_rebound_fails_without_selecting_a_new_hold(self):
        result=self.run_observe(bounce=True)
        self.assertFalse(result['fov_return_and_hold_passed']);self.assertTrue(result['hold_failed'])

    def test_projection_transition_is_dropped_before_arrival_then_hold(self):
        result=self.run_observe(projection_transition=True)
        self.assertTrue(result['fov_return_and_hold_passed'])
        self.assertEqual(result['dropped_samples'],1)
        self.assertEqual(result['arrival_seconds_since_write_return'],.02)

    def test_persistent_projection_mismatch_never_passes(self):
        result=self.run_observe(persistent_mismatch=True)
        self.assertFalse(result['fov_return_and_hold_passed'])
        self.assertIsNone(result['arrival_seconds_since_write_return'])
        self.assertEqual(result['valid_samples'],0)

    def test_pose_change_is_fatal_even_with_projection_mismatch(self):
        result=self.run_observe(projection_transition=True,pose_change=True)
        self.assertFalse(result['fov_return_and_hold_passed'])
        self.assertEqual(result['dropped_samples'],0)
        self.assertIn('XYZ changed',result['failure'])


if __name__=='__main__':unittest.main()
