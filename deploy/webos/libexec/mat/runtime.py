"""Temporary TV test utilities. Importing this module does not play audio."""
import ctypes as C,json,os,re,subprocess,time
P=C.c_void_p;U=C.c_uint64
def bind(lib,n,a,r):
 f=getattr(lib,n);f.argtypes=a;f.restype=r;return f
def log(phase,**kw):print('CODEX_AV '+json.dumps(dict(phase=phase,wallMonotonic=time.monotonic(),**kw)),flush=True)
class Tv:
 def __init__(self):self.master,self.slave=os.openpty()
 def luna(self,uri,payload):
  r=subprocess.run(['luna-send','-n','1','-w','2200','-f',uri,json.dumps(payload)],stdin=self.slave,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,timeout=4)
  d=json.loads(r.stdout)
  if isinstance(d,dict) and d.get('returnValue') is False:raise RuntimeError('TV service rejected operation')
  return d
 def foreground(self):return self.luna('luna://com.webos.applicationManager/getForegroundAppInfo',{}).get('appId')
 def earc(self,value=None):
  a=['amixer','-c','0','cget' if value is None else 'cset','name=Sndout EARC Outputtype']
  if value is not None:a.append(','.join(map(str,value)))
  s=subprocess.check_output(a,stderr=subprocess.DEVNULL,text=True,timeout=3)
  return [int(x) for x in re.search(r'^\s*: values=([0-9,]+)\s*$',s,re.M)[1].split(',')]
 def connect(self,port,connect=True):
  p={'source':'ADEC'+str(port),'sink':'MAIN'}
  if connect:p['pipelineAttribute']={'pipelinePurpose':[],'sourceType':'MEDIA','sourceAttribute':'MEDIA'}
  return self.luna('luna://com.webos.service.audiooutput/audio/'+('connect' if connect else 'disconnect'),p)
 def close(self):os.close(self.master);os.close(self.slave)
class Resource:
 def __init__(self):
  self.handle=None;self.allocation=None;self.registered=False
  self.lib=l=C.CDLL('libresource_mgr_client_c.so.1')
  self.CB=C.CFUNCTYPE(C.c_bool,*([C.c_char_p]*5));self.cb=self.CB(lambda *_:False)
  for n,a,r in [('Create',[C.c_char_p,self.CB],P),('RegisterPipeline',[P,C.c_char_p],C.c_bool),('TryAcquire',[P,C.c_char_p,C.POINTER(P)],C.c_bool),('Release',[P,C.c_char_p],C.c_bool),('UnregisterPipeline',[P],C.c_bool),('Destroy',[P],C.c_bool)]:bind(l,'ResourceManagerClient'+n,a,r)
  self.handle=l.ResourceManagerClientCreate(None,self.cb)
  if not self.handle:raise RuntimeError('resource client creation failed')
  try:
   self.registered=bool(l.ResourceManagerClientRegisterPipeline(self.handle,b'media'))
   if not self.registered:raise RuntimeError('resource registration denied')
   response=P();ok=l.ResourceManagerClientTryAcquire(self.handle,b'[{"resource":"ADEC","qty":1},{"resource":"ADEC_BANDWIDTH","qty":2}]',C.byref(response))
   d=json.loads(C.string_at(response));self.allocation=json.dumps(d['resources']).encode() if ok else None
   if not ok or not d.get('state'):raise RuntimeError('no unused audio resources available')
   self.port=next(x['index'] for x in d['resources'] if x['resource']=='ADEC');assert self.port in (0,1)
  except BaseException:self.close();raise
 def close(self):
  if not self.handle:return
  if self.allocation:self.lib.ResourceManagerClientRelease(self.handle,self.allocation)
  if self.registered:self.lib.ResourceManagerClientUnregisterPipeline(self.handle)
  self.lib.ResourceManagerClientDestroy(self.handle);self.handle=None
class Gst:
 def __init__(self):
  os.environ.update(GST_REGISTRY_UPDATE='no',GST_REGISTRY_FORK='no')
  if not os.environ.get('GST_REGISTRY','').startswith('/tmp/moonlight-mat-root-'):raise RuntimeError('private registry required')
  self.g=C.CDLL('libgstreamer-1.0.so.0');self.a=C.CDLL('libgstapp-1.0.so.0');self.o=C.CDLL('libgobject-2.0.so.0')
  self.free=bind(C.CDLL('libglib-2.0.so.0'),'g_free',[P],None)
  entries=[('gst_init',[P,P],None),('gst_parse_launch',[C.c_char_p,C.POINTER(P)],P),('gst_bin_get_by_name',[P,C.c_char_p],P),('gst_element_set_state',[P,C.c_int],C.c_int),('gst_element_get_state',[P,P,P,U],C.c_int),('gst_object_unref',[P],None),('gst_buffer_new_allocate',[P,C.c_size_t,P],P),('gst_buffer_fill',[P,C.c_size_t,P,C.c_size_t],C.c_size_t),('gst_buffer_extract',[P,C.c_size_t,P,C.c_size_t],C.c_size_t),('gst_buffer_set_flags',[P,C.c_uint],C.c_int),('gst_mini_object_ref',[P],P),('gst_mini_object_unref',[P],None),('gst_element_get_bus',[P],P),('gst_bus_timed_pop_filtered',[P,U,C.c_uint],P),('gst_message_parse_error',[P,P,P],None),('gst_segment_new',[],P),('gst_segment_init',[P,C.c_int],None),('gst_segment_do_seek',[P,C.c_double,C.c_int,C.c_int,C.c_int,U,C.c_int,U,P],C.c_int),('gst_segment_free',[P],None),('gst_sample_new',[P,P,P,P],P),('gst_element_get_clock',[P],P),('gst_clock_get_time',[P],U),('gst_element_get_base_time',[P],U),('gst_object_get_name',[P],P),('gst_bin_recalculate_latency',[P],C.c_int),('gst_structure_get_uint64',[P,C.c_char_p,P],C.c_int),('gst_structure_free',[P],None)]
  for n,a,r in entries:setattr(self,n,bind(self.g,n,a,r))
  for n,a,r in [('gst_app_src_push_sample',[P,P],C.c_int),('gst_app_src_end_of_stream',[P],C.c_int)]:setattr(self,n,bind(self.a,n,a,r))
  self.connect=bind(self.o,'g_signal_connect_data',[P,C.c_char_p,P,P,P,C.c_int],C.c_ulong)
  self.get=self.o.g_object_get;self.get.argtypes=[P,C.c_char_p];self.get.restype=None
  self.set=self.o.g_object_set;self.set.argtypes=[P,C.c_char_p];self.set.restype=None
  self.gst_init(None,None)
 def load_plugin(self,path,expected_sha):
  import hashlib
  from pathlib import Path
  if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=expected_sha:raise RuntimeError('candidate plugin hash mismatch')
  f=bind(self.g,'gst_plugin_load_file',[C.c_char_p,C.POINTER(P)],P);error=P();plugin=f(str(path).encode(),C.byref(error))
  if not plugin or error.value:raise RuntimeError('explicit candidate plugin load failed')
  self.gst_object_unref(plugin)
 def prop(self,obj,n,ctype):
  v=ctype();self.get(obj,n.encode(),C.byref(v),P());return v.value
 def name(self,obj):
  p=self.gst_object_get_name(obj)
  if not p:return None
  try:return C.string_at(p).decode()
  finally:self.free(p)
 def segment(self,origin):
  p=self.gst_segment_new();self.gst_segment_init(p,3);update=C.c_int()
  if not self.gst_segment_do_seek(p,1.0,3,1,1,origin,0,2**64-1,C.byref(update)):raise RuntimeError('segment initialization rejected')
  return p
 def push(self,src,data,pts,duration,segment,flags=0):
  b=self.gst_buffer_new_allocate(None,len(data),None)
  if not b:raise RuntimeError('buffer allocation failed')
  if self.gst_buffer_fill(b,0,data,len(data))!=len(data):raise RuntimeError('buffer fill failed')
  U.from_address(b+0x28).value=pts;U.from_address(b+0x30).value=pts;U.from_address(b+0x38).value=duration
  if flags:self.gst_buffer_set_flags(b,flags)
  sample=self.gst_sample_new(b,None,segment,None);self.gst_mini_object_unref(b)
  rc=self.gst_app_src_push_sample(src,sample);self.gst_mini_object_unref(sample)
  if rc:raise RuntimeError('appsrc push failed: '+str(rc))
 def stats(self,obj):
  p=self.prop(obj,'stats',P)
  if not p:return {}
  out={}
  for k in ['rendered','dropped']:
   v=U()
   if self.gst_structure_get_uint64(p,k.encode(),C.byref(v)):out[k]=v.value
  self.gst_structure_free(p);return out
