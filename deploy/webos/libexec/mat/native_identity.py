"""Temporary native decoder context on the caller's RM-owned port only.

No code patching or disk/config replacement. The allocated context belongs to
this process; field offsets are locked to the inspected C5 library SHA-256.
HAL MAT=5 / TRUE_HD=6 are driver enums, NOT Gst/native codec IDs (native 6=DRA).
"""
import ctypes as C,fcntl,hashlib,struct
from pathlib import Path
class NativeIdentity:
 def __init__(self,gst,port,hal_codec,log,channels=6,rate=48000):
  assert port in (0,1) and hal_codec in (5,6)
  if channels not in (6,8) or rate!=48000:raise ValueError("unverified native discovery format")
  self.ctx=None;self.opened=False;self.connected=False;self.started=False;self.log=log
  self.codec=hal_codec
  self.port=port
  path='/usr/lib/gstreamer-1.0/libgstlgaudiodec.so'
  assert hashlib.sha256(Path(path).read_bytes()).hexdigest()=='84db367e1ea3eeb4b589bf63910140cfd43ea77f2db124ae6882fbee8ebb6bb7'
  # Register the stock plugin's logging/module support without creating or
  # changing any system decoder element or registry file.
  for n,a,r in [('gst_element_factory_find',[C.c_char_p],C.c_void_p),('gst_plugin_feature_load',[C.c_void_p],C.c_void_p),('gst_object_unref',[C.c_void_p],None)]:
   f=getattr(gst,n);f.argtypes=a;f.restype=r
  factory=gst.gst_element_factory_find(b'ac3_audiodec');assert factory
  feature=gst.gst_plugin_feature_load(factory);assert feature
  gst.gst_object_unref(feature);gst.gst_object_unref(factory)
  self.lib=l=C.CDLL(path)
  for n,a,r in [('lgadec_open',[],C.c_void_p),('lgadec_close',[C.c_void_p],C.c_int),
   ('lgadec_decoder_open',[C.c_void_p],C.c_int),('lgadec_decoder_connect',[C.c_void_p],C.c_int),
   ('lgadec_decoder_start',[C.c_void_p],C.c_int),('lgadec_decoder_stop',[C.c_void_p],C.c_int),
   ('lgadec_aimc_disconnect',[C.c_void_p],C.c_int),('lgadec_decoder_close',[C.c_void_p],C.c_int),
   ('lgadec_decoder_feed',[C.c_void_p,C.c_void_p,C.c_uint,C.c_uint64],C.c_int)]:
   f=getattr(l,n);f.argtypes=a;f.restype=r
  assert not Path('/tmp/lgadec_dump_enable').exists(),'external decoder dump flag enabled'
  self.ctx=l.lgadec_open();assert self.ctx
  try:
   C.c_int.from_address(self.ctx+0x314).value=port
   C.c_uint.from_address(self.ctx+0x18).value=21
   C.c_uint.from_address(self.ctx+0x2d0).value=rate
   C.c_ubyte.from_address(self.ctx+0x2d4).value=channels
   C.c_ubyte.from_address(self.ctx+0x2d5).value=16
   rc=l.lgadec_decoder_open(self.ctx)
   if rc<0:raise RuntimeError('native decoder open failed')
   self.opened=True;self.fd=C.c_int.from_address(self.ctx+4).value
   # Use the exact audited ioctl directly: the vendor configure wrapper
   # silently ignores this ioctl's failures, so its return is not evidence.
   fcntl.ioctl(self.fd,0x40044402,struct.pack('<I',hal_codec))
   uid=bytearray(4);fcntl.ioctl(self.fd,0x80044404,uid,True)
   self.uid=struct.unpack('<I',uid)[0]
   log(phase='native_decoder_created',halCodec=hal_codec,audioPort=port,headUid=hex(self.uid),
       decoderState=C.c_uint.from_address(self.ctx+0x300).value)
   if not self.uid:raise RuntimeError('native decoder has no head UID')
   rc=l.lgadec_decoder_connect(self.ctx)
   if rc!=0:raise RuntimeError('native decoder connect failed')
   self.connected=True
   rc=l.lgadec_decoder_start(self.ctx)
   if rc!=0:raise RuntimeError('native decoder start failed')
   self.started=True
  except BaseException:
   self.close();raise
 def feed(self,data,pts):
  if not self.started:raise RuntimeError('native identity is not started')
  rc=self.lib.lgadec_decoder_feed(self.ctx,data,len(data),pts)
  # This decoder API returns 0, unlike lgao_feed which returns a byte count.
  if rc!=0:raise RuntimeError('native decoder feed rejected')
 def snapshot(self):
  if not self.ctx:return None
  info=bytearray(68);error=None
  try:fcntl.ioctl(self.fd,0xc044440c,info,True)
  except OSError as e:error=e.errno
  return {'halCodec':self.codec,'headUid':hex(self.uid),'state':C.c_uint.from_address(self.ctx+0x300).value,
   'hasDecoderInput':bool(C.c_void_p.from_address(self.ctx+0x358).value),
   'decodedInfoWords':list(struct.unpack('<17I',info)),'decodedInfoIoctlErrno':error}
 def close(self):
  if not self.ctx:return
  # Stop callbacks and detach private modules before freeing their context.
  if self.started:self.lib.lgadec_decoder_stop(self.ctx);self.started=False
  if self.connected:self.lib.lgadec_aimc_disconnect(self.ctx);self.connected=False
  if self.opened:self.lib.lgadec_decoder_close(self.ctx);self.opened=False
  self.lib.lgadec_close(self.ctx);self.ctx=None
