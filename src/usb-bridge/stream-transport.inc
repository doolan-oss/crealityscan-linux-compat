/* SDK mode uses raw, negotiated per-endpoint streams. All Winsock lifetime
 * management shares the process-lifetime control reference. No synthetic data. */
static const GUID sdk_y8={0x20203859,0,0x0010,{0x80,0,0,0xaa,0,0x38,0x9b,0x71}};
static BOOL sdk_format(unsigned fourcc, unsigned width, unsigned height, const GUID **subtype, DWORD *capacity, DWORD *stride) {
  DWORD pixels = width * height;
  switch (fourcc) {
  case PROFILE_FOURCC('G','R','E','Y'): *subtype=&sdk_y8; *capacity=pixels; *stride=width; return TRUE;
  case PROFILE_FOURCC('M','J','P','G'): *subtype=&MFVideoFormat_MJPG; *capacity=pixels*3; *stride=0; return TRUE;
  case PROFILE_FOURCC('Y','U','Y','V'): *subtype=&MFVideoFormat_YUY2; *capacity=pixels*2; *stride=width*2; return TRUE;
  /* Decoded from the camera's MJPEG by the native helper. */
  case PROFILE_FOURCC('N','V','1','2'): *subtype=&MFVideoFormat_NV12; *capacity=pixels*3/2; *stride=width; return TRUE;
  case PROFILE_FOURCC('B','G','R','3'): *subtype=&MFVideoFormat_RGB24; *capacity=pixels*3; *stride=width*3; return TRUE;
  }
  return FALSE;
}
/* The requested type must be one this endpoint offered. */
static BOOL sdk_profile(unsigned endpoint, REFGUID subtype, UINT64 size, UINT64 rate, DWORD *fourcc, DWORD *capacity) {
  profile_modes modes;
  if (endpoint > 1 || (DWORD)rate != 1 || !load_modes(endpoint, &modes)) return FALSE;
  unsigned width = size >> 32, height = (DWORD)size, fps = rate >> 32;
  for (unsigned i = 0; i < modes.count; i++) {
    const profile_mode *m = &modes.modes[i];
    const GUID *offered; DWORD stride;
    if (m->width != width || m->height != height || !sdk_format(m->fourcc, width, height, &offered, capacity, &stride) ||
        !IsEqualGUID(offered, subtype)) continue;
    for (unsigned r = 0; r < m->count; r++)
      if (m->rates[r] == fps) { *fourcc = m->fourcc; return TRUE; }
  }
  return FALSE;
}
static void sdk_close(camera *c) {
  /* Caller serializes with io_lock. Stop acknowledgement follows Linux cleanup. */
  if (c->socket != INVALID_SOCKET) {
    char op='S'; DWORD status=0;
    if (!control_transfer(c->socket,&op,1,TRUE) || !control_transfer(c->socket,&status,4,FALSE) || status)
      LOG("stream stop endpoint=%u: helper disconnected or cleanup error=%lu",c->endpoint,status);
    closesocket(c->socket);c->socket=INVALID_SOCKET;
  }
}
static HRESULT sdk_frame(camera *c, BYTE *data, DWORD *length, ULONGLONG *timestamp, ULONGLONG generation, BYTE *metadata, DWORD *metadata_len) {
  HRESULT hr=E_FAIL;
  EnterCriticalSection(&c->io_lock);
  EnterCriticalSection(&c->lock);
  BOOL active=c->running&&!c->shutdown&&c->generation==generation;
  LeaveCriticalSection(&c->lock);
  if (!active) {LeaveCriticalSection(&c->io_lock);return MF_E_INVALIDREQUEST;}
  if (c->socket == INVALID_SOCKET) {
    char token[64]={0},port[16]={0};
    if (!GetEnvironmentVariableA("PIKA_CAMERA_TOKEN",token,sizeof(token)) ||
        !GetEnvironmentVariableA("PIKA_CAMERA_PORT",port,sizeof(port))) goto done;
    if(!InitOnceExecuteOnce(&control_winsock_once,control_winsock_init,NULL,NULL)) goto done;
    c->socket=socket(AF_INET,SOCK_STREAM,IPPROTO_TCP);if(c->socket==INVALID_SOCKET)goto done;
    struct sockaddr_in addr={0};addr.sin_family=AF_INET;addr.sin_addr.s_addr=htonl(INADDR_LOOPBACK);addr.sin_port=htons((unsigned short)atoi(port));
    if(!bridge_connect(c->socket,&addr))goto done;
    int nodelay=1;setsockopt(c->socket,IPPROTO_TCP,TCP_NODELAY,(char*)&nodelay,sizeof(nodelay));
    DWORD req[6]={0x324b4950,c->endpoint,c->fourcc,c->fps,c->width,c->height},status=0;
    if(!control_transfer(c->socket,token,64,TRUE)||!control_transfer(c->socket,req,sizeof(req),TRUE)||
       !control_transfer(c->socket,&status,4,FALSE)||status){LOG("stream setup endpoint=%u error=%lu",c->endpoint,status);goto done;}
  }
  char op='N';DWORD h[8]={0};
  if(!control_transfer(c->socket,&op,1,TRUE)||!control_transfer(c->socket,h,sizeof(h),FALSE))goto done;
  if(h[0]||!h[1]||h[1]>c->capacity||h[6]>255){LOG("native frame endpoint=%u error=%lu bytes=%lu",c->endpoint,h[0],h[1]);goto done;}
  if(!control_transfer(c->socket,data,h[1],FALSE))goto done;
  if(h[6]&&!control_transfer(c->socket,metadata,h[6],FALSE))goto done;
  *metadata_len=h[6];
  *length=h[1];*timestamp=(((ULONGLONG)h[5]<<32)|h[4])*10;
  if(h[2]<3||!(h[2]%120))LOG("native frame endpoint=%u sequence=%lu bytes=%lu timestamp100ns=%llu",c->endpoint,h[2],h[1],*timestamp);
  hr=S_OK;
done:
  if(FAILED(hr)&&c->socket!=INVALID_SOCKET){closesocket(c->socket);c->socket=INVALID_SOCKET;}
  LeaveCriticalSection(&c->io_lock);return hr;
}
/* Windows UVC metadata wraps the actual PTS/SCR twice in a 40-byte header.
 * Preserve device extension bytes verbatim; never substitute host timestamps. */
static HRESULT sdk_sample_metadata(IMFSample *sample,const BYTE *uvc,DWORD len){
  static const GUID capture={0x2ebe23a8,0xfaf5,0x444a,{0xa6,0xa2,0xeb,0x81,0x08,0x80,0xab,0x5d}};
  static const GUID raw={0x9252077b,0x2680,0x49b9,{0xae,0x02,0xb1,0x90,0x75,0x97,0x3b,0x70}};
  if(!len)return S_OK;
  if(len<12||len>255||uvc[0]!=len||(uvc[1]&0x0c)!=0x0c)return E_INVALIDARG;
  DWORD size=40+len-12;
  IMFMediaBuffer *buffer=NULL;IMFAttributes *attrs=NULL;BYTE *data=NULL;
  HRESULT hr=MFCreateMemoryBuffer(size,&buffer);
  if(SUCCEEDED(hr))hr=IMFMediaBuffer_Lock(buffer,&data,NULL,NULL);
  if(SUCCEEDED(hr)){
    memset(data,0,size);((DWORD*)data)[0]=2;((DWORD*)data)[1]=size;
    memcpy(data+8,uvc+2,10);memcpy(data+24,uvc+2,10);memcpy(data+40,uvc+12,len-12);
    IMFMediaBuffer_Unlock(buffer);hr=IMFMediaBuffer_SetCurrentLength(buffer,size);
  }
  if(SUCCEEDED(hr))hr=MFCreateAttributes(&attrs,1);
  if(SUCCEEDED(hr))hr=IMFAttributes_SetUnknown(attrs,&raw,(IUnknown*)buffer);
  if(SUCCEEDED(hr))hr=IMFSample_SetUnknown(sample,&capture,(IUnknown*)attrs);
  if(attrs)IMFAttributes_Release(attrs);if(buffer)IMFMediaBuffer_Release(buffer);return hr;
}
