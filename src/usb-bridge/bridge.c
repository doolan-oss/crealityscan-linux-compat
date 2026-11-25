/* Local experimental MF camera source. Synthetic mode never opens hardware.
 * Native Windows PE DLL; the real V4L2 transport is an opt-in local helper.
 * In SDK mode the scanner model's identity and stream modes come from the
 * launcher's environment (scanner-profile.h); without it, the Pika's apply.
 */
#define WIN32_LEAN_AND_MEAN
#define COBJMACROS
#define CONST_VTABLE
#include <mfapi.h>
#include <mferror.h>
#include <mfidl.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include <winsock2.h>
#include "control-interfaces.h"
#include "scanner-profile.h"

#define WIDTH 1280
#define HEIGHT 960
#define FRAME_BYTES (WIDTH * HEIGHT)
#define DURATION 166666
#define MAX_REQUESTS 16
#define LOG(...)                                                               \
  do {                                                                         \
    fprintf(stderr, "[pika-camera-bridge] ");                                  \
    fprintf(stderr, __VA_ARGS__);                                              \
    fprintf(stderr, "\n");                                                     \
  } while (0)
static const WCHAR synthetic_link[] = L"pikacam://synthetic-grey-1280x960";
static const WCHAR physical_link[] = L"pikacam://explicit-v4l2-endpoint";
static LONG live_sources;
typedef struct camera {
  IMFMediaSource source;
  IMFMediaStream stream;
  BridgeTopology topology;
  BridgeKs ks;
  IAMCameraControl camctl;
  IAMVideoProcAmp procctl;
  LONG refs;
  CRITICAL_SECTION lock, io_lock;
  DWORD fourcc, capacity, fps, width, height;
  IMFMediaEventQueue *source_events, *stream_events;
  IMFPresentationDescriptor *pd;
  IMFStreamDescriptor *sd;
  HANDLE wake, thread;
  BOOL shutdown, running, announced;
  HRESULT terminal_error;
  IUnknown *tokens[MAX_REQUESTS];
  unsigned head, count;
  ULONGLONG sequence, generation;
  BOOL physical, wsa_started;
  unsigned endpoint;
  SOCKET socket;
} camera;
typedef struct activation {
  IMFActivate iface;
  LONG refs;
  IMFAttributes *attrs;
  IMFMediaSource *source;
  unsigned endpoint;
  CRITICAL_SECTION lock;
} activation;
static camera *from_source(IMFMediaSource *p) {
  return CONTAINING_RECORD(p, camera, source);
}
static camera *from_stream(IMFMediaStream *p) {
  return CONTAINING_RECORD(p, camera, stream);
}
static activation *from_activation(IMFActivate *p) {
  return CONTAINING_RECORD(p, activation, iface);
}
static HRESULT new_source(unsigned endpoint, IMFMediaSource **out);
static HRESULT WINAPI source_shutdown(IMFMediaSource *p);
static BOOL backend_is(const char *value) {
  char prefix[1024], guard[1024], v[32];
  DWORD pn=GetEnvironmentVariableA("WINEPREFIX",prefix,sizeof(prefix));
  DWORD gn=GetEnvironmentVariableA("CREALITY_PREFIX_GUARD",guard,sizeof(guard));
  if (!pn || pn>=sizeof(prefix) || !gn || gn>=sizeof(guard) ||
      strcmp(prefix, guard))
    return FALSE;
  return GetEnvironmentVariableA("PIKA_CAMERA_BACKEND", v, sizeof(v)) &&
         !strcmp(v, value);
}

static BOOL sdk_mode(void) {
  char value[8];
  return backend_is("v4l2") && GetEnvironmentVariableA("PIKA_SDK_IDENTITY", value, sizeof(value)) && !strcmp(value, "1");
}
static BOOL profile_env(const char *name, char *buffer, DWORD size) {
  DWORD n = GetEnvironmentVariableA(name, buffer, size);
  return n && n < size;
}
/* USB product ID of the connected scanner model (vendor is always 2bc5). */
static unsigned scanner_pid(void) {
  char text[16];
  unsigned pid;
  if (!profile_env("PIKA_USB_PID", text, sizeof(text))) return profile_default_pid;
  if (profile_parse_pid(text, &pid)) { LOG("invalid PIKA_USB_PID %s", text); return profile_default_pid; }
  return pid;
}
static BOOL load_modes(unsigned endpoint, profile_modes *modes) {
  char name[16], text[2048];
  snprintf(name, sizeof(name), "PIKA_MODES_%u", endpoint);
  const char *value = profile_env(name, text, sizeof(text)) ? text : profile_default_modes[endpoint];
  if (!profile_parse_modes(value, modes)) return TRUE;
  LOG("invalid %s: %s", name, value);
  return FALSE;
}
static BOOL load_units(profile_units *units) {
  char text[512];
  const char *value = profile_env("PIKA_XU", text, sizeof(text)) ? text : profile_default_units;
  if (!profile_parse_units(value, units)) return TRUE;
  LOG("invalid PIKA_XU: %s", value);
  return FALSE;
}
/* Media Foundation description of a native or helper-decoded V4L2 format.
 * Stride 0 marks compressed samples. */
static BOOL sdk_format(unsigned fourcc, unsigned width, unsigned height, const GUID **subtype, DWORD *capacity, DWORD *stride);
static HRESULT endpoint_link(unsigned endpoint, WCHAR *out, unsigned capacity) {
  if (!sdk_mode()) {
    const WCHAR *v = backend_is("synthetic") ? synthetic_link : physical_link;
    if (wcslen(v) >= capacity) return E_INVALIDARG;
    lstrcpyW(out, v);
    return S_OK;
  }
  WCHAR serial[128], revision[16];
  if (!GetEnvironmentVariableW(L"PIKA_USB_SERIAL", serial, 128) ||
      !GetEnvironmentVariableW(L"PIKA_USB_REVISION", revision, 16)) return E_ACCESSDENIED;
  if (endpoint > 1 || capacity < 256) return E_INVALIDARG;
  /* Virtual MF link derived from measured physical VID/PID, interface, revision
   * and serial. This is not an assertion that Wine created a PnP camera node. */
  swprintf(out, capacity, L"\\\\?\\usb#vid_2bc5&pid_%04x&mi_%02u#%ls&%ls&0&0&0#{e5323777-f976-4f5b-9b55-b94699c46e44}\\global",
           scanner_pid(), endpoint * 2, revision, serial);
  return S_OK;
}

static ULONG camera_add(camera *c) { return InterlockedIncrement(&c->refs); }
static ULONG camera_release(camera *c) {
  ULONG refs = InterlockedDecrement(&c->refs);
  if (!refs) {
    if (c->thread)
      CloseHandle(c->thread);
    if (c->wake)
      CloseHandle(c->wake);
    if (c->source_events)
      IMFMediaEventQueue_Release(c->source_events);
    if (c->stream_events)
      IMFMediaEventQueue_Release(c->stream_events);
    if (c->pd)
      IMFPresentationDescriptor_Release(c->pd);
    if (c->sd)
      IMFStreamDescriptor_Release(c->sd);
    DeleteCriticalSection(&c->io_lock);
    DeleteCriticalSection(&c->lock);
    InterlockedDecrement(&live_sources);
    free(c);
  }
  return refs;
}
static HRESULT WINAPI source_qi(IMFMediaSource *p, REFIID iid, void **out) {
  if (!out)
    return E_POINTER;
  *out = NULL;
  if (IsEqualIID(iid, &IID_IUnknown) || IsEqualIID(iid, &IID_IMFMediaSource) ||
      IsEqualIID(iid, &IID_IMFMediaEventGenerator)) {
    *out = p;
    camera_add(from_source(p));
    return S_OK;
  }
  if (sdk_mode()) {
    camera *c=from_source(p);
    if(IsEqualIID(iid,&bridge_iid_topology))*out=&c->topology;
    else if(IsEqualIID(iid,&bridge_iid_ks))*out=&c->ks;
    else if(IsEqualIID(iid,&IID_IAMCameraControl))*out=&c->camctl;
    else if(IsEqualIID(iid,&IID_IAMVideoProcAmp))*out=&c->procctl;
    if(*out){camera_add(c);return S_OK;}
  }
  LOG("unsupported source QI %08lx-%04x-%04x", iid->Data1, iid->Data2,
      iid->Data3);
  return E_NOINTERFACE;
}
static ULONG WINAPI source_add(IMFMediaSource *p) {
  return camera_add(from_source(p));
}
static ULONG WINAPI source_release(IMFMediaSource *p) {
  return camera_release(from_source(p));
}
static HRESULT WINAPI stream_qi(IMFMediaStream *p, REFIID iid, void **out) {
  if (!out)
    return E_POINTER;
  *out = NULL;
  if (IsEqualIID(iid, &IID_IUnknown) || IsEqualIID(iid, &IID_IMFMediaStream) ||
      IsEqualIID(iid, &IID_IMFMediaEventGenerator)) {
    *out = p;
    camera_add(from_stream(p));
    return S_OK;
  }
  return E_NOINTERFACE;
}
static ULONG WINAPI stream_add(IMFMediaStream *p) {
  return camera_add(from_stream(p));
}
static ULONG WINAPI stream_release(IMFMediaStream *p) {
  return camera_release(from_stream(p));
}
#define EVENTS(prefix, iface, from, member)                                    \
  static HRESULT WINAPI prefix##_get(iface *p, DWORD flags,                    \
                                     IMFMediaEvent **event) {                  \
    return IMFMediaEventQueue_GetEvent(from(p)->member, flags, event);         \
  }                                                                            \
  static HRESULT WINAPI prefix##_begin(iface *p, IMFAsyncCallback *cb,         \
                                       IUnknown *state) {                      \
    return IMFMediaEventQueue_BeginGetEvent(from(p)->member, cb, state);       \
  }                                                                            \
  static HRESULT WINAPI prefix##_end(iface *p, IMFAsyncResult *r,              \
                                     IMFMediaEvent **event) {                  \
    return IMFMediaEventQueue_EndGetEvent(from(p)->member, r, event);          \
  }                                                                            \
  static HRESULT WINAPI prefix##_queue(iface *p, MediaEventType t, REFGUID g,  \
                                       HRESULT h, const PROPVARIANT *v) {      \
    return IMFMediaEventQueue_QueueEventParamVar(from(p)->member, t, g, h, v); \
  }
EVENTS(source, IMFMediaSource, from_source, source_events)
EVENTS(stream, IMFMediaStream, from_stream, stream_events)
static HRESULT WINAPI source_characteristics(IMFMediaSource *p, DWORD *flags) {
  if (!flags)
    return E_POINTER;
  if (from_source(p)->shutdown)
    return MF_E_SHUTDOWN;
  *flags = MFMEDIASOURCE_IS_LIVE;
  return S_OK;
}
static HRESULT WINAPI source_pd(IMFMediaSource *p,
                                IMFPresentationDescriptor **out) {
  if (!out)
    return E_POINTER;
  *out = NULL;
  if (from_source(p)->shutdown)
    return MF_E_SHUTDOWN;
  return IMFPresentationDescriptor_Clone(from_source(p)->pd, out);
}
static HRESULT WINAPI stream_source(IMFMediaStream *p, IMFMediaSource **out) {
  if (!out)
    return E_POINTER;
  *out = NULL;
  camera *c = from_stream(p);
  if (c->shutdown)
    return MF_E_SHUTDOWN;
  *out = &c->source;
  camera_add(c);
  return S_OK;
}
static HRESULT WINAPI stream_descriptor(IMFMediaStream *p,
                                        IMFStreamDescriptor **out) {
  if (!out)
    return E_POINTER;
  *out = NULL;
  camera *c = from_stream(p);
  if (c->shutdown)
    return MF_E_SHUTDOWN;
  *out = c->sd;
  IMFStreamDescriptor_AddRef(*out);
  return S_OK;
}
static void clear_tokens(camera *c) {
  while (c->count) {
    IUnknown *t = c->tokens[c->head];
    c->head = (c->head + 1) % MAX_REQUESTS;
    c->count--;
    if (t)
      IUnknown_Release(t);
  }
}
static BOOL sdk_profile(unsigned endpoint, REFGUID subtype, UINT64 size, UINT64 rate, DWORD *fourcc, DWORD *capacity);
static void sdk_close(camera *c);
static HRESULT WINAPI source_start(IMFMediaSource *p,
                                   IMFPresentationDescriptor *pd,
                                   const GUID *fmt, const PROPVARIANT *pos) {
  camera *c = from_source(p);
  if (!pd || !pos)
    return E_INVALIDARG;
  if (fmt && !IsEqualGUID(fmt, &GUID_NULL))
    return MF_E_UNSUPPORTED_TIME_FORMAT;
  if (pos->vt != VT_EMPTY && !(pos->vt == VT_I8 && pos->hVal.QuadPart == 0))
    return MF_E_INVALIDREQUEST;
  BOOL selected = FALSE;
  IMFStreamDescriptor *sd = NULL;
  HRESULT hr = IMFPresentationDescriptor_GetStreamDescriptorByIndex(
      pd, 0, &selected, &sd);
  if (FAILED(hr))
    return hr;
  IMFMediaTypeHandler *handler = NULL;
  IMFMediaType *type = NULL;
  GUID subtype;
  UINT64 size = 0, rate = 0;
  hr = IMFStreamDescriptor_GetMediaTypeHandler(sd, &handler);
  IMFStreamDescriptor_Release(sd);
  if (SUCCEEDED(hr))
    hr = IMFMediaTypeHandler_GetCurrentMediaType(handler, &type);
  if (handler)
    IMFMediaTypeHandler_Release(handler);
  if (SUCCEEDED(hr))
    hr = IMFMediaType_GetGUID(type, &MF_MT_SUBTYPE, &subtype);
  if (SUCCEEDED(hr))
    hr = IMFMediaType_GetUINT64(type, &MF_MT_FRAME_SIZE, &size);
  if (SUCCEEDED(hr))
    hr = IMFMediaType_GetUINT64(type, &MF_MT_FRAME_RATE, &rate);
  if (type)
    IMFMediaType_Release(type);
  if (FAILED(hr))
    return hr;
  DWORD fourcc=0,capacity=FRAME_BYTES;
  if (!selected || (sdk_mode() ? !sdk_profile(c->endpoint,&subtype,size,rate,&fourcc,&capacity) :
       size != (((UINT64)WIDTH << 32) | HEIGHT) ||
       !IsEqualGUID(&subtype,&MFVideoFormat_L8) || rate != (((UINT64)60 << 32)|1))) {
    LOG("start refused endpoint=%u selected=%d subtype=%08lx size=%ux%u rate=%u/%u",c->endpoint,selected,subtype.Data1,
        (unsigned)(size>>32),(unsigned)size,(unsigned)(rate>>32),(unsigned)rate);
    return MF_E_INVALIDMEDIATYPE;
  }
  EnterCriticalSection(&c->lock);
  if (c->shutdown) {
    LeaveCriticalSection(&c->lock);
    return MF_E_SHUTDOWN;
  }
  if(FAILED(c->terminal_error)){HRESULT error=c->terminal_error;LeaveCriticalSection(&c->lock);return error;}
  c->fourcc=fourcc;c->capacity=capacity;c->fps=rate>>32;c->width=size>>32;c->height=(DWORD)size;
  LOG("start endpoint=%u subtype=%08lx fps=%lu capacity=%lu size=%lux%lu",c->endpoint,subtype.Data1,c->fps,c->capacity,c->width,c->height);
  c->running = TRUE;
  IMFMediaEventQueue_QueueEventParamUnk(
      c->source_events, c->announced ? MEUpdatedStream : MENewStream,
      &GUID_NULL, S_OK, (IUnknown *)&c->stream);
  c->announced = TRUE;
  PROPVARIANT zero = {0};
  zero.vt = VT_I8;
  IMFMediaEventQueue_QueueEventParamVar(c->source_events, MESourceStarted,
                                        &GUID_NULL, S_OK, &zero);
  IMFMediaEventQueue_QueueEventParamVar(c->stream_events, MEStreamStarted,
                                        &GUID_NULL, S_OK, &zero);
  SetEvent(c->wake);
  LeaveCriticalSection(&c->lock);
  return S_OK;
}
static HRESULT WINAPI source_stop(IMFMediaSource *p) {
  camera *c = from_source(p);
  EnterCriticalSection(&c->lock);
  if (c->shutdown) {
    LeaveCriticalSection(&c->lock);
    return MF_E_SHUTDOWN;
  }
  c->running = FALSE;
  c->generation++;
  clear_tokens(c);
  IMFMediaEventQueue_QueueEventParamVar(c->stream_events, MEStreamStopped,
                                        &GUID_NULL, S_OK, NULL);
  IMFMediaEventQueue_QueueEventParamVar(c->source_events, MESourceStopped,
                                        &GUID_NULL, S_OK, NULL);
  LeaveCriticalSection(&c->lock);
  if(sdk_mode()){EnterCriticalSection(&c->io_lock);sdk_close(c);LeaveCriticalSection(&c->io_lock);}
  return S_OK;
}
static HRESULT WINAPI source_pause(IMFMediaSource *p) {
  if (from_source(p)->shutdown)
    return MF_E_SHUTDOWN;
  return MF_E_INVALID_STATE_TRANSITION; /* Live source: pause unsupported, use
                                           Stop/Start. */
}
static HRESULT WINAPI stream_request(IMFMediaStream *p, IUnknown *token) {
  camera *c = from_stream(p);
  EnterCriticalSection(&c->lock);
  HRESULT hr = S_OK;
  if (c->shutdown)
    hr = MF_E_SHUTDOWN;
  else if (FAILED(c->terminal_error))
    hr = MF_E_END_OF_STREAM;
  else if (!c->running || c->count == MAX_REQUESTS)
    hr = MF_E_NOTACCEPTING;
  else {
    if (token)
      IUnknown_AddRef(token);
    c->tokens[(c->head + c->count) % MAX_REQUESTS] = token;
    c->count++;
    SetEvent(c->wake);
  }
  LeaveCriticalSection(&c->lock);
  return hr;
}
static BOOL socket_all(SOCKET s, void *data, int len, BOOL sending) {
  char *p = data;
  while (len) {
    int n = sending ? send(s, p, len, 0) : recv(s, p, len, 0);
    if (n <= 0)
      return FALSE;
    p += n;
    len -= n;
  }
  return TRUE;
}
#include "controls.inc"
#include "stream-transport.inc"

/* Helper protocol: 64-byte token, then FRAME\n; reply 16 bytes of
 * little-endian status,size,sequence,reserved, followed by GREY frame bytes.
 * This physical path is never used in synthetic mode. */
static HRESULT physical_frame(camera *c, BYTE *data, ULONGLONG *seq) {
  if (c->socket == INVALID_SOCKET) {
    char token[64] = {0}, port[16] = {0};
    WSADATA w;
    if (!GetEnvironmentVariableA("PIKA_CAMERA_TOKEN", token, sizeof(token)) ||
        !GetEnvironmentVariableA("PIKA_CAMERA_PORT", port, sizeof(port)))
      return E_ACCESSDENIED;
    char *end;
    long number = strtol(port, &end, 10);
    if (*end || number < 1024 || number > 65535)
      return E_INVALIDARG;
    if (WSAStartup(MAKEWORD(2, 2), &w))
      return E_FAIL;
    c->wsa_started = TRUE;
    c->socket = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (c->socket == INVALID_SOCKET)
      return E_FAIL;
    DWORD timeout = 3000;
    setsockopt(c->socket, SOL_SOCKET, SO_RCVTIMEO, (char *)&timeout,
               sizeof(timeout));
    setsockopt(c->socket, SOL_SOCKET, SO_SNDTIMEO, (char *)&timeout,
               sizeof(timeout));
    struct sockaddr_in addr = {0};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    addr.sin_port = htons((unsigned short)number);
    if (connect(c->socket, (struct sockaddr *)&addr, sizeof(addr)) ||
        !socket_all(c->socket, token, 64, TRUE))
      return E_FAIL;
  }
  DWORD h[4] = {0};
  char request[] = "FRAME\n";
  if (!socket_all(c->socket, request, 6, TRUE) ||
      !socket_all(c->socket, h, sizeof(h), FALSE))
    return E_FAIL;
  if (h[0] || h[1] != FRAME_BYTES)
    return E_FAIL;
  if (!socket_all(c->socket, data, FRAME_BYTES, FALSE))
    return E_FAIL;
  *seq = h[2];
  return S_OK;
}
static DWORD WINAPI worker(void *arg) {
  camera *c = arg;
  for (;;) {
    WaitForSingleObject(c->wake, INFINITE);
    for (;;) {
      EnterCriticalSection(&c->lock);
      if (c->shutdown) {
        LeaveCriticalSection(&c->lock);
        return 0;
      }
      if (!c->running || !c->count) {
        ResetEvent(c->wake);
        LeaveCriticalSection(&c->lock);
        break;
      }
      IUnknown *token = c->tokens[c->head];
      c->head = (c->head + 1) % MAX_REQUESTS;
      c->count--;
      ULONGLONG seq = c->sequence++, generation = c->generation;
      LeaveCriticalSection(&c->lock);
      IMFMediaBuffer *buffer = NULL;
      IMFSample *sample = NULL;
      BYTE *data = NULL;
      BYTE metadata[256]={0};DWORD metadata_len=0;
      DWORD length=c->capacity;
      ULONGLONG timestamp=seq*DURATION;
      HRESULT hr = MFCreateMemoryBuffer(c->capacity, &buffer);
      if (SUCCEEDED(hr))
        hr = IMFMediaBuffer_Lock(buffer, &data, NULL, NULL);
      if (SUCCEEDED(hr)) {
        if(sdk_mode()) hr=sdk_frame(c,data,&length,&timestamp,generation,metadata,&metadata_len);
        else if (c->physical) { hr = physical_frame(c, data, &seq); timestamp=seq*DURATION; }
        else
          for (DWORD i = 0; i < FRAME_BYTES; i++)
            data[i] = (BYTE)((i + seq) % 251);
        IMFMediaBuffer_Unlock(buffer);
      }
      if (SUCCEEDED(hr))
        hr = IMFMediaBuffer_SetCurrentLength(buffer, length);
      if (SUCCEEDED(hr))
        hr = MFCreateSample(&sample);
      if (SUCCEEDED(hr))
        hr = IMFSample_AddBuffer(sample, buffer);
      if (SUCCEEDED(hr))
        hr = IMFSample_SetSampleTime(sample, timestamp);
      if (SUCCEEDED(hr))
        hr = IMFSample_SetSampleDuration(sample, 10000000/c->fps);
      if(SUCCEEDED(hr)&&sdk_mode())hr=sdk_sample_metadata(sample,metadata,metadata_len);
      if (SUCCEEDED(hr) && token)
        hr = IMFSample_SetUnknown(sample, &MFSampleExtension_Token, token);
      EnterCriticalSection(&c->lock);
      if (!c->shutdown && c->running && c->generation == generation) {
        if (SUCCEEDED(hr))
          IMFMediaEventQueue_QueueEventParamUnk(c->stream_events, MEMediaSample,
                                                &GUID_NULL, S_OK,
                                                (IUnknown *)sample);
        else {
          LOG("frame delivery failed: 0x%08lx; terminating stream", hr);
          c->terminal_error=hr;
          c->running = FALSE;
          clear_tokens(c);
          IMFMediaEventQueue_QueueEventParamVar(c->source_events, MEError,
                                                &GUID_NULL, hr, NULL);
          /* This Wine reader ignores MEError. End the failed stream as well,
           * so pending reads wake with EOS and no fabricated sample. */
          IMFMediaEventQueue_QueueEventParamVar(c->stream_events, MEEndOfStream,
                                               &GUID_NULL, hr, NULL);
          IMFMediaEventQueue_QueueEventParamVar(c->source_events, MEEndOfPresentation,
                                               &GUID_NULL, hr, NULL);
        }
      }
      LeaveCriticalSection(&c->lock);
      if (token)
        IUnknown_Release(token);
      if (sample)
        IMFSample_Release(sample);
      if (buffer)
        IMFMediaBuffer_Release(buffer);
    }
  }
}
static HRESULT WINAPI source_shutdown(IMFMediaSource *p) {
  camera *c = from_source(p);
  EnterCriticalSection(&c->lock);
  if (c->shutdown) {
    LeaveCriticalSection(&c->lock);
    return MF_E_SHUTDOWN;
  }
  c->shutdown = TRUE;
  c->running = FALSE;
  clear_tokens(c);
  SetEvent(c->wake);
  LeaveCriticalSection(&c->lock);
  if (c->thread)
    WaitForSingleObject(c->thread, INFINITE);
  if(sdk_mode()) sdk_close(c);
  if (c->socket != INVALID_SOCKET) {
    closesocket(c->socket);
    c->socket = INVALID_SOCKET;
  }
  if (c->wsa_started) {
    WSACleanup();
    c->wsa_started = FALSE;
  }
  IMFMediaEventQueue_Shutdown(c->source_events);
  IMFMediaEventQueue_Shutdown(c->stream_events);
  return S_OK;
}
static const IMFMediaSourceVtbl source_vtable = {
    source_qi,   source_add,   source_release,         source_get, source_begin,
    source_end,  source_queue, source_characteristics, source_pd,  source_start,
    source_stop, source_pause, source_shutdown};
static const IMFMediaStreamVtbl stream_vtable = {
    stream_qi,         stream_add,    stream_release, stream_get,
    stream_begin,      stream_end,    stream_queue,   stream_source,
    stream_descriptor, stream_request};
#include "pinned-descriptor.inc"
static HRESULT new_source(unsigned endpoint, IMFMediaSource **out) {
  *out = NULL;
  if (!backend_is("synthetic") && !backend_is("v4l2"))
    return E_ACCESSDENIED;
  camera *c = calloc(1, sizeof(*c));
  if (!c)
    return E_OUTOFMEMORY;
  c->source.lpVtbl = &source_vtable;
  c->stream.lpVtbl = &stream_vtable;
  c->topology.lpVtbl=&topo_vtable;
  c->ks.lpVtbl=&ks_vtable;
  c->camctl.lpVtbl=&camctl_vtable;
  c->procctl.lpVtbl=&procctl_vtable;
  c->refs = 1;
  c->endpoint = endpoint;
  c->socket = INVALID_SOCKET;
  c->physical = backend_is("v4l2");
  InitializeCriticalSection(&c->lock);
  InitializeCriticalSection(&c->io_lock);
  c->capacity=FRAME_BYTES;c->fps=60;c->width=WIDTH;c->height=HEIGHT;
  InterlockedIncrement(&live_sources);
  IMFMediaType *types[PROFILE_MAX_TYPES]={0};
  IMFMediaTypeHandler *handler=NULL;
  HRESULT hr=MFCreateEventQueue(&c->source_events);
  if(SUCCEEDED(hr))hr=MFCreateEventQueue(&c->stream_events);
  /* Synthetic and prototype sources offer one fixed 60 fps greyscale type. */
  profile_modes modes={1,{{PROFILE_FOURCC('G','R','E','Y'),WIDTH,HEIGHT,1,{60}}}};
  if(SUCCEEDED(hr)&&sdk_mode()&&!load_modes(endpoint,&modes))hr=E_INVALIDARG;
  unsigned count=0;
#define SET(call) if(SUCCEEDED(hr)) hr=(call)
  for(unsigned m=0;m<modes.count&&SUCCEEDED(hr);m++)for(unsigned r=0;r<modes.modes[m].count&&SUCCEEDED(hr);r++) {
    const profile_mode *mode=&modes.modes[m];
    const GUID *subtype=&MFVideoFormat_L8;
    DWORD bytes=FRAME_BYTES,stride=WIDTH;
    if(sdk_mode()&&!sdk_format(mode->fourcc,mode->width,mode->height,&subtype,&bytes,&stride))hr=E_INVALIDARG;
    unsigned fps=mode->rates[r];
    SET(MFCreateMediaType(&types[count]));
    IMFMediaType *type=types[count++];
    SET(IMFMediaType_SetGUID(type,&MF_MT_MAJOR_TYPE,&MFMediaType_Video));
    SET(IMFMediaType_SetGUID(type,&MF_MT_SUBTYPE,subtype));
    SET(IMFMediaType_SetUINT64(type,&MF_MT_FRAME_SIZE,((UINT64)mode->width<<32)|mode->height));
    SET(IMFMediaType_SetUINT64(type,&MF_MT_FRAME_RATE,((UINT64)fps<<32)|1));
    SET(IMFMediaType_SetUINT64(type,&MF_MT_FRAME_RATE_RANGE_MIN,((UINT64)fps<<32)|1));
    SET(IMFMediaType_SetUINT64(type,&MF_MT_FRAME_RATE_RANGE_MAX,((UINT64)fps<<32)|1));
    SET(IMFMediaType_SetUINT64(type,&MF_MT_PIXEL_ASPECT_RATIO,((UINT64)1<<32)|1));
    SET(IMFMediaType_SetUINT32(type,&MF_MT_INTERLACE_MODE,MFVideoInterlace_Progressive));
    SET(IMFMediaType_SetUINT32(type,&MF_MT_SAMPLE_SIZE,bytes));
    if(stride)SET(IMFMediaType_SetUINT32(type,&MF_MT_DEFAULT_STRIDE,stride));
    SET(IMFMediaType_SetUINT32(type,&MF_MT_ALL_SAMPLES_INDEPENDENT,TRUE));
    SET(IMFMediaType_SetUINT32(type,&MF_MT_FIXED_SIZE_SAMPLES,stride!=0));
  }
  if(sdk_mode()&&SUCCEEDED(hr))
    for(unsigned m=0;m<modes.count;m++)LOG("endpoint=%u offers %.4s %ux%u at %u rates, fastest %u fps",endpoint,
        (const char*)&modes.modes[m].fourcc,modes.modes[m].width,modes.modes[m].height,modes.modes[m].count,modes.modes[m].rates[0]);
  SET(MFCreateStreamDescriptor(0,count,types,&c->sd));
  if(sdk_mode()&&endpoint)SET(wrap_descriptor(&c->sd));
  SET(IMFStreamDescriptor_GetMediaTypeHandler(c->sd,&handler));
  SET(IMFMediaTypeHandler_SetCurrentMediaType(handler,types[0]));
  SET(MFCreatePresentationDescriptor(1,&c->sd,&c->pd));
  SET(IMFPresentationDescriptor_SelectStream(c->pd,0));
  for(unsigned i=0;i<count;i++)if(types[i])IMFMediaType_Release(types[i]);
  if(handler)IMFMediaTypeHandler_Release(handler);
  if (SUCCEEDED(hr)) {
    c->wake = CreateEventW(NULL, TRUE, FALSE, NULL);
    if (!c->wake)
      hr = HRESULT_FROM_WIN32(GetLastError());
  }
  if (SUCCEEDED(hr)) {
    c->thread = CreateThread(NULL, 0, worker, c, 0, NULL);
    if (!c->thread)
      hr = HRESULT_FROM_WIN32(GetLastError());
  }
  if (FAILED(hr)) {
    camera_release(c);
    return hr;
  }
  *out = &c->source;
  if(sdk_mode())LOG("created USB SDK source for scanner 2bc5:%04x endpoint=%u",scanner_pid(),endpoint);
  else LOG("created %s source", c->physical ? "V4L2 prototype" : "SYNTHETIC TEST");
  return S_OK;
}
static HRESULT WINAPI activation_qi(IMFActivate *p, REFIID iid, void **out) {
  if (!out)
    return E_POINTER;
  *out = NULL;
  if (IsEqualIID(iid, &IID_IUnknown) || IsEqualIID(iid, &IID_IMFAttributes) ||
      IsEqualIID(iid, &IID_IMFActivate)) {
    *out = p;
    IMFActivate_AddRef(p);
    return S_OK;
  }
  return E_NOINTERFACE;
}
static ULONG WINAPI activation_add(IMFActivate *p) {
  return InterlockedIncrement(&from_activation(p)->refs);
}
static ULONG WINAPI activation_release(IMFActivate *p) {
  activation *a = from_activation(p);
  ULONG n = InterlockedDecrement(&a->refs);
  if (!n) {
    if (a->source) {
      IMFMediaSource_Shutdown(a->source);
      IMFMediaSource_Release(a->source);
    }
    IMFAttributes_Release(a->attrs);
    DeleteCriticalSection(&a->lock);
    free(a);
  }
  return n;
}
#include "activation-attributes.h"
static HRESULT WINAPI activation_activate(IMFActivate *p, REFIID iid,
                                          void **out) {
  activation *a = from_activation(p);
  if (!out)
    return E_POINTER;
  *out = NULL;
  EnterCriticalSection(&a->lock);
  HRESULT hr = S_OK;
  if (!a->source)
    hr = new_source(a->endpoint, &a->source);
  if (SUCCEEDED(hr))
    hr = IMFMediaSource_QueryInterface(a->source, iid, out);
  LeaveCriticalSection(&a->lock);
  return hr;
}
static HRESULT WINAPI activation_shutdown(IMFActivate *p) {
  activation *a = from_activation(p);
  EnterCriticalSection(&a->lock);
  if (a->source) {
    IMFMediaSource_Shutdown(a->source);
    IMFMediaSource_Release(a->source);
    a->source = NULL;
  }
  LeaveCriticalSection(&a->lock);
  return S_OK;
}
static HRESULT WINAPI activation_detach(IMFActivate *p) {
  activation *a = from_activation(p);
  EnterCriticalSection(&a->lock);
  if (a->source) {
    IMFMediaSource_Release(a->source);
    a->source = NULL;
  }
  LeaveCriticalSection(&a->lock);
  return S_OK;
}
static const IMFActivateVtbl activation_vtable = {
    activation_qi,       activation_add,
    activation_release,  ATTRIBUTE_VTABLE_ENTRIES activation_activate,
    activation_shutdown, activation_detach};
#include "source-reader.inc"
#include "device-tree.inc"

HRESULT WINAPI MFEnumDeviceSources(IMFAttributes *attrs, IMFActivate ***out,
                                   UINT32 *count) {
  if (!attrs || !out || !count)
    return E_INVALIDARG;
  *out = NULL;
  *count = 0;
  GUID type;
  HRESULT hr =
      IMFAttributes_GetGUID(attrs, &MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE, &type);
  if (FAILED(hr))
    return hr;
  if (!IsEqualGUID(&type, &MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_GUID))
    return E_NOTIMPL;
  if (!backend_is("synthetic") && !backend_is("v4l2"))
    return S_OK;
  GUID category;
  if (SUCCEEDED(IMFAttributes_GetGUID(attrs,&MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_CATEGORY,&category))) {
    LOG("requested camera category %08lx-%04x-%04x", category.Data1,category.Data2,category.Data3);
    /* These USB UVC cameras belong to the video-camera category, not the
     * separately enumerated Windows sensor-camera category. */
    if (category.Data1==0x24e552d7 && category.Data2==0x6523 && category.Data3==0x47f7) return S_OK;
  }
  install_device_tree();
  unsigned n = sdk_mode() ? 2 : 1;
  *out = CoTaskMemAlloc(n * sizeof(**out));
  if (!*out) return E_OUTOFMEMORY;
  for (unsigned i = 0; i < n; i++) {
    activation *a = calloc(1, sizeof(*a));
    if (!a) { hr = E_OUTOFMEMORY; break; }
    a->iface.lpVtbl = &activation_vtable;
    a->refs = 1;
    a->endpoint = i;
    InitializeCriticalSection(&a->lock);
    hr = MFCreateAttributes(&a->attrs, 4);
    if (FAILED(hr)) { DeleteCriticalSection(&a->lock); free(a); break; }
    WCHAR link[512];
    SET(endpoint_link(i, link, 512));
    SET(IMFAttributes_SetGUID(a->attrs, &MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE,
                              &MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_GUID));
    /* SDK mode: the USB interface names, as Windows shows them. */
    WCHAR name[128], variable[32];
    swprintf(variable, 32, L"PIKA_CAMERA_NAME_%u", i);
    DWORD named = sdk_mode() ? GetEnvironmentVariableW(variable, name, 128) : 0;
    if (!named || named >= 128)
      lstrcpyW(name, sdk_mode() ? (i ? L"Creality Pika RGB Camera" : L"Creality Pika Depth Camera") :
               (backend_is("synthetic") ? L"SYNTHETIC TEST CAMERA - NOT PIKA" : L"EXPERIMENTAL V4L2 endpoint - not SDK-ready"));
    SET(IMFAttributes_SetString(a->attrs, &MF_DEVSOURCE_ATTRIBUTE_FRIENDLY_NAME, name));
    SET(IMFAttributes_SetString(a->attrs, &MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_SYMBOLIC_LINK, link));
    if (FAILED(hr)) { activation_release(&a->iface); break; }
    (*out)[i] = &a->iface;
    ++*count;
    LOG("enumeration: %ls (%ls)", link, name);
  }
  if (FAILED(hr)) {
    for (UINT32 i = 0; i < *count; i++) IMFActivate_Release((*out)[i]);
    CoTaskMemFree(*out); *out = NULL; *count = 0;
  }
  return hr;
}

HRESULT WINAPI MFCreateDeviceSource(IMFAttributes *attrs,
                                    IMFMediaSource **out) {
  if (!attrs || !out)
    return E_INVALIDARG;
  *out = NULL;
  GUID type;
  WCHAR link[512];
  HRESULT hr =
      IMFAttributes_GetGUID(attrs, &MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE, &type);
  if (FAILED(hr))
    return hr;
  if (!IsEqualGUID(&type, &MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_GUID))
    return E_NOTIMPL;
  hr = IMFAttributes_GetString(
      attrs, &MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_SYMBOLIC_LINK, link,
      512, NULL);
  if (FAILED(hr))
    return hr;
  for (unsigned i = 0; i < (sdk_mode() ? 2u : 1u); i++) {
    WCHAR expected[512];
    hr = endpoint_link(i, expected, 512);
    if (FAILED(hr)) return hr;
    if (!lstrcmpiW(link, expected)) return new_source(i, out);
  }
  LOG("source lookup failed: %ls", link);
  return MF_E_NOT_FOUND;
}
LONG WINAPI PikaBridgeLiveSources(void) { return live_sources; }
