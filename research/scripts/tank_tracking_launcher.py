"""Small standalone manual-test window; never starts tracking on launch."""
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from research.scripts import tank_tracking_trial as trial
from research.scripts.build_tank_tracking import build

PRESETS={
    '车后跟随':('chase',15,6),
    '侧面跟拍':('side',8,4),
    '绕车环拍':('orbit',10,5),
}


def ensure_driver():
    folder=trial.OUT/'native';manifest=folder/'position_hook_1121.json'
    try:
        m=json.loads(manifest.read_text())
        for key,file in [('production_source_sha256','blitzcam/native/position_hook_1121.c'),
                         ('extension_sha256','research/native/tank_tracking_1121.h')]:
            if m[key]!=hashlib.sha256((ROOT/file).read_text().encode()).hexdigest():raise ValueError('stale')
        dll=folder/m['dll']
        if dll.parent.resolve()!=folder.resolve() or hashlib.sha256(dll.read_bytes()).hexdigest()!=m['sha256']:raise ValueError('invalid')
    except (OSError,ValueError,KeyError):build()


class Window:
    def __init__(self,root):
        self.root=root;self.messages=queue.Queue();self.worker=None;self.cancel=threading.Event();self.closing=False
        root.title('坦克跟踪 · 实验测试');root.geometry('600x470');root.minsize(580,450)
        style=ttk.Style(root);style.configure('TLabel',font=('Microsoft YaHei UI',10));style.configure('TButton',font=('Microsoft YaHei UI',10),padding=(12,7))
        panel=ttk.Frame(root,padding=24);panel.pack(fill='both',expand=True)
        ttk.Label(panel,text='坦克跟踪测试',font=('Microsoft YaHei UI',18,'bold')).pack(anchor='w')
        ttk.Label(panel,text='1. 在游戏中打开本地回放，切到自由镜头并暂停。\n2. 停止工作台其他运镜，然后选择下面的预设。\n3. 点击开始后切回游戏，等待镜头准备完成。',justify='left').pack(anchor='w',pady=(12,16))
        ttk.Label(panel,text='目标：当前回放的录制者坦克').pack(anchor='w',pady=(0,12))
        fields=ttk.Frame(panel);fields.pack(fill='x')
        self.preset=tk.StringVar(value='车后跟随');self.seconds=tk.StringVar(value='8');self.rate=tk.StringVar(value='正常（1×）');self.smooth=tk.BooleanVar(value=False)
        self.inputs=[]
        for col,(label,var,values,width) in enumerate([
            ('镜头预设',self.preset,list(PRESETS),14),('回放片段 / 秒',self.seconds,['4','8','12'],10),('播放速度',self.rate,['正常（1×）','慢放（0.5×）'],15)]):
            ttk.Label(fields,text=label).grid(row=0,column=col,sticky='w',padx=(0,16),pady=(0,5))
            box=ttk.Combobox(fields,textvariable=var,values=values,state='readonly',width=width)
            box.grid(row=1,column=col,sticky='w',padx=(0,16));self.inputs.append(box)
        self.smoothing=ttk.Checkbutton(panel,text='柔和移动镜头（仍持续锁定坦克）',variable=self.smooth)
        self.smoothing.pack(anchor='w',pady=(16,10))
        buttons=ttk.Frame(panel);buttons.pack(fill='x',pady=(0,14))
        self.check=ttk.Button(buttons,text='检查回放',command=lambda:self.begin(False));self.check.pack(side='left')
        self.start=ttk.Button(buttons,text='开始测试',command=lambda:self.begin(True));self.start.pack(side='left',padx=10)
        self.stop=ttk.Button(buttons,text='停止',command=self.stop_run,state='disabled');self.stop.pack(side='left')
        self.status=tk.StringVar(value='准备好游戏后，先点“检查回放”。')
        ttk.Label(panel,textvariable=self.status,wraplength=540,justify='left').pack(anchor='w',fill='x')
        ttk.Label(panel,text='结束后会自动暂停回放；每次测试从当前时刻继续。\n观察坦克是否稳定居中、转弯是否跟得上、画面边缘有无闪烁。',wraplength=540,foreground='#666666').pack(anchor='w',side='bottom',pady=(12,0))
        root.protocol('WM_DELETE_WINDOW',self.close);root.after(100,self.poll)

    def busy(self,value):
        for button in (self.start,self.check):button.configure(state='disabled' if value else 'normal')
        self.stop.configure(state='normal' if value else 'disabled')
        self.smoothing.configure(state='disabled' if value else 'normal')
        for box in self.inputs:box.configure(state='disabled' if value else 'readonly')

    def begin(self,execute):
        if self.worker and self.worker.is_alive():return
        self.cancel.clear();self.busy(True)
        self.status.set('正在准备；可以切回游戏等待。' if execute else '正在检查回放，请稍候…')
        preset,distance,height=PRESETS[self.preset.get()]
        args=trial.parser().parse_args(['--preset',preset,'--seconds',self.seconds.get(),'--rate',
            '0.5' if self.rate.get().startswith('慢放') else '1','--distance',str(distance),'--height',str(height),
            '--fov','60','--smooth','0.15' if self.smooth.get() else '0',*(['--execute'] if execute else [])])
        self.worker=threading.Thread(target=self.work,args=(args,),daemon=True);self.worker.start()

    def work(self,args):
        log=io.StringIO()
        try:
            with redirect_stdout(log),redirect_stderr(log):
                if args.execute:ensure_driver()
                result=trial.run(args,stop_requested=self.cancel.is_set,on_progress=lambda value:self.messages.put(('progress',value)))
            if result.get('state')=='cancelled':message=result['message']
            elif not args.execute:message=f"已就绪：回放 {result['clock']['time']:.1f} 秒，已找到录制者坦克。可以开始测试。"
            else:message='测试结束，回放已暂停，镜头已交还。' if result['state']['state']=='completed' else '已停止测试，镜头已交还。'
            self.messages.put(('done',message))
        except Exception as exc:
            message=str(exc)
            if isinstance(exc,ConnectionError) or 'urlopen error' in message:message='无法连接工作台。请先打开 Blitz Camera，再重试。'
            self.messages.put(('done','未完成：'+message))
            log.write('\n'+repr(exc))
        finally:
            folder=trial.OUT/'launcher';folder.mkdir(parents=True,exist_ok=True)
            (folder/f'{time.time_ns()}.log').write_text(log.getvalue(),encoding='utf8')

    def stop_run(self):
        self.cancel.set();self.status.set('正在停止并交还镜头，请稍候…');self.stop.configure(state='disabled')

    def close(self):
        if self.worker and self.worker.is_alive():self.closing=True;self.stop_run()
        else:self.root.destroy()

    def poll(self):
        try:
            while True:
                kind,value=self.messages.get_nowait()
                if kind=='progress' and not self.cancel.is_set():self.status.set(value['message'])
                elif kind=='done':self.status.set(value)
        except queue.Empty:pass
        if self.worker and not self.worker.is_alive():
            self.worker=None;self.busy(False)
            if self.closing:self.root.destroy();return
        self.root.after(100,self.poll)


if __name__=='__main__':
    root=tk.Tk()
    if '--smoke-test' in sys.argv:root.withdraw()
    window=Window(root)
    if '--smoke-test' in sys.argv:
        root.update_idletasks()
        assert len(window.inputs)==3 and str(window.start['state'])=='normal'
        assert str(window.stop['state'])=='disabled'
        print('Tracking launcher widgets ready; no game action performed.');root.destroy()
    else:root.mainloop()
