"""No real Windows calls: constrain R3-Y to its authorized eight target bytes."""
from contextlib import ExitStack
from copy import deepcopy
import ctypes as C
import importlib.util
from pathlib import Path
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

SPEC=importlib.util.spec_from_file_location('angle_restore_under_test',
    Path(__file__).resolve().parents[1]/'research/scripts/restore_yaw_pitch_1121_once.py')
r=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(r)


def snapshot(yaw=1055.,pitch=9.):
    return {'build':{'sha256':r.PROFILE_1121.sha256},'session_id':'same',
        'addresses':{'camera':'0x1000'},'replay':{'paused':True,'time':23.,'origin':9.,'rate':1.},
        'camera':{'position':[1.,2.,3.],'quaternion':list(r.quaternion_from_angles(90-yaw,-pitch,0)),
                  'horizontal_fov_deg':68.},
        'native_controller':{'target_angles':[yaw,pitch],'smoothed_angles':[yaw,pitch],
            'native_roll_radians':0.,'current_interface_fov':54.,'target_interface_fov':54.,
            'target_position':[1.,2.,3.]},
        'raw_camera':{'base_roll_deg':0.,'aspect':1.8,'fov_scale':1.26,'interface_fov':54.}}


class PairChecks(unittest.TestCase):
    def test_valid_both_axes_and_quaternion_sign(self):
        a,b=snapshot(),snapshot(1075.,14.)
        b['camera']['quaternion']=[-v for v in b['camera']['quaternion']]
        x=r.validate_pair(a,b)
        self.assertEqual(x['native_yaw_difference_deg'],20.)
        self.assertEqual(x['native_pitch_difference_deg'],5.)

    def test_reject_position_fov_roll_clock_identity_changes(self):
        for parent,key,value in [('camera','position',[1.1,2.,3.]),('camera','horizontal_fov_deg',70.),
            ('native_controller','native_roll_radians',.1),('raw_camera','base_roll_deg',1.),
            ('replay','paused',False),('replay','origin',8.),('build','sha256','bad'),
            ('addresses','camera','different'),('raw_camera','fov_scale',1.3)]:
            with self.subTest(key=key):
                b=snapshot(1075.,14.);b[parent][key]=value
                with self.assertRaises(r.CameraError):r.validate_pair(snapshot(),b)

    def test_reject_large_small_cross_turn_and_polar_changes(self):
        for angles in [(1056.,14.),(1105.,14.),(1075.,10.),(1075.,40.),(1085.,14.),(1075.,85.)]:
            with self.subTest(angles=angles):
                with self.assertRaises(r.CameraError):r.validate_pair(snapshot(),snapshot(*angles))

    def test_reject_unsettled_inconsistent_and_nonfinite_native_angles(self):
        for key,value in [('smoothed_angles',[1074.,14.]),('target_interface_fov',55.),
                          ('target_angles',[float('nan'),14.]),('target_angles',[1070.,14.])]:
            b=snapshot(1075.,14.);b['native_controller'][key]=value
            with self.subTest(key=key),self.assertRaises(r.CameraError):r.validate_pair(snapshot(),b)


class OneWriteTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.k=Mock();self.k.OpenProcess.return_value=123
        self.stack.enter_context(patch.object(r.C,'WinDLL',return_value=self.k))
        self.stack.enter_context(patch.object(r,'identity',return_value={'pid':1}))
        self.verify=self.stack.enter_context(patch.object(r,'verify_live',return_value=(snapshot(1075.,14.),{},{})))
        self.region_protection=4;self.byte_count=8;self.region_size=0x1000;self.calls=[]
        def query(handle,address,ptr,size):
            m=C.cast(ptr,C.POINTER(r.MEMORY_BASIC_INFORMATION)).contents
            m.BaseAddress=0x1000;m.RegionSize=self.region_size;m.State=0x1000;m.Type=0x20000;m.Protect=self.region_protection
            return size
        def write(handle,address,buffer,size,count):
            self.calls.append((address.value,C.string_at(buffer,size),size))
            C.cast(count,C.POINTER(C.c_size_t)).contents.value=self.byte_count
            return 1
        self.k.VirtualQueryEx.side_effect=query;self.k.WriteProcessMemory.side_effect=write
        self.s=SimpleNamespace(info=SimpleNamespace(pid=1),objects=SimpleNamespace(spectator_controller=0x1000),memory=Mock())
        self.s.memory.read.return_value=struct.pack('<2f',1075.,14.)
        self.w=r.OneAngleWrite();self.journal=Mock();self.budget=Mock()

    def commit(self):
        return self.w.commit(self.s,snapshot(),{},Mock(),{'pid':1},self.journal,self.budget)

    def test_exact_eight_bytes_once_and_handle_closed(self):
        self.assertTrue(self.commit()['full_payload_written'])
        self.assertEqual(self.calls,[(0x1058,struct.pack('<2f',1055.,9.),8)])
        self.k.OpenProcess.assert_called_once_with(0x438,False,1)
        self.k.CloseHandle.assert_called_once_with(123)
        self.budget.assert_called_once()
        with self.assertRaises(r.CameraError):self.commit()
        self.assertEqual(len(self.calls),1)

    def test_partial_write_cannot_retry(self):
        self.byte_count=4
        self.assertFalse(self.commit()['full_payload_written'])
        with self.assertRaises(r.CameraError):self.commit()
        self.assertEqual(len(self.calls),1)

    def test_windows_error_cannot_retry(self):
        self.k.WriteProcessMemory.side_effect=OSError('synthetic failure')
        with self.assertRaises(OSError):self.commit()
        with self.assertRaises(r.CameraError):self.commit()
        self.k.WriteProcessMemory.assert_called_once()
        self.k.CloseHandle.assert_called_once_with(123)

    def test_readonly_or_truncated_region_never_written(self):
        for protection,size in [(2,0x1000),(4,0x5c)]:
            self.region_protection=protection;self.region_size=size
            with self.assertRaises(r.CameraError):self.commit()
        self.k.WriteProcessMemory.assert_not_called();self.budget.assert_not_called()

    def test_identity_changed_after_journal_never_written(self):
        with patch.object(r,'identity',side_effect=[{'pid':1},{'pid':2}]):
            with self.assertRaises(r.CameraError):self.commit()
        self.k.WriteProcessMemory.assert_not_called()

    def test_target_changed_after_journal_never_written(self):
        self.s.memory.read.side_effect=[b'a'*8,b'b'*8]
        with self.assertRaises(r.CameraError):self.commit()
        self.k.WriteProcessMemory.assert_not_called()

    def test_mode_changed_after_journal_never_written(self):
        self.verify.side_effect=[(snapshot(),{},{}),r.CameraError('mode changed')]
        with self.assertRaises(r.CameraError):self.commit()
        self.k.WriteProcessMemory.assert_not_called()

    def test_existing_persistent_budget_never_written(self):
        self.budget.side_effect=FileExistsError('budget already exists')
        with self.assertRaises(FileExistsError):self.commit()
        self.k.WriteProcessMemory.assert_not_called()


if __name__=='__main__':unittest.main()
