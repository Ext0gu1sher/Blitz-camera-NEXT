"""Fresh root discovery, toggle idempotence and supervisor tests; no game I/O."""
import ctypes as C
from pathlib import Path
import struct
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from blitzcam import freecamera as fc
from blitzcam.memory import ReadOnlyMemory, confirmed_exit_code
from blitzcam.profile import CameraError, PROFILE_1121
from blitzcam.reader import CameraSession
from blitzcam.seek_trial import clock


class RootsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name);self.cancel=threading.Event();self.report={'hooks_detached':True}
        self.data=bytearray(0xb000)
        self.memory=SimpleNamespace(info=SimpleNamespace(base=0x400000),profile=PROFILE_1121,
                                    read=self.read,u32=lambda a:struct.unpack('<I',self.read(a,4))[0],
                                    regions=lambda:[(0x1000,len(self.data))],exit_code=lambda:None)
        self.session=CameraSession(self.memory)
        self.player,self.context,self.hud,self.model=0x1000,0x2000,0x3000,0x4000
        self.owner,self.scene,self.game,self.free,self.controller,self.render=0x5000,0x6000,0x7000,0x8000,0x9000,0xa000
        for name,address in (('ReplayPlayer',self.player),('AvatarContextReplay',self.context),
                             ('GameSceneController',self.owner),('GameScene',self.scene),('GameCamera',self.game),
                             ('FreeCamera',self.free),('ReplayCameraController',self.controller),('RenderSystem',self.render)):
            self.u(address,self.session.vft[name])
        self.u(self.hud,0x3853e68);self.u(self.model,0x385332c)
        for a,b in ((self.hud+0x120,self.context),(self.hud+0x148,self.model),(self.context+0x1b0,self.player),
                    (self.owner+0x1c,self.scene),(self.owner+0x20,self.context),(self.owner+0x8c,self.game),
                    (self.owner+0x94,self.free),(self.owner+0x9c,self.controller),(self.controller+0x28,self.game),
                    (self.game+0x5b8,self.controller),(self.scene+0xa8,self.render),
                    (self.player+0x108,0xffffffff),(self.player+0xa0,1)):
            self.u(a,b)
        for offset in (0x11,0x12,0x35):self.data[self.player+offset-0x1000]=1
        for offset,value in ((0x18,19.08),(0x64,9),(0x14,1)):struct.pack_into('<f',self.data,self.player+offset-0x1000,value)
        self.mode(False)
        self.expected=clock(self.memory,self.player,self.session.vft['ReplayPlayer'])
        self.session.objects=SimpleNamespace(player=0xdead,scene=0xdead)  # Stale graph must be ignored.

    def read(self,a,n):
        if a<0x1000 or a+n>0x1000+len(self.data):raise CameraError('outside fixture')
        return bytes(self.data[a-0x1000:a-0x1000+n])

    def u(self,a,value):struct.pack_into('<I',self.data,a-0x1000,value)

    def mode(self,free):
        for a in (self.scene+0x120,self.scene+0x124,self.render+0xb4,self.render+0xb8):self.u(a,self.free if free else self.game)
        self.data[self.context+0x190-0x1000]=int(free)

    def ensure(self):return fc.ensure_free_camera(self.session,self.player,self.expected,self.folder,self.cancel,self.report)

    def test_discovers_tracked_chain_from_fresh_hud_and_scene(self):
        row,=fc.discover(self.session,self.player,self.cancel)
        self.assertEqual((row['mode'],row['player'],row['hud'],row['scene']),(0,self.player,self.hud,self.scene))

    def test_stale_hud_mismatched_context_flag_and_delayed_render_are_rejected(self):
        self.u(self.hud+0x120,0)
        self.assertEqual(fc.discover(self.session,self.player,self.cancel),[])
        self.u(self.hud+0x120,self.context)
        self.data[self.context+0x190-0x1000]=1
        self.assertEqual(fc.discover(self.session,self.player,self.cancel),[])
        self.mode(True);self.u(self.render+0xb8,self.game)
        self.assertEqual(fc.discover(self.session,self.player,self.cancel),[])

    def test_duplicate_hud_and_wrong_player_do_not_authorize_toggle(self):
        self.u(0xb000,0x3853e68);self.u(0xb120,self.context);self.u(0xb148,self.model)
        self.assertEqual(fc.discover(self.session,self.player,self.cancel),[])
        self.u(0xb000,0)
        self.assertEqual(fc.discover(self.session,0xdead,self.cancel),[])

    def test_already_free_is_idempotent_without_loading_or_arming_any_hook(self):
        self.mode(True)
        with patch.object(fc,'native_free_camera') as native:
            self.assertTrue(self.ensure());self.assertTrue(self.ensure());native.assert_not_called()
        self.assertEqual(self.report['freecamera']['requests'],0)
        self.assertEqual(self.session.objects.scene,0xdead)

    def test_tracked_switches_once_then_waits_for_consistent_render(self):
        real=fc.discover;calls=[]
        def discover(*args):
            calls.append(1)
            if len(calls)==2:return []  # Native return precedes render update.
            return real(*args)
        def native(*_):self.mode(True);return True
        with patch.object(fc,'configuration',return_value=Mock()),patch.object(fc,'native_free_camera',side_effect=native) as action,patch.object(fc,'discover',side_effect=discover):
            self.assertTrue(self.ensure());action.assert_called_once()
        self.assertEqual(len(calls),3);self.assertEqual(self.report['freecamera']['after']['mode'],1)

    def test_clock_change_stops_before_native_action(self):
        self.expected['raw']+=1
        with patch.object(fc,'native_free_camera') as action:
            with self.assertRaisesRegex(CameraError,'时刻或暂停状态'):self.ensure()
            action.assert_not_called()

    def test_cancel_after_dispatch_does_not_retry_or_report_restored(self):
        def cancel(*_):self.cancel.set();return True
        with patch.object(fc,'configuration',return_value=Mock()),patch.object(fc,'native_free_camera',side_effect=cancel) as action:
            self.assertFalse(self.ensure());action.assert_called_once()
        self.assertNotIn('after',self.report['freecamera'])

    def test_timeout_after_dispatch_never_toggles_twice(self):
        with patch.object(fc,'configuration',return_value=Mock()),patch.object(fc,'native_free_camera',return_value=True) as action,patch.object(fc.time,'monotonic',side_effect=[0,0,11]):
            with self.assertRaisesRegex(CameraError,'未重复切换'):self.ensure()
            action.assert_called_once()


class NativeSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name);self.cancel=threading.Event()
        self.report={'hooks_detached':True,'freecamera':{}}
        self.cfg=fc.Config(functor=125,tick_entry=126)
        self.h=fc.Header();self.calls=[];self.requests=1;self.exited=False;self.broken_detach=False;self.cancel_on_attach=False
        def read(a,n):
            self.assertEqual((a,n),(0x3000+C.sizeof(fc.Config),C.sizeof(fc.Header)))
            if self.exited:raise CameraError('process exited')
            return bytes(self.h)
        self.session=SimpleNamespace(memory=SimpleNamespace(read=read,u32=lambda _:126,exit_code=lambda:1 if self.exited else None))
        owner=self
        class Driver:
            def __init__(self,*_):self.k=SimpleNamespace(GetTickCount=lambda:123);self.detach_address=None
            def __enter__(self):return self
            def __exit__(self,*_):
                if self.detach_address:self.call(self.detach_address,0,'fallback detach')
            def load(self,_):return 0x1000
            def write(self,*_):pass
            def call(self,a,*_):
                owner.calls.append(a)
                if a==0x7000:
                    owner.h=fc.Header(status=4,detached=1,requests=owner.requests,job_calls=1,thread=2,job_thread=2,before_mode=0,after_mode=-1)
                    if owner.cancel_on_attach:owner.cancel.set()
                    if owner.crash_on_attach:owner.exited=True
                if a==0x8000 and owner.broken_detach:owner.h.active=1
                return 0
        self.crash_on_attach=False
        patch.object(fc,'Remote',Driver).start()
        patch.object(fc,'pe_exports',return_value={'g_shared':0x2000,'HookAttach@4':0x6000,'HookDetach@4':0x7000}).start()
        self.addCleanup(patch.stopall)

    def run_native(self):return fc.native_free_camera(self.session,self.cfg,self.folder,self.cancel,self.report)

    def test_single_dispatch_accepts_transient_render_mode_and_detaches(self):
        self.assertTrue(self.run_native());self.assertEqual(self.calls,[0x7000,0x8000])
        self.assertTrue(self.report['hooks_detached'])
        self.assertEqual(self.report['freecamera']['header']['after_mode'],-1)

    def test_bad_execution_audit_stops_without_retry(self):
        self.requests=2
        with self.assertRaisesRegex(CameraError,'执行记录异常'):self.run_native()
        self.assertEqual(self.calls,[0x7000,0x8000])

    def test_cancellation_detaches_and_does_not_redispatch(self):
        self.cancel_on_attach=True
        self.assertFalse(self.run_native());self.assertEqual(self.calls,[0x7000,0x8000])

    def test_process_exit_skips_all_later_remote_operations(self):
        self.crash_on_attach=True
        with self.assertRaisesRegex(CameraError,'process exited'):self.run_native()
        self.assertEqual(self.calls,[0x7000]);self.assertTrue(self.report['hooks_detached'])

    def test_failed_detachment_is_not_success(self):
        self.broken_detach=True
        with self.assertRaisesRegex(CameraError,'尚未退出'):self.run_native()
        self.assertFalse(self.report['hooks_detached'])


class ProcessExitTests(unittest.TestCase):
    def test_handle_query_distinguishes_confirmed_exit_from_alive_and_query_failure(self):
        m=ReadOnlyMemory.__new__(ReadOnlyMemory);m.handle=123
        def query(_,out):out._obj.value=self.code;return self.success
        m.k=SimpleNamespace(GetExitCodeProcess=query)
        self.code=259;self.success=True;self.assertIsNone(confirmed_exit_code(m))
        self.code=0xc0000005;self.assertEqual(confirmed_exit_code(m),0xc0000005)
        self.code=0;self.assertEqual(confirmed_exit_code(m),0)
        self.success=False;self.assertIsNone(confirmed_exit_code(m))
        m.handle=None;self.assertIsNone(confirmed_exit_code(m))


if __name__=='__main__':unittest.main()
