import ctypes
import importlib.util
from pathlib import Path
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch

P=Path(__file__).resolve().parents[1]/'research/scripts/diagnose_shadow_fov_1121.py'
spec=importlib.util.spec_from_file_location('shadow_fov_diagnostic',P)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class DiagnosticTests(unittest.TestCase):
    def writer(self,complete=True):
        address=0x10114
        memory=SimpleNamespace(read=lambda a,n:m.encode_fov(64))
        s=SimpleNamespace(objects=SimpleNamespace(spectator_controller=0x10000),memory=memory)
        w=m.FovOnlyWriter.__new__(m.FovOnlyWriter)
        w.s=s;w.h=1;w.failed=False;w.calls=0;w.used=False;w.process={'pid':1}
        w.expected={address:m.encode_fov(64)};w.reserve=lambda:None;w.journal=lambda x:None
        self.api_calls=[]
        def write(handle,addr,buf,size,count):
            self.api_calls.append((addr.value,size,ctypes.string_at(buf,size)))
            count._obj.value=8 if complete else 4
            return True
        w.k=SimpleNamespace(WriteProcessMemory=write)
        return w

    def test_range_and_pair(self):
        self.assertEqual(struct.unpack('<2f',m.encode_fov(54)),(54,54))
        for v in (53.99,64.01,float('nan'),float('inf')):
            with self.assertRaises(m.CameraError):m.encode_fov(v)

    def test_only_fov_range_allowed(self):
        w=self.writer();w.expected[0x100ac]=b'0'*12
        with self.assertRaises(m.CameraError):w.commit_fov(64,lambda:None)
        self.assertEqual(self.api_calls,[])

    def test_guard_failure_prevents_write(self):
        w=self.writer()
        def guard():raise m.CameraError('Replay or pose changed')
        with self.assertRaises(m.CameraError):w.commit_fov(64,guard)
        self.assertEqual(self.api_calls,[])
        self.assertTrue(w.failed)

    def test_success_is_one_eight_byte_range(self):
        w=self.writer()
        with patch.object(m,'identity',return_value=w.process):w.commit_fov(54,lambda:None)
        self.assertEqual(self.api_calls,[(0x10114,8,m.encode_fov(54))])
        self.assertEqual(w.calls,1)

    def test_partial_write_cannot_retry(self):
        w=self.writer(complete=False)
        with patch.object(m,'identity',return_value=w.process):
            with self.assertRaises(m.CameraError):w.commit_fov(54,lambda:None)
            with self.assertRaises(m.CameraError):w.commit_fov(54,lambda:None)
        self.assertEqual(len(self.api_calls),1)

    def test_budget_prevents_extra_call(self):
        w=self.writer();w.calls=m.MAX_WRITES
        with self.assertRaises(m.CameraError):w.commit_fov(64,lambda:None)
        self.assertEqual(self.api_calls,[])

    def test_shadow_coverage_reads_correct_arrays(self):
        d=bytearray(0x5e0);struct.pack_into('<I',d,0,0x375b100)
        struct.pack_into('<I',d,0x294,3);struct.pack_into('<f',d,0x5dc,2048)
        struct.pack_into('<4f',d,0x550,64,128,256,0)
        struct.pack_into('<4f',d,0x560,1/32,1/16,1/8,0)
        s=SimpleNamespace(objects=SimpleNamespace(render=0x1000),live=lambda x:x,
                          memory=SimpleNamespace(u32=lambda a:0x2000,read=lambda a,n:bytes(d)))
        r=m.shadow_state(s,0x2000)
        self.assertEqual(r['coverage_width'],[64,128,256])
        self.assertEqual(r['texel_step'],[1/32,1/16,1/8])


if __name__=='__main__':unittest.main()
