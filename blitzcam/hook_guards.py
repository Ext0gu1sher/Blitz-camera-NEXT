"""Read-only guards extracted from the locally verified 11.21 experiments."""
import math,re,struct
from .profile import CameraError,IncoherentSample,SessionChanged,PROFILE_1121
from .pose import quaternion_from_angles

def angle_difference(a, b):
    na, nb = math.sqrt(sum(x*x for x in a)), math.sqrt(sum(x*x for x in b))
    if not na or not nb:
        raise CameraError('Invalid orientation.')
    dot = min(1., abs(sum(x*y for x,y in zip(a,b))/(na*nb)))
    return math.degrees(2*math.acos(dot))

def controller_extra(session):
    data = session.memory.read(session.objects.spectator_controller, 0x138)
    vector = lambda off: list(struct.unpack_from('<3f', data, off))
    return {'input_bytes_10_2d': list(data[0x10:0x2e]),
            'bounds_min': vector(0x30), 'bounds_max': vector(0x3c),
            'position_boxes_begin_end': [hex(x) for x in struct.unpack_from('<2I', data, 0x48)],
            'target_position': vector(0xac),
            'scene_related_pointer_08': hex(struct.unpack_from('<I', data, 8)[0])}

def battle_links(session):
    # Independently traced RTTI +128 update interface in this exact build.
    pattern = struct.pack('<I', session.live(0x37f8f70))
    result = []
    mem = session.memory
    for start, length in mem.regions():
        for address in range(start, start+length, 1024*1024):
            try:
                data = mem.read(address, min(1024*1024, start+length-address))
            except CameraError:
                continue
            for match in re.finditer(re.escape(pattern), data):
                p = address+match.start()
                if p % 4:
                    continue
                try:
                    context = mem.u32(p+0x120)
                    interface = mem.u32(p+0x128)
                    owner = mem.u32(p+0x150)
                    controller = mem.u32(owner+0x68)
                    if (context == session.objects.context and
                        interface == session.live(0x37f8fb0) and
                        controller == session.objects.spectator_controller):
                        result.append({'battle_controller': hex(p), 'context_at_120': hex(context),
                                       'owner_at_150': hex(owner), 'spectator_at_owner_68': hex(controller)})
                except CameraError:
                    pass
    return result

def u32(data, offset=0):
    return struct.unpack_from('<I', data, offset)[0]

def vector_pointers(mem, header):
    begin, end, cap = struct.unpack('<3I', header)
    if not (begin <= end <= cap and (end-begin) % 4 == 0 and
            (cap-begin) % 4 == 0 and cap-begin <= 16384):
        raise IncoherentSample('Invalid/bounded animation vector.')
    if end == begin:
        return []
    if begin < 0x10000 or begin % 4:
        raise IncoherentSample('Invalid animation vector address.')
    return list(struct.unpack('<'+'I'*((end-begin)//4), mem.read(begin, end-begin)))

class AnimationProbe:
    def __init__(self, session):
        self.s = session
        self.mem = session.memory
        self.core = self.mem.u32(session.live(0x4690a30))
        self.jobs = self.mem.u32(self.core)
        self.manager = self.mem.u32(self.core+0x44)
        self.owner = self.mem.u32(session.objects.spectator_controller+0x134)
        self.field = session.objects.spectator_controller+0x114
        self.guard()

    def guard(self):
        s, m = self.s, self.mem
        if (m.u32(s.live(0x4690a30)) != self.core or m.u32(self.core) != self.jobs or
            m.u32(self.core+0x44) != self.manager or
            m.u32(self.jobs) != s.live(0x372a4c4) or
            m.u32(s.objects.spectator_controller+0x134) != self.owner or
            m.u32(self.owner) != s.live(0x372adb4)):
            raise SessionChanged('Animation/core identity changed.')

    def jobs_header(self):
        # +10 is a waiter count, NOT an executing-job ID. +68..+9f is the
        # in-flight record copied out of the deque by 0x92aec0 before pop.
        d = self.mem.read(self.jobs, 0xa0)
        count, size = u32(d, 0x60), u32(d, 0x58)
        if size > 1048576 or (size and size & (size-1)) or count > size:
            raise IncoherentSample('Invalid/bounded main-thread job deque.')
        return {'reserved_id': u32(d, 0xc), 'waiters': u32(d, 0x10),
                'completed_id': u32(d, 0x14), 'queue_map': hex(u32(d, 0x54)),
                'queue_map_size': u32(d, 0x58), 'queue_start': u32(d, 0x5c),
                'queue_count': u32(d, 0x60), 'inflight_id': u32(d, 0x68),
                'inflight_mode': u32(d, 0x6c), 'inflight_origin_thread': u32(d, 0x70),
                'inflight_functor': hex(u32(d, 0x9c))}

    def containers(self):
        m = self.mem
        h = m.read(self.manager+4, 8)
        head, count = struct.unpack('<2I', h)
        if not 0 <= count <= 64 or head < 0x10000:
            raise IncoherentSample('Invalid animation map header.')
        head_bytes = m.read(head, 8)
        node, prev = u32(head_bytes), head
        nodes, entries, seen = [], [], set()
        while node != head:
            if node in seen or len(seen) >= count:
                raise IncoherentSample('Animation map cycle/count mismatch.')
            seen.add(node)
            d = m.read(node, 0x14)
            nxt, back, group, bucket = u32(d), u32(d, 4), u32(d, 8), u32(d, 0x10)
            if back != prev or not bucket:
                raise IncoherentSample('Animation map link mismatch.')
            vectors = m.read(bucket, 0x18)
            registered = vector_pointers(m, vectors[:12])
            update = vector_pointers(m, vectors[12:24])
            nodes.append((node, d.hex(), bucket, vectors.hex()))
            entries.append({'group': group, 'bucket': hex(bucket),
                            'registered': registered, 'update': update})
            prev, node = node, nxt
        if len(seen) != count or u32(head_bytes, 4) != prev:
            raise IncoherentSample('Animation map traversal incomplete.')
        if m.read(self.manager+4, 8) != h or m.read(head, 8) != head_bytes:
            raise IncoherentSample('Animation map changed during traversal.')
        for p, raw, bucket, vectors in nodes:
            if m.read(p, 0x14).hex() != raw or m.read(bucket, 0x18).hex() != vectors:
                raise IncoherentSample('Animation containers changed during traversal.')
        return entries

    def animation(self, p):
        if p < 0x10000 or p % 4:
            raise IncoherentSample('Invalid animation pointer.')
        d = self.mem.read(p, 0x50)
        result = {'address': hex(p), 'vft': hex(u32(d)), 'flags': u32(d, 0x18),
                  'owner': hex(u32(d, 0x2c)), 'next': hex(u32(d, 0x30)),
                  'track': u32(d, 0x34), 'group': u32(d, 0x48)}
        related = u32(d, 0x2c) == self.owner
        if u32(d) == self.s.live(0x375e610):
            # Only this verified type has an A8-byte layout.
            full = self.mem.read(p, 0xa8)
            get, put = u32(full, 0x74), u32(full, 0x9c)
            callbacks = []
            for ptr, preferred in ((get, 0x380c544), (put, 0x380c560)):
                if not ptr:
                    callbacks.append(None)
                    continue
                cb = self.mem.read(ptr, 8)
                callbacks.append({'address': hex(ptr), 'vft': hex(u32(cb)),
                                  'expected_type': u32(cb) == self.s.live(preferred),
                                  'float_address': hex(u32(cb, 4))})
            binding = any(cb and cb['expected_type'] and
                          cb['float_address'] == hex(self.field) for cb in callbacks)
            related = related or binding
            if related:
                result.update(float_animation={
                    'elapsed': struct.unpack_from('<f', full, 0x1c)[0],
                    'duration': struct.unpack_from('<f', full, 0x20)[0],
                    'progress': struct.unpack_from('<f', full, 0x24)[0],
                    'time_scale': struct.unpack_from('<f', full, 0x40)[0],
                    'end': struct.unpack_from('<f', full, 0xa0)[0],
                    'start': struct.unpack_from('<f', full, 0xa4)[0],
                    'getter': callbacks[0], 'setter': callbacks[1],
                    'binds_current_fov': binding, 'raw_hex': full.hex()})
        result['related'] = related
        return result

    def observe(self):
        self.guard()
        jobs_a = self.jobs_header()
        containers_a = self.containers()
        roots = {p for c in containers_a for key in ('registered', 'update') for p in c[key]}
        todo, found = list(roots), {}
        while todo:
            p = todo.pop()
            if p in found:
                continue
            if len(found) >= 512:
                raise IncoherentSample('Animation chain bound exceeded.')
            a = self.animation(p)
            found[p] = a
            if int(a['next'], 16):
                todo.append(int(a['next'], 16))
        for root in roots:
            chain_seen, p = set(), root
            while p:
                if p in chain_seen:
                    raise IncoherentSample('Animation next-chain cycle.')
                chain_seen.add(p)
                p = int(found[p]['next'], 16)
        jobs_b = self.jobs_header()
        containers_b = self.containers()
        if containers_a != containers_b or jobs_a != jobs_b:
            raise IncoherentSample('Animation/job structure changed across observation.')
        # Metadata may have changed even if vector headers did not.
        for p, a in found.items():
            d = self.mem.read(p, 0x50)
            if (hex(u32(d)), u32(d, 0x18), hex(u32(d, 0x2c)), hex(u32(d, 0x30)),
                u32(d, 0x34), u32(d, 0x48)) != tuple(a[k] for k in
                    ('vft', 'flags', 'owner', 'next', 'track', 'group')):
                raise IncoherentSample('Animation metadata changed across observation.')
        relevant = [a for a in found.values() if a['related']]
        no_jobs = (jobs_b['reserved_id'] != 0 and
                   jobs_b['queue_count'] == 0 and jobs_b['inflight_id'] == 0 and
                   jobs_b['inflight_functor'] == '0x0' and
                   jobs_b['reserved_id'] == jobs_b['completed_id'])
        self.guard()
        return {'owner': hex(self.owner), 'field': hex(self.field), 'jobs': jobs_b,
                'containers': containers_b, 'relevant': relevant,
                'registered_or_chained_count': len(found),
                'observed_quiescent': not relevant and no_jobs,
                'frame_synchronized': False, 'write_ready': False}

def structural_signature(observation):
    result = {k: observation[k] for k in ('owner', 'field', 'jobs', 'containers',
              'registered_or_chained_count', 'observed_quiescent')}
    relevant = []
    for a in observation['relevant']:
        item = {k: a[k] for k in ('address', 'vft', 'flags', 'owner', 'next', 'track', 'group')}
        if 'float_animation' in a:
            item['binding'] = {k: a['float_animation'][k] for k in
                ('duration', 'time_scale', 'start', 'end', 'getter', 'setter', 'binds_current_fov')}
        relevant.append(item)
    result['relevant'] = sorted(relevant, key=lambda a: a['address'])
    return result

def guard_battle(session, link):
    session._guard()
    p,owner = int(link['battle_controller'],16),int(link['owner_at_150'],16)
    for address,value in ((p,session.live(0x37f8f70)),(p+0x128,session.live(0x37f8fb0)),
        (p+0x120,session.objects.context),(p+0x150,owner),(owner+0x68,session.objects.spectator_controller)):
        if session.memory.u32(address) != value:
            raise CameraError('Battle-controller update chain changed.')

def bracketed_capture(session,link,animation):
    guard_battle(session,link)
    a = animation.observe()
    extra_a = controller_extra(session)
    snap = session.capture(require_paused=True)
    extra_b = controller_extra(session)
    b = animation.observe()
    if extra_a != extra_b or structural_signature(a) != structural_signature(b):
        raise IncoherentSample('Controller/animation structure changed around capture.')
    if not b['observed_quiescent']:
        raise CameraError('缩放动画尚未空闲，请松开滚轮并等待镜头停稳。')
    n = snap['native_controller']
    if any(extra_b['input_bytes_10_2d']) or any(n['input_vector_80']) or any(n['input_vector_9c']):
        raise CameraError('Camera input has not been released.')
    return snap,b

def validate_snapshot(s,settled=True):
    n,r,c=s['native_controller'],s['raw_camera'],s['camera']
    if s['build']['sha256']!=PROFILE_1121.sha256 or not s['replay']['paused']:
        raise CameraError('Requires the exact paused 11.21 build.')
    if len(n['target_angles'])!=2 or len(n['smoothed_angles'])!=2:
        raise CameraError('Unexpected native angle layout.')
    values=c['position']+c['quaternion']+n['target_position']+n['target_angles']+n['smoothed_angles']
    values += [c['horizontal_fov_deg'],n['current_interface_fov'],n['target_interface_fov'],
               n['native_roll_radians'],r['base_roll_deg'],r['interface_fov'],r['aspect'],r['fov_scale']]
    if not all(math.isfinite(x)for x in values):raise CameraError('Nonfinite camera state.')
    if n['native_roll_radians']!=0:
        raise CameraError('请先将游戏原生侧倾归零；轨迹侧倾由相机基础横滚控制。')
    if abs(n['target_angles'][0])>1e6 or abs(n['target_angles'][1])>80:
        raise CameraError('摄像机水平角度累积过大或俯仰过于接近极点。')
    if not all(5<=n[k]<=90 for k in ('current_interface_fov','target_interface_fov')):
        raise CameraError('缩放超出当前已适配范围。')
    if r['aspect']<=0 or r['fov_scale']<=0:raise CameraError('Invalid viewport/scaling.')
    if abs(c['horizontal_fov_deg']-r['interface_fov']*r['fov_scale'])>.0001:
        kind=CameraError if settled else IncoherentSample
        raise kind('缩放状态与画面投影尚未同步，请等待镜头停稳。')
    q=quaternion_from_angles(90-n['smoothed_angles'][0],-n['smoothed_angles'][1],-r['base_roll_deg'])
    if angle_difference(q,c['quaternion'])>.01:
        kind=CameraError if settled else IncoherentSample
        raise kind('Native smoothed angles and Camera direction are from inconsistent update stages.')
    if settled:
        if max(abs(a-b)for a,b in zip(n['target_angles'],n['smoothed_angles']))>.001:
            raise CameraError('Angles are not settled.')
        if math.dist(n['target_position'],c['position'])>.01:
            raise CameraError('Position is not settled.')
        # Native smoothing can stop one float ULP short of its target. The
        # independent animation/job quiescence and stable-sample checks remain.
        if n['current_interface_fov']!=r['interface_fov'] or abs(n['current_interface_fov']-n['target_interface_fov'])>1e-5:
            raise CameraError('缩放尚未稳定，请松开滚轮并等待镜头停稳。')

def same_scene(saved,s):
    if saved['session_id']!=s['session_id'] or saved['addresses']!=s['addresses']:
        raise CameraError('Replay/camera identity changed.')
    if saved['native_controller'].get('kind')!=s['native_controller'].get('kind'):
        raise CameraError('自由镜头控制器已切换，请重新连接后重试。')
    if any(saved['replay'][k]!=s['replay'][k]for k in ('time','origin','rate')) or not s['replay']['paused']:
        raise CameraError('Paused replay time or rate changed.')
    if any(saved['raw_camera'][k]!=s['raw_camera'][k]for k in ('aspect','fov_scale','base_roll_deg')):
        raise CameraError('Viewport/scaling/base roll changed.')
    if s['native_controller']['native_roll_radians']!=saved['native_controller']['native_roll_radians']:
        raise CameraError('Native roll changed.')

def segment_intersects(a,b,box):
    lo,hi=0.,1.
    for i in range(3):
        d=b[i]-a[i]
        if d==0:
            if not box[i]<=a[i]<=box[i+3]:return False
        else:
            x,y=sorted(((box[i]-a[i])/d,(box[i+3]-a[i])/d))
            lo,hi=max(lo,x),min(hi,y)
            if lo>hi:return False
    return True

def check_path(session,extra,start,end):
    for point in (start,end):
        if not all(math.isfinite(v)for v in point)or not all(lo+.1<=v<=hi-.1 for lo,v,hi in
                zip(extra['bounds_min'],point,extra['bounds_max'])):
            raise CameraError('Path endpoint outside or too near primary bounds.')
    begin,finish=(int(x,16)for x in extra['position_boxes_begin_end'])
    if finish<begin or (finish-begin)%24 or finish-begin>128*24:
        raise CameraError('Unexpected native position-region list.')
    boxes=[]
    for address in range(begin,finish,24):
        box=list(struct.unpack('<6f',session.memory.read(address,24)))
        if not all(math.isfinite(x)for x in box)or any(box[i]>box[i+3]for i in range(3)):
            raise CameraError('Invalid position-adjustment region.')
        if segment_intersects(start,end,box):
            raise CameraError('Return segment intersects a native position-adjustment region.')
        boxes.append(box)
    return boxes
