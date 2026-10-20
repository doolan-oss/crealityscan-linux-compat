/* Actual control requests are forwarded to the scoped native UVC helper. */
static INIT_ONCE control_winsock_once=INIT_ONCE_STATIC_INIT;
static BOOL CALLBACK control_winsock_init(INIT_ONCE *once,void *arg,void **context){
 WSADATA data;return WSAStartup(MAKEWORD(2,2),&data)==0;
}
/* Wine blocking connect can stall under the GUI's thread scheduling. Make
 * connection establishment nonblocking too, not only subsequent I/O. */
static BOOL bridge_connect(SOCKET s,const struct sockaddr_in *addr){
 u_long nonblocking=1;if(ioctlsocket(s,FIONBIO,&nonblocking))return FALSE;
 if(!connect(s,(const struct sockaddr*)addr,sizeof(*addr)))return TRUE;
 int error=WSAGetLastError();if(error!=WSAEWOULDBLOCK&&error!=WSAEINPROGRESS)return FALSE;
 ULONGLONG deadline=GetTickCount64()+4000;
 do{
  fd_set writefds,errors;FD_ZERO(&writefds);FD_ZERO(&errors);FD_SET(s,&writefds);FD_SET(s,&errors);
  struct timeval zero={0};int ready=select(0,NULL,&writefds,&errors,&zero);
  if(ready==SOCKET_ERROR)return FALSE;
  if(ready){int status=0,len=sizeof(status);return !getsockopt(s,SOL_SOCKET,SO_ERROR,(char*)&status,&len)&&!status;}
  Sleep(1);
 }while(GetTickCount64()<deadline);
 LOG("loopback connection timed out");return FALSE;
}
static BOOL control_transfer(SOCKET s,void *buffer,int size,BOOL sending){
 char *p=buffer;ULONGLONG deadline=GetTickCount64()+4000;
 while(size){
  int n=sending?send(s,p,size,0):recv(s,p,size,0);
  if(n>0){p+=n;size-=n;continue;}
  if(n==SOCKET_ERROR&&WSAGetLastError()==WSAEWOULDBLOCK&&GetTickCount64()<deadline){Sleep(1);continue;}
  LOG("control transport failed sending=%d remaining=%d error=%d",sending,size,WSAGetLastError());return FALSE;
 }
 return TRUE;
}
static HRESULT control_rpc(camera *c, DWORD op, DWORD selector,
                           const void *input, DWORD input_len,
                           void *output, DWORD capacity, DWORD *output_len) {
  if (output_len) *output_len = 0;
  if (!sdk_mode() || c->shutdown) return E_ACCESSDENIED;
  char token[64]={0}, port[16]={0};
  if (!GetEnvironmentVariableA("PIKA_CAMERA_TOKEN", token, 64) ||
      !GetEnvironmentVariableA("PIKA_CONTROL_PORT", port, 16)) return E_ACCESSDENIED;
  LOG("control begin op=%lu endpoint=%u",op,c->endpoint);
  if(!InitOnceExecuteOnce(&control_winsock_once,control_winsock_init,NULL,NULL))return E_FAIL;
  LOG("control winsock ready op=%lu",op);
  SOCKET s=socket(AF_INET,SOCK_STREAM,IPPROTO_TCP);
  LOG("control socket created op=%lu socket=%llu",op,(ULONGLONG)s);
  HRESULT hr=E_FAIL;
  if (s==INVALID_SOCKET) return hr;
  DWORD timeout=4000;
  setsockopt(s,SOL_SOCKET,SO_RCVTIMEO,(char*)&timeout,4);
  setsockopt(s,SOL_SOCKET,SO_SNDTIMEO,(char*)&timeout,4);
  struct sockaddr_in addr={0}; addr.sin_family=AF_INET;
  addr.sin_addr.s_addr=htonl(INADDR_LOOPBACK); addr.sin_port=htons((USHORT)atoi(port));
  DWORD header[4]={op,c->endpoint,selector,input_len}, reply[2];
  LOG("control connecting op=%lu",op);
  int connected=bridge_connect(s,&addr)?0:-1;
  LOG("control connected op=%lu status=%d",op,connected);
  if (!connected && control_transfer(s,token,64,TRUE) &&
      control_transfer(s,header,16,TRUE) && (!input_len || control_transfer(s,(void*)input,input_len,TRUE)) &&
      control_transfer(s,reply,8,FALSE)) {
    if (reply[0]) { LOG("native control op=%lu endpoint=%u selector=%lu errno=%lu",op,c->endpoint,selector,reply[0]); hr=E_FAIL; }
    else if (reply[1]>capacity) hr=HRESULT_FROM_WIN32(ERROR_MORE_DATA);
    else if (!reply[1] || control_transfer(s,output,reply[1],FALSE)) {
      if (output_len) *output_len=reply[1];
      hr=S_OK;
    }
  }
  LOG("control closing op=%lu",op);
  closesocket(s); LOG("control complete op=%lu result=%lx",op,hr); return hr;
}
#define CONTROL_IDENTITY(tag, type, member) \
static HRESULT WINAPI tag##_qi(type *p, REFIID iid, void **out) { \
 camera *c=CONTAINING_RECORD(p,camera,member); return source_qi(&c->source,iid,out); } \
static ULONG WINAPI tag##_add(type *p) { return camera_add(CONTAINING_RECORD(p,camera,member)); } \
static ULONG WINAPI tag##_release(type *p) { return camera_release(CONTAINING_RECORD(p,camera,member)); }
CONTROL_IDENTITY(topo,BridgeTopology,topology)
CONTROL_IDENTITY(ks,BridgeKs,ks)
CONTROL_IDENTITY(camctl,IAMCameraControl,camctl)
CONTROL_IDENTITY(procctl,IAMVideoProcAmp,procctl)
static HRESULT WINAPI topo_zero(BridgeTopology *p,DWORD *n) { if(!n)return E_POINTER;*n=0;return S_OK; }
static HRESULT WINAPI topo_category(BridgeTopology *p,DWORD i,GUID *g) { return E_INVALIDARG; }
static HRESULT WINAPI topo_connection(BridgeTopology *p,DWORD i,BridgeConnection *g) { return E_INVALIDARG; }
static HRESULT WINAPI topo_name(BridgeTopology *p,DWORD i,WCHAR *name,DWORD size,DWORD *needed) {
 const WCHAR text[]=L"Pika UVC extension unit 4";
 if(i)return E_INVALIDARG;
 if(needed)*needed=sizeof(text);
 if(!name || size<sizeof(text))return HRESULT_FROM_WIN32(ERROR_MORE_DATA);
 memcpy(name,text,sizeof(text));return S_OK;
}
static HRESULT WINAPI topo_nodes(BridgeTopology *p,DWORD *n) { if(!n)return E_POINTER;*n=1;return S_OK; }
static HRESULT WINAPI topo_type(BridgeTopology *p,DWORD i,GUID *g) { if(!g)return E_POINTER;if(i)return E_INVALIDARG;*g=bridge_node_type;return S_OK; }
static HRESULT WINAPI topo_create(BridgeTopology *p,DWORD i,REFIID iid,void **out) {
 if(i)return E_INVALIDARG;
 return topo_qi(p,iid,out);
}
static const BridgeTopologyVtbl topo_vtable={topo_qi,topo_add,topo_release,topo_zero,topo_category,topo_zero,topo_connection,topo_name,topo_nodes,topo_type,topo_create};
static HRESULT WINAPI ks_property(BridgeKs *p,BridgeProperty *prop,ULONG plen,void *data,ULONG len,ULONG *returned) {
 if(returned)*returned=0;
 if(!prop || plen<sizeof(BridgeNode))return E_INVALIDARG;
 BridgeNode *node=(BridgeNode*)prop;
 if(node->NodeId || !IsEqualGUID(&prop->Set,&bridge_xu_guid) || prop->Id<1 || prop->Id>3)
  return HRESULT_FROM_WIN32(ERROR_NOT_SUPPORTED);
 if(prop->Flags!=(0x10000000u|1) && prop->Flags!=(0x10000000u|2)) {
  LOG("unsupported KsProperty flags=%lx id=%lu",prop->Flags,prop->Id);return E_NOTIMPL;
 }
 camera *c=CONTAINING_RECORD(p,camera,ks);
 DWORD size=0,n=0;
 HRESULT hr=control_rpc(c,1,prop->Id,NULL,0,&size,4,&n);
 if(FAILED(hr))return hr;
 if(n!=4 || size>1024 || !size)return E_UNEXPECTED;
 if(returned)*returned=size;
 if(!data || len<size)return HRESULT_FROM_WIN32(ERROR_MORE_DATA);
 if(prop->Flags&2) {
  LOG("XU SET endpoint=%u selector=%lu bytes=%lu",c->endpoint,prop->Id,size);
  hr=control_rpc(c,3,prop->Id,data,size,NULL,0,NULL);
  if(returned)*returned=0;
 } else {
  hr=control_rpc(c,2,prop->Id,NULL,0,data,len,&n);
  if(returned)*returned=n;
 }
 return hr;
}
static HRESULT WINAPI ks_unsupported(BridgeKs *p,void *a,ULONG b,void *c,ULONG d,ULONG *e) { if(e)*e=0;return E_NOTIMPL; }
static const BridgeKsVtbl ks_vtable={ks_qi,ks_add,ks_release,ks_property,ks_unsupported,ks_unsupported};
static DWORD proc_id(LONG p) {
 switch(p) {
 case VideoProcAmp_Brightness:return 0x00980900;
 case VideoProcAmp_Contrast:return 0x00980901;
 case VideoProcAmp_Hue:return 0x00980903;
 case VideoProcAmp_Saturation:return 0x00980902;
 case VideoProcAmp_Sharpness:return 0x0098091b;
 case VideoProcAmp_Gamma:return 0x00980910;
 case VideoProcAmp_WhiteBalance:return 0x0098091a;
 case VideoProcAmp_BacklightCompensation:return 0x0098091c;
 case VideoProcAmp_Gain:return 0x00980913;
 default:return 0;
 }
}
static LONG exposure_exponent(LONG raw) {
 // Standard UVC absolute exposure is in 100us; DirectShow uses log2 seconds.
 double seconds=raw/10000.0, x=1.0; LONG e=0;
 while(x>seconds && e>-20) {x/=2;e--;}
 return e;
}
static LONG exposure_raw(LONG e) {
 double x=10000.0;
 if(e < -20 || e > 10)return -1;
 while(e<0){x/=2;e++;}while(e>0){x*=2;e--;}
 return (LONG)(x+.5);
}
static HRESULT ctl_range(camera *c,DWORD id,LONG *min,LONG *max,LONG *step,LONG *def,LONG *flags,BOOL exposure) {
 if(!id)return HRESULT_FROM_WIN32(ERROR_NOT_SUPPORTED);
 if(!min||!max||!step||!def||!flags)return E_POINTER;
 BYTE query[68];DWORD n;
 HRESULT hr=control_rpc(c,10,id,NULL,0,query,sizeof(query),&n);
 if(FAILED(hr))return hr;
 if(n!=68)return E_UNEXPECTED;
 memcpy(min,query+40,4);memcpy(max,query+44,4);memcpy(step,query+48,4);memcpy(def,query+52,4);
 *flags=2;
 if(exposure){*min=exposure_exponent(*min);*max=exposure_exponent(*max);*def=exposure_exponent(*def);*step=1;*flags=3;}
 return S_OK;
}
static HRESULT ctl_get(camera *c,DWORD id,LONG *value,LONG *flags,BOOL exposure) {
 if(!id)return HRESULT_FROM_WIN32(ERROR_NOT_SUPPORTED);
 if(!value||!flags)return E_POINTER;
 DWORD n;HRESULT hr=control_rpc(c,11,id,NULL,0,value,4,&n);if(FAILED(hr))return hr;
 if(n!=4)return E_UNEXPECTED;
 *flags=2;
 if(exposure){LONG mode;*value=exposure_exponent(*value);hr=control_rpc(c,11,0x009a0901,NULL,0,&mode,4,&n);if(SUCCEEDED(hr)&&mode!=1)*flags=1;}
 return hr;
}
static HRESULT ctl_set(camera *c,DWORD id,LONG value,LONG flags,BOOL exposure) {
 if(!id)return HRESULT_FROM_WIN32(ERROR_NOT_SUPPORTED);
 if(flags!=1&&flags!=2)return E_INVALIDARG;
 if(exposure){
  if(flags==2){value=exposure_raw(value);if(value<0)return E_INVALIDARG;}
  LONG mode=flags==1?0:1;HRESULT hr=control_rpc(c,12,0x009a0901,&mode,4,NULL,0,NULL);if(FAILED(hr)||flags==1)return hr;
 }
 else if(flags!=2)return E_NOTIMPL;
 return control_rpc(c,12,id,&value,4,NULL,0,NULL);
}
static HRESULT WINAPI camctl_range(IAMCameraControl *p,LONG prop,LONG *a,LONG *b,LONG *d,LONG *e,LONG *f) { return ctl_range(CONTAINING_RECORD(p,camera,camctl),prop==CameraControl_Exposure?0x009a0902:0,a,b,d,e,f,TRUE); }
static HRESULT WINAPI camctl_get(IAMCameraControl *p,LONG prop,LONG *v,LONG *f) { return ctl_get(CONTAINING_RECORD(p,camera,camctl),prop==CameraControl_Exposure?0x009a0902:0,v,f,TRUE); }
static HRESULT WINAPI camctl_set(IAMCameraControl *p,LONG prop,LONG v,LONG f) { return ctl_set(CONTAINING_RECORD(p,camera,camctl),prop==CameraControl_Exposure?0x009a0902:0,v,f,TRUE); }
static const IAMCameraControlVtbl camctl_vtable={camctl_qi,camctl_add,camctl_release,camctl_range,camctl_set,camctl_get};
static HRESULT WINAPI procctl_range(IAMVideoProcAmp *p,LONG prop,LONG *a,LONG *b,LONG *d,LONG *e,LONG *f) { return ctl_range(CONTAINING_RECORD(p,camera,procctl),proc_id(prop),a,b,d,e,f,FALSE); }
static HRESULT WINAPI procctl_get(IAMVideoProcAmp *p,LONG prop,LONG *v,LONG *f) { return ctl_get(CONTAINING_RECORD(p,camera,procctl),proc_id(prop),v,f,FALSE); }
static HRESULT WINAPI procctl_set(IAMVideoProcAmp *p,LONG prop,LONG v,LONG f) { return ctl_set(CONTAINING_RECORD(p,camera,procctl),proc_id(prop),v,f,FALSE); }
static const IAMVideoProcAmpVtbl procctl_vtable={procctl_qi,procctl_add,procctl_release,procctl_range,procctl_set,procctl_get};
