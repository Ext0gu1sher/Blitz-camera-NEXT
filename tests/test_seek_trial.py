import ctypes as C
import math
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from blitzcam.seek_trial import Config,Header,FIELDS,prepare,clock,settled
from blitzcam.profile import CameraError

class SeekTrialTests(unittest.TestCase):
    def test_native_layout(self):
        self.assertEqual((C.sizeof(Config),C.sizeof(Header)),(100,56))
        self.assertEqual((Config.delta.offset,Header.requests.offset,Header.task_after.offset),(96,24,52))

    def test_absolute_target_uses_displayed_time_and_native_delta(self):
        src=SimpleNamespace(**{k:100+i for i,k in enumerate(FIELDS) if k not in ('magic','size','seek_entry')},raw=80.0,origin=9.5,initial_rate=1.0)
        session=SimpleNamespace(live=lambda va:va+0x1000)
        with patch('blitzcam.seek_trial.configuration',return_value=(src,{'node':123})):
            cfg,_=prepare(session,{'replay':{'time':70.5}},69.0)
        self.assertEqual((cfg.raw,cfg.origin,cfg.delta,cfg.rate),(80.,9.5,-1.5,1.))
        self.assertEqual(cfg.seek_entry,0x13e6ea0)
        self.assertEqual(cfg.magic,0x314b5342)

    def test_outside_bounded_trial_never_prepares_live_config(self):
        with patch('blitzcam.seek_trial.configuration') as fn:
            for target in (True,float('nan'),float('inf'),-1,10,130.001,9.999):
                with self.subTest(target=target),self.assertRaises(ValueError):
                    prepare(None,{'replay':{'time':10}},target)
            fn.assert_not_called()

    def test_project_seek_explicitly_extends_delta_without_weakening_research_default(self):
        src=SimpleNamespace(**{k:100+i for i,k in enumerate(FIELDS) if k not in ('magic','size','seek_entry')},raw=80.,origin=9.5,initial_rate=1.)
        session=SimpleNamespace(live=lambda va:va)
        with patch('blitzcam.seek_trial.configuration',return_value=(src,{})):
            cfg,_=prepare(session,{'replay':{'time':70.5}},670.5,max_delta=3600)
            self.assertEqual(cfg.delta,600.)
            with self.assertRaises(ValueError):prepare(session,{'replay':{'time':70.5}},670.5)
            with self.assertRaises(ValueError):prepare(session,{'replay':{'time':70.5}},3671.5,max_delta=3600)

    def test_clock_observer_accepts_reconstruction_flags_without_monotonic_guard(self):
        data=bytearray(0x10c);struct.pack_into('<I',data,0,123)
        struct.pack_into('<f',data,0x18,79.777);struct.pack_into('<f',data,0x64,9.377)
        struct.pack_into('<f',data,0x14,1);struct.pack_into('<I',data,0x108,7)
        data[0x2d]=1
        m=SimpleNamespace(read=lambda p,n:bytes(data))
        x=clock(m,1234,123)
        self.assertAlmostEqual(x['time'],70.4,places=4);self.assertFalse(settled(x,1))
        with self.assertRaises(CameraError):clock(m,1234,124)

    def test_all_lifecycle_conditions_required_for_completion(self):
        x=dict(active=1,paused=1,initialized=1,seek=0,waiting=0,task=0xffffffff,source=1,rate=1,raw=80.,origin=9.,time=71.)
        self.assertTrue(settled(x,1))
        for key,value in (('active',0),('paused',0),('initialized',0),('seek',1),('waiting',1),('task',5),('source',0),('rate',.25),('raw',math.nan)):
            with self.subTest(key=key):self.assertFalse(settled(dict(x,**{key:value}),1))

if __name__=='__main__':unittest.main()
