"""Headless UI acceptance against a synthetic replay and a fake playback worker.

This fixture never opens the game, starts a Hook, or launches a visible browser.
"""
from pathlib import Path
import json
import os
import subprocess
import tempfile
import threading
import zipfile
import time
from types import SimpleNamespace
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from blitzcam.server import Workstation, make_handler
from blitzcam.project import validate_project
from blitzcam.pose import quaternion_from_angles
from tests.test_replay_events import arena_payload, data_with_events

ROOT=Path(__file__).resolve().parents[1]


class ReplayFixture:
    def capture(self,require_paused=True):
        return {'camera':{'position':[0,0,20],'quaternion':list(quaternion_from_angles(0,0,0)),
                          'yaw_deg':0,'pitch_deg':0,'roll_deg':0,'horizontal_fov_deg':60},
                'replay':{'time':12,'paused':True,'rate':1},'quality':{}}
    def close(self):pass


class PlaybackFixture:
    def __init__(self):
        self.value={'state':'idle','active':False,'message':'测试回放已暂停。','progress':0,'hooks_detached':True}
        self.calls=[]
    def state(self):return dict(self.value)
    def prepare(self,project,reference,locate,adopt_session,orientation_enabled,fov_enabled):
        from blitzcam.replay_timeline import playback_window
        assert not locate,'Fixture expects playback'
        self.start(playback_window(project,reference),reference,False,orientation_enabled,fov_enabled)
    def start(self,project,reference,reverse,orientation_enabled,fov_enabled):
        self.calls.append({'reverse':reverse,'orientation_enabled':orientation_enabled,'fov_enabled':fov_enabled,'duration':project.duration,'timeline_start':project.start_time,'timeline_end':project.end_time})
        self.value.update(self.calls[-1],state='playing',active=True,message='模拟播放：不访问游戏。',progress=.35)
    def stop(self,wait=False):self.value.update(state='stopped',active=False,message='模拟播放已停止。')
    def pause(self,paused=True):self.value.update(state='paused' if paused else 'playing')


def main():
    with tempfile.TemporaryDirectory(dir=ROOT/'output') as tmp,patch('blitzcam.server.OUTPUT',Path(tmp)):
        app=Workstation(Path(tmp)/'project.json');app.stop.set();app.poller.join()
        def reset_editor_session():
            from blitzcam.editor_state import editor_state_path
            app.editor_state=None
            editor_state_path(Path(tmp),app.project_path).unlink(missing_ok=True)
        app.playback=PlaybackFixture();app.session=ReplayFixture();app.sample=app.session.capture()
        app.connection={'state':'connected','message':'合成测试回放；不访问实际游戏。'}
        app.set_project(validate_project({'keyframes':[
            {'time_sec':t,'position':p,'quaternion':list(quaternion_from_angles(i*30,5,0)),
             'horizontal_fov_deg':60+i*4,'name':f'测试机位 {i+1}'}
            for i,(t,p) in enumerate(zip((0,4,7,10),([0,0,20],[10,20,30],[20,4,25],[30,30,22])))],
            'replay_speed':{'mode':'curve','camera_clock':'shooting'}}))
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(app))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        env=dict(os.environ)
        env['NODE_PATH']=str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules')
        try:
            subprocess.run(['node',str(ROOT/'tools/test_overlay_ui.cjs'),f'http://127.0.0.1:{server.server_address[1]}'],cwd=ROOT,env=env,check=True)
            if [c['reverse'] for c in app.playback.calls]!=[False,True,False,True]:raise AssertionError(app.playback.calls)
            if not all(c['orientation_enabled'] and c['fov_enabled'] for c in app.playback.calls):raise AssertionError(app.playback.calls)
            if app.playback.calls[0]['duration']!=12:raise AssertionError(app.playback.calls)
            app.set_project(validate_project({'keyframes':[
                {'time_sec':t,'position':p,'quaternion':list(quaternion_from_angles(i*30,5,0)),
                 'horizontal_fov_deg':60+i*4,'name':f'绝对机位 {i+1}'}
                for i,(t,p) in enumerate(zip((12,16.8,20.4,24),([0,0,20],[10,20,30],[20,4,25],[30,30,22])))],
                'replay_speed':{'mode':'fixed','rate':1,'camera_clock':'replay'},
                'replay_timeline':{'time_basis':'replay','duration_sec':305.66,'work_start_sec':12,'work_end_sec':24}}))
            chosen=Path(tmp)/'chosen.wotbreplay'
            with zipfile.ZipFile(chosen,'w') as z:
                z.writestr('meta.json',json.dumps({'battleDuration':306.125,'version':'11.21'}))
                # Explicit arena BATTLE event at raw == ReplayPlayer origin:
                # the synthetic editor timeline has a zero-second pre-battle area.
                z.writestr('data.wotreplay',data_with_events([(8,4.25,arena_payload())]))
            # Model the fixture game's source identity for the main play guard.
            reset_editor_session()
            with patch('blitzcam.server.session_timeline',return_value={'replay_file':str(chosen)}):
                subprocess.run(['node',str(ROOT/'tools/test_replay_timeline_ui.cjs'),f'http://127.0.0.1:{server.server_address[1]}',str(chosen)],cwd=ROOT,env=env,check=True)
            before_interactions=app.project.to_dict()
            reset_editor_session()
            subprocess.run(['node',str(ROOT/'tools/test_timeline_interactions_ui.cjs'),f'http://127.0.0.1:{server.server_address[1]}'],cwd=ROOT,env=env,check=True)
            app.set_project(validate_project(before_interactions))
            # Supply independent tracks to compare every timestamp across modes.
            from blitzcam.channels import track_controls
            with_tracks=app.project.to_dict();with_tracks['camera_tracks']=track_controls(app.project)
            app.set_project(validate_project(with_tracks))
            reset_editor_session()
            subprocess.run(['node',str(ROOT/'tools/test_shooting_modes_ui.cjs'),f'http://127.0.0.1:{server.server_address[1]}'],cwd=ROOT,env=env,check=True)
            app.set_project(validate_project(before_interactions))
            reset_editor_session()
            opened=Path(tmp)/'电影 A & B.wotbreplay'
            with zipfile.ZipFile(opened,'w') as z:
                z.writestr('meta.json',json.dumps({'battleDuration':307.5,'version':'11.21'}))
                z.writestr('data.wotreplay',data_with_events([(8,4.25,arena_payload())]))
            app.stop.clear()  # The periodic reader was joined; allow the launch worker.
            def delayed_choice():
                time.sleep(.8)
                return opened
            with patch('blitzcam.memory._kernel',side_effect=AssertionError('launch inspected game')), \
                 patch('blitzcam.replay_launcher.locate_client',return_value=Path('wotblitz.exe')), \
                 patch('blitzcam.replay_launcher.choose_replay') as picker, \
                 patch('blitzcam.replay_launcher.launch_replay',return_value=SimpleNamespace(pid=65432,poll=lambda:None)) as launch:
                choices=iter((True,False))
                picker.side_effect=lambda:delayed_choice() if next(choices) else None
                subprocess.run(['node',str(ROOT/'tools/test_replay_open_ui.cjs'),f'http://127.0.0.1:{server.server_address[1]}',str(opened)],cwd=ROOT,env=env,check=True)
                if launch.call_count!=1 or picker.call_count!=2:raise AssertionError((launch.call_count,picker.call_count))
        finally:
            server.shutdown();server.server_close();thread.join();app.close()


if __name__=='__main__':main()
