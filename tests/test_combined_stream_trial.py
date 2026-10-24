"""Offline timing/stop checks only; no game access."""
from contextlib import ExitStack
import ctypes as C
import importlib.util
from pathlib import Path
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

SPEC=importlib.util.spec_from_file_location('combined_stream_under_test',
    Path(__file__).resolve().parents[1]/'research/scripts/play_combined_1121_trial.py')
r=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(r)


def endpoint(b=False):
    return {'camera':{'position':[42.,6.,44.]if b else[0.,0.,30.]},
        'native_controller':{'target_angles':[993.,17.]if b else[1046.,5.],
            'current_interface_fov':64. if b else 54.},'raw_camera':{'fov_scale':1.26688}}


class TimelineChecks(unittest.TestCase):
    def test_absolute_time_endpoints_midpoint_and_clamping(self):
        a,b=endpoint(),endpoint(True)
        self.assertEqual(r.target_at(a,b,-1)['position'],a['camera']['position'])
        self.assertEqual(r.target_at(a,b,9)['position'],b['camera']['position'])
        mid=r.target_at(a,b,4)
        self.assertEqual(mid['position'],[21.,3.,37.])
        self.assertEqual(mid['target_angles'],[1019.5,11.]);self.assertEqual(mid['interface_fov'],59.)
        # Independent calls never integrate prior scheduling errors.
        self.assertEqual(r.target_at(a,b,4),mid)

    def test_nonfinite_time_rejected(self):
        for t in [float('nan'),float('inf')]:
            with self.assertRaises(r.CameraError):r.target_at(endpoint(),endpoint(True),t)

    def test_lift_preserves_exact_endpoints_and_changes_only_middle_height(self):
        a,b=endpoint(),endpoint(True)
        for t in [0,8]:self.assertEqual(r.target_at(a,b,t,2),r.target_at(a,b,t))
        base=r.target_at(a,b,4);raised=r.target_at(a,b,4,2)
        self.assertEqual(raised['position'],[21.,3.,39.])
        self.assertEqual(base['target_angles'],raised['target_angles'])
        self.assertEqual(base['interface_fov'],raised['interface_fov'])
        for lift in [-1,2.1,float('nan')]:
            with self.assertRaises(r.CameraError):r.target_at(a,b,4,lift)

    def test_start_uses_captured_camera_xyz_after_previous_restore(self):
        a={'camera':{'position':[1.,2.,3.],'quaternion':[1.,0.,0.,0.],'horizontal_fov_deg':68.},
           'native_controller':{'target_position':[1.00001,2.,3.],'target_angles':[1046.,5.],
               'current_interface_fov':54.,'target_interface_fov':54.}}
        s={'camera':a['camera'].copy(),'native_controller':a['native_controller'].copy()}
        s['native_controller']['target_position']=a['camera']['position'][:]
        with patch.object(r,'validate_snapshot'),patch.object(r,'same_scene'):
            r.near_start(a,s)
            s['native_controller']['target_position']=[1.1,2.,3.]
            with self.assertRaises(r.CameraError):r.near_start(a,s)


class StreamChecks(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.k=Mock();self.k.OpenProcess.return_value=123
        self.stack.enter_context(patch.object(r.C,'WinDLL',return_value=self.k))
        self.stack.enter_context(patch.object(r,'identity',return_value={'pid':1}))
        self.goal=r.target_at(endpoint(),endpoint(True),0)
        self.mem={0x1000+off:data for name,off,data in r.payloads(self.goal,'restore')}
        self.s=SimpleNamespace(info=SimpleNamespace(pid=1),objects=SimpleNamespace(spectator_controller=0x1000),
            memory=SimpleNamespace(read=lambda address,n:self.mem[address][:n]))
        self.partial=False;self.calls=[];self.protect=4
        def query(h,address,ptr,size):
            page=C.cast(ptr,C.POINTER(r.MEMORY_BASIC_INFORMATION)).contents
            page.BaseAddress=0x1000;page.RegionSize=0x1000;page.State=0x1000;page.Type=0x20000;page.Protect=self.protect
            return size
        def write(h,address,buf,size,count):
            self.calls.append((address.value,size));n=size-4 if self.partial else size
            data=C.string_at(buf,size);C.cast(count,C.POINTER(C.c_size_t)).contents.value=n
            self.mem[address.value]=data[:n]+self.mem[address.value][n:];return 1
        self.k.VirtualQueryEx.side_effect=query;self.k.WriteProcessMemory.side_effect=write
        self.reserve=Mock();self.journal=Mock()
        self.w=r.StreamWriter(self.s,{'pid':1},self.mem,self.journal,self.reserve)

    def test_two_batches_keep_exact_ranges_and_reserve_only_once(self):
        with self.w:
            self.w.commit(self.goal,Mock())
            self.w.commit(r.target_at(endpoint(),endpoint(True),4),Mock())
        self.assertEqual(self.calls,[(0x1058,8),(0x10ac,12),(0x1114,8)]*2)
        self.assertEqual(self.w.batches,2);self.reserve.assert_called_once()
        self.k.CloseHandle.assert_called_once_with(123)
        with self.assertRaises(r.CameraError):self.w.commit(self.goal,Mock())

    def test_partial_stops_all_remaining_and_cannot_resume(self):
        with self.w:
            self.partial=True
            with self.assertRaises(r.CameraError):self.w.commit(self.goal,Mock())
            with self.assertRaises(r.CameraError):self.w.commit(self.goal,Mock())
        self.assertEqual(len(self.calls),1)

    def test_guard_change_between_stages_stops(self):
        with self.w:
            guard=Mock(side_effect=[None,r.CameraError('paused replay changed')])
            with self.assertRaises(r.CameraError):self.w.commit(self.goal,guard)
        self.assertEqual(len(self.calls),1)

    def test_external_target_change_prevents_next_batch(self):
        with self.w:
            self.w.commit(self.goal,Mock());self.mem[0x1114]=struct.pack('<2f',60.,60.)
            with self.assertRaises(r.CameraError):self.w.commit(self.goal,Mock())
        self.assertEqual(len(self.calls),3)

    def test_page_or_reserved_budget_prevents_writes(self):
        self.protect=2
        with self.assertRaises(r.CameraError):
            with self.w:pass
        self.protect=4;self.reserve.side_effect=FileExistsError('existing budget')
        with self.w:
            with self.assertRaises(FileExistsError):self.w.commit(self.goal,Mock())
        self.assertEqual(self.calls,[])

    def test_batch_cap_is_nonresumable(self):
        with self.w:
            self.w.batches=r.MAX_BATCHES
            with self.assertRaises(r.CameraError):self.w.commit(self.goal,Mock())
        self.assertEqual(self.calls,[])


if __name__=='__main__':unittest.main()
