"""Research-only ABI for the deferred main-job seek experiment."""
import ctypes as C
from .seek_trial import Config as OriginalConfig
from .seek_trial import prepare as original_prepare


class Config(C.Structure):
    _pack_ = 4
    _fields_ = OriginalConfig._fields_ + [
        (n, C.c_uint32) for n in ('mode', 'job_manager', 'queue_entry')
    ] + [('fault_path', C.c_char*260), ('ui_repair', C.c_uint32)]


class Header(C.Structure):
    _pack_ = 4
    _fields_ = [(n, C.c_int32) for n in (
        'heartbeat status error active detached thread requests queued job_thread '
        'emitting_nodes job_calls clones destroys faults observer').split()] + [
        (n, C.c_uint32) for n in ('job_token', 'queue_depth')
    ] + [(n, C.c_float) for n in ('raw_before', 'raw_after')] + [
        (n, C.c_uint32) for n in ('emitting_node','emitting_vft','emitting_owner','emitting_entry')]


class UiRepairState(C.Structure):
    _pack_ = 4
    _fields_ = [(n, C.c_uint32) for n in (
        'installed base thread active clear_calls remove_calls removed '
        'relocated coalesced violations last_stage last_owner last_component sequence').split()
    ] + [('fault_path', C.c_char*260)]


def prepare(session, sample, target, mode, fault_path, ui_repair=False, *, max_delta=120):
    source, link = original_prepare(session, sample, target, max_delta=max_delta)
    config = Config()
    for n, _ in OriginalConfig._fields_:
        setattr(config, n, getattr(source, n))
    config.magic = 0x32534b42
    config.size = C.sizeof(Config)
    config.mode = mode
    config.ui_repair = int(ui_repair)
    # ab01f0 -> singleton wrapper; native call sites pass *wrapper as ECX.
    config.job_manager = session.memory.u32(session.memory.u32(session.live(0x4690a30)))
    config.queue_entry = session.live(0x91d090)
    encoded = str(fault_path).encode('utf-8')
    if len(encoded) >= 260:
        raise ValueError('Fault recording path exceeds fixed native buffer.')
    config.fault_path = encoded
    return config, link
