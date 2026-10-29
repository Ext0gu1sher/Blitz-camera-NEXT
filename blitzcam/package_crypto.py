"""Offline package cryptography using Windows CNG; no third-party runtime.

RSA-PSS/SHA256 authenticates releases. AES-256-GCM encrypts each Pro package;
RSA-OAEP/SHA256 wraps its fresh content key for a persisted device key.
Publisher private blobs are protected with current-user DPAPI, never shipped.
"""
from contextlib import contextmanager
import ctypes as C
import hashlib
import os
import struct

U32 = C.c_uint32
HANDLE = C.c_void_p
P = C.c_void_p


class CryptoError(ValueError):
    pass


class Padding(C.Structure):
    _fields_ = [('algorithm', C.c_wchar_p), ('label', P), ('size', U32)]


class PssPadding(C.Structure):
    _fields_ = [('algorithm', C.c_wchar_p), ('salt_size', U32)]


class AuthInfo(C.Structure):
    _fields_ = [('size', U32), ('version', U32), ('nonce', P), ('nonce_size', U32),
                ('aad', P), ('aad_size', U32), ('tag', P), ('tag_size', U32),
                ('mac', P), ('mac_size', U32), ('aad_count', U32),
                ('data_count', C.c_uint64), ('flags', U32)]


class Blob(C.Structure):
    _fields_ = [('size', U32), ('data', P)]


def _dll(name):
    if os.name != 'nt':
        raise CryptoError('离线包加密需要 Windows。')
    return C.WinDLL(name)


def _fn(dll, name, args):
    fn = getattr(dll, name)
    fn.argtypes, fn.restype = args, C.c_long
    return fn


def _check(status, operation):
    if status != 0:
        raise CryptoError(f'{operation}失败（0x{status & 0xffffffff:08X}）。')


def _buf(data):
    return C.create_string_buffer(bytes(data), max(1, len(data)))


@contextmanager
def _algorithm(name):
    dll, handle = _dll('bcrypt'), HANDLE()
    _check(_fn(dll, 'BCryptOpenAlgorithmProvider', [P, C.c_wchar_p, C.c_wchar_p, U32])(
        C.byref(handle), name, None, 0), '打开加密算法')
    try:
        yield dll, handle
    finally:
        _fn(dll, 'BCryptCloseAlgorithmProvider', [HANDLE, U32])(handle, 0)


@contextmanager
def _rsa(blob=None, private=False, bits=3072):
    with _algorithm('RSA') as (dll, algorithm):
        key = HANDLE()
        if blob is None:
            _check(_fn(dll, 'BCryptGenerateKeyPair', [HANDLE, P, U32, U32])(
                algorithm, C.byref(key), bits, 0), '生成发布密钥')
            try:
                _check(_fn(dll, 'BCryptFinalizeKeyPair', [HANDLE, U32])(key, 0), '完成密钥生成')
            except BaseException:
                _fn(dll, 'BCryptDestroyKey', [HANDLE])(key)
                raise
        else:
            source = _buf(blob)
            _check(_fn(dll, 'BCryptImportKeyPair', [HANDLE, HANDLE, C.c_wchar_p, P, P, U32, U32])(
                algorithm, None, 'RSAFULLPRIVATEBLOB' if private else 'RSAPUBLICBLOB',
                C.byref(key), source, len(blob), 0), '读取密钥')
        try:
            yield dll, key
        finally:
            _fn(dll, 'BCryptDestroyKey', [HANDLE])(key)


def _export(dll, key, kind):
    size = U32()
    fn = _fn(dll, 'BCryptExportKey', [HANDLE, HANDLE, C.c_wchar_p, P, U32, P, U32])
    _check(fn(key, None, kind, None, 0, C.byref(size), 0), '读取密钥长度')
    result = C.create_string_buffer(size.value)
    _check(fn(key, None, kind, result, size.value, C.byref(size), 0), '导出密钥')
    return result.raw[:size.value]


def generate_publisher():
    with _rsa() as (dll, key):
        return _export(dll, key, 'RSAPUBLICBLOB'), _export(dll, key, 'RSAFULLPRIVATEBLOB')


def validate_public(blob):
    if not isinstance(blob, bytes) or len(blob) < 24:
        raise CryptoError('设备公钥无效。')
    magic, bits, exponent, modulus, p1, p2 = struct.unpack_from('<6I', blob)
    if (magic != 0x31415352 or bits not in (2048, 3072, 4096) or modulus != bits // 8
            or not 1 <= exponent <= 8 or p1 or p2 or len(blob) != 24 + exponent + modulus):
        raise CryptoError('设备公钥格式无效。')
    with _rsa(blob):
        pass
    return hashlib.sha256(blob).hexdigest()


def sign(private, content):
    digest, padding = _buf(hashlib.sha256(content).digest()), PssPadding('SHA256', 32)
    with _rsa(private, True) as (dll, key):
        fn = _fn(dll, 'BCryptSignHash', [HANDLE, P, P, U32, P, U32, P, U32])
        size = U32()
        _check(fn(key, C.byref(padding), digest, 32, None, 0, C.byref(size), 8), '读取签名长度')
        out = C.create_string_buffer(size.value)
        _check(fn(key, C.byref(padding), digest, 32, out, size.value, C.byref(size), 8), '签名')
        return out.raw[:size.value]


def verify(public, content, signature):
    digest, sig, padding = _buf(hashlib.sha256(content).digest()), _buf(signature), PssPadding('SHA256', 32)
    with _rsa(public) as (dll, key):
        _check(_fn(dll, 'BCryptVerifySignature', [HANDLE, P, P, U32, P, U32, U32])(
            key, C.byref(padding), digest, 32, sig, len(signature), 8), '发布签名验证')


def wrap_key(public, secret):
    source, padding, size = _buf(secret), Padding('SHA256', None, 0), U32()
    with _rsa(public) as (dll, key):
        fn = _fn(dll, 'BCryptEncrypt', [HANDLE, P, U32, P, P, U32, P, U32, P, U32])
        _check(fn(key, source, len(secret), C.byref(padding), None, 0, None, 0, C.byref(size), 4), '读取密钥封装长度')
        out = C.create_string_buffer(size.value)
        _check(fn(key, source, len(secret), C.byref(padding), None, 0, out, size.value, C.byref(size), 4), '封装设备密钥')
        return out.raw[:size.value]


def aes_gcm(secret, nonce, content, aad=b'', *, tag=None):
    if len(secret) != 32 or len(nonce) != 12 or (tag is not None and len(tag) != 16):
        raise CryptoError('加密参数无效。')
    with _algorithm('AES') as (dll, algorithm):
        mode = C.create_unicode_buffer('ChainingModeGCM')
        _check(_fn(dll, 'BCryptSetProperty', [HANDLE, C.c_wchar_p, P, U32, U32])(
            algorithm, 'ChainingMode', mode, C.sizeof(mode), 0), '设置加密模式')
        key, keydata = HANDLE(), _buf(secret)
        _check(_fn(dll, 'BCryptGenerateSymmetricKey', [HANDLE, P, P, U32, P, U32, U32])(
            algorithm, C.byref(key), None, 0, keydata, len(secret), 0), '建立包密钥')
        try:
            source, nbuf, abuf = _buf(content), _buf(nonce), _buf(aad)
            tbuf = _buf(tag or b'\0' * 16)
            auth = AuthInfo(C.sizeof(AuthInfo), 1, C.cast(nbuf, P), 12,
                            C.cast(abuf, P) if aad else None, len(aad), C.cast(tbuf, P), 16)
            out, size = C.create_string_buffer(max(1, len(content))), U32()
            name = 'BCryptDecrypt' if tag is not None else 'BCryptEncrypt'
            _check(_fn(dll, name, [HANDLE, P, U32, P, P, U32, P, U32, P, U32])(
                key, source, len(content), C.byref(auth), None, 0, out, len(content), C.byref(size), 0), '包解密验证' if tag is not None else '包加密')
            return out.raw[:size.value], tbuf.raw
        finally:
            _fn(dll, 'BCryptDestroyKey', [HANDLE])(key)


def protect_local(content, *, decrypt=False):
    """DPAPI protects the publisher's private key at rest for this Windows user."""
    dll, source, result = _dll('crypt32'), _buf(content), Blob()
    data = Blob(len(content), C.cast(source, P))
    if decrypt:
        fn = _fn(dll, 'CryptUnprotectData', [P, P, P, P, P, U32, P])
        ok = fn(C.byref(data), None, None, None, None, 1, C.byref(result))
    else:
        fn = _fn(dll, 'CryptProtectData', [P, C.c_wchar_p, P, P, P, U32, P])
        ok = fn(C.byref(data), 'Blitz Camera publisher key', None, None, None, 1, C.byref(result))
    if not ok:
        raise CryptoError('无法读取此 Windows 用户保护的发布密钥。')
    try:
        return C.string_at(result.data, result.size)
    finally:
        C.memset(result.data, 0, result.size)
        fn = _dll('kernel32').LocalFree
        fn.argtypes, fn.restype = [P], P
        fn(result.data)


@contextmanager
def device_key(name, provider, *, create=False):
    dll, store, key = _dll('ncrypt'), HANDLE(), HANDLE()
    _check(_fn(dll, 'NCryptOpenStorageProvider', [P, C.c_wchar_p, U32])(
        C.byref(store), provider, 0), '打开设备密钥存储')
    free = _fn(dll, 'NCryptFreeObject', [HANDLE])
    try:
        if create:
            _check(_fn(dll, 'NCryptCreatePersistedKey', [HANDLE, P, C.c_wchar_p, C.c_wchar_p, U32, U32])(
                store, C.byref(key), 'RSA', name, 0, 0), '生成设备密钥')
            length = U32(2048)
            _check(_fn(dll, 'NCryptSetProperty', [HANDLE, C.c_wchar_p, P, U32, U32])(
                key, 'Length', C.byref(length), 4, 0), '设置设备密钥长度')
            _check(_fn(dll, 'NCryptFinalizeKey', [HANDLE, U32])(key, 64), '保存设备密钥')
        else:
            _check(_fn(dll, 'NCryptOpenKey', [HANDLE, P, C.c_wchar_p, U32, U32])(
                store, C.byref(key), name, 0, 64), '打开本机授权密钥')
        yield dll, key
    finally:
        if key.value:
            free(key)
        free(store)


def device_public(name, provider, *, create=False):
    with device_key(name, provider, create=create) as (dll, key):
        fn = _fn(dll, 'NCryptExportKey', [HANDLE, HANDLE, C.c_wchar_p, P, P, U32, P, U32])
        size = U32()
        _check(fn(key, None, 'RSAPUBLICBLOB', None, None, 0, C.byref(size), 0), '读取设备公钥长度')
        result = C.create_string_buffer(size.value)
        _check(fn(key, None, 'RSAPUBLICBLOB', None, result, size.value, C.byref(size), 0), '导出设备公钥')
        return result.raw[:size.value]


def stored_key_names(provider):
    """Enumerate current-user key names only; never export private material.

    NCryptEnumKeys/NCryptKeyName ownership follows the Windows SDK contract:
    https://learn.microsoft.com/windows/win32/api/ncrypt/nf-ncrypt-ncryptenumkeys
    """
    class KeyName(C.Structure):
        _fields_ = [('name', C.c_wchar_p), ('algorithm', C.c_wchar_p),
                    ('legacy_spec', U32), ('flags', U32)]
    dll, store, state = _dll('ncrypt'), HANDLE(), P()
    _check(_fn(dll, 'NCryptOpenStorageProvider', [P, C.c_wchar_p, U32])(
        C.byref(store), provider, 0), '打开设备密钥存储')
    names = []
    free = _fn(dll, 'NCryptFreeBuffer', [P])
    try:
        enum = _fn(dll, 'NCryptEnumKeys', [HANDLE, C.c_wchar_p, P, P, U32])
        while True:
            item = P()
            status = enum(store, None, C.byref(item), C.byref(state), 64)
            try:
                if (status & 0xffffffff) == 0x8009002a: break  # NTE_NO_MORE_ITEMS
                _check(status, '读取本机设备登记')
                entry = C.cast(item, C.POINTER(KeyName)).contents
                if entry.algorithm == 'RSA' and not (entry.flags & 32):
                    names.append(entry.name)
            finally:
                if item.value: free(item)
    finally:
        if state.value: free(state)
        _fn(dll, 'NCryptFreeObject', [HANDLE])(store)
    return names


def unwrap_device(name, provider, wrapped):
    with device_key(name, provider) as (dll, key):
        fn = _fn(dll, 'NCryptDecrypt', [HANDLE, P, U32, P, P, U32, P, U32])
        source, padding, size = _buf(wrapped), Padding('SHA256', None, 0), U32()
        _check(fn(key, source, len(wrapped), C.byref(padding), None, 0, C.byref(size), 4 | 64), '读取解密长度')
        result = C.create_string_buffer(size.value)
        _check(fn(key, source, len(wrapped), C.byref(padding), result, size.value, C.byref(size), 4 | 64), '解封本机包密钥')
        return result.raw[:size.value]
