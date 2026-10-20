#define WIN32_LEAN_AND_MEAN
#define COBJMACROS
#define CONST_VTABLE
#include <mfapi.h>
#include <mferror.h>
#include <mfidl.h>
#include <mfreadwrite.h>
#include <stdio.h>
#include <stdlib.h>
#include <windows.h>
#define CHECK(call)                                                            \
  do {                                                                         \
    HRESULT h = (call);                                                        \
    if (FAILED(h)) {                                                           \
      fprintf(stderr, "FAIL line %d: %s = 0x%08lx\n", __LINE__, #call, h);     \
      ExitProcess(1);                                                          \
    }                                                                          \
  } while (0)
#define ASSERT(c)                                                              \
  do {                                                                         \
    if (!(c)) {                                                                \
      fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #c);                     \
      ExitProcess(1);                                                          \
    }                                                                          \
  } while (0)
typedef struct callback {
  IMFSourceReaderCallback iface;
  LONG refs;
  HANDLE ready;
  HRESULT status;
  DWORD stream, flags;
  LONGLONG timestamp;
  IMFSample *sample;
} callback;
static HRESULT WINAPI cb_qi(IMFSourceReaderCallback *p, REFIID iid,
                            void **out) {
  if (!out)
    return E_POINTER;
  *out = NULL;
  if (IsEqualIID(iid, &IID_IUnknown) ||
      IsEqualIID(iid, &IID_IMFSourceReaderCallback)) {
    *out = p;
    IMFSourceReaderCallback_AddRef(p);
    return S_OK;
  }
  return E_NOINTERFACE;
}
static ULONG WINAPI cb_add(IMFSourceReaderCallback *p) {
  return InterlockedIncrement(&((callback *)p)->refs);
}
static ULONG WINAPI cb_release(IMFSourceReaderCallback *p) {
  return InterlockedDecrement(&((callback *)p)->refs);
}
static HRESULT WINAPI cb_read(IMFSourceReaderCallback *p, HRESULT status,
                              DWORD stream, DWORD flags, LONGLONG timestamp,
                              IMFSample *sample) {
  callback *c = (callback *)p;
  c->status = status;
  c->stream = stream;
  c->flags = flags;
  c->timestamp = timestamp;
  c->sample = sample;
  if (sample)
    IMFSample_AddRef(sample);
  SetEvent(c->ready);
  return S_OK;
}
static HRESULT WINAPI cb_flush(IMFSourceReaderCallback *p, DWORD stream) {
  (void)p;
  (void)stream;
  return S_OK;
}
static HRESULT WINAPI cb_event(IMFSourceReaderCallback *p, DWORD stream,
                               IMFMediaEvent *e) {
  (void)p;
  (void)stream;
  (void)e;
  return S_OK;
}
static const IMFSourceReaderCallbackVtbl cb_vtable = {
    cb_qi, cb_add, cb_release, cb_read, cb_flush, cb_event};
void mainCRTStartup(void) {
  char mode[32] = {0};
  GetEnvironmentVariableA("PIKA_CAMERA_BACKEND", mode, sizeof(mode));
  ASSERT(!strcmp(mode, "v4l2"));
  CHECK(CoInitializeEx(NULL, COINIT_MULTITHREADED));
  CHECK(MFStartup(MF_VERSION, MFSTARTUP_LITE));
  HMODULE dll = LoadLibraryW(L"mf.dll");
  ASSERT(dll);
  HRESULT(WINAPI *enumerate)(IMFAttributes *, IMFActivate ***, UINT32 *) =
      (void *)GetProcAddress(dll, "MFEnumDeviceSources");
  ASSERT(enumerate);
  IMFAttributes *attrs = NULL;
  CHECK(MFCreateAttributes(&attrs, 2));
  CHECK(IMFAttributes_SetGUID(attrs, &MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE,
                              &MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_GUID));
  IMFActivate **devices = NULL;
  UINT32 count = 0;
  CHECK(enumerate(attrs, &devices, &count));
  ASSERT(count == 1);
  IMFMediaSource *source = NULL;
  CHECK(IMFActivate_ActivateObject(devices[0], &IID_IMFMediaSource, (void **)&source));
  callback cb = {0};
  cb.iface.lpVtbl = &cb_vtable;
  cb.refs = 1;
  cb.ready = CreateEventW(NULL, TRUE, FALSE, NULL);
  ASSERT(cb.ready);
  IMFAttributes *ra = NULL;
  CHECK(MFCreateAttributes(&ra, 2));
  CHECK(IMFAttributes_SetUnknown(ra, &MF_SOURCE_READER_ASYNC_CALLBACK, (IUnknown *)&cb.iface));
  CHECK(IMFAttributes_SetUINT32(ra, &MF_SOURCE_READER_DISCONNECT_MEDIASOURCE_ON_SHUTDOWN, FALSE));
  IMFSourceReader *reader = NULL;
  CHECK(MFCreateSourceReaderFromMediaSource(source, ra, &reader));
  IMFAttributes_Release(ra);
  int result = 0;
  unsigned captured = 0;
  for (unsigned n = 0; n < 33; n++) {
    ResetEvent(cb.ready);
    CHECK(IMFSourceReader_ReadSample(reader, 0, 0, NULL, NULL, NULL, NULL));
    if (WaitForSingleObject(cb.ready, 8000) != WAIT_OBJECT_0) {
      fprintf(stderr, "FAILED: no Media Foundation callback within 8 seconds\n");
      ExitProcess(2);
    }
    fprintf(stderr, "ReadSample: hr=0x%08lx stream=%lu flags=0x%lx timestamp=%lld sample=%s\n",
            cb.status, cb.stream, cb.flags, cb.timestamp, cb.sample ? "present" : "absent");
    if (FAILED(cb.status) || !cb.sample || cb.flags & (MF_SOURCE_READERF_ERROR | MF_SOURCE_READERF_ENDOFSTREAM)) {
      fprintf(stderr, "FAILED: no image delivered; inspect helper.log for the native capture error\n");
      if (cb.sample) { IMFSample_Release(cb.sample); cb.sample = NULL; }
      result = 2;
      break;
    }
    if (n < 30) {
      IMFSample_Release(cb.sample);
      cb.sample = NULL;
      continue;
    }
    IMFMediaBuffer *buf = NULL;
    CHECK(IMFSample_ConvertToContiguousBuffer(cb.sample, &buf));
    BYTE *data = NULL;
    DWORD len = 0;
    CHECK(IMFMediaBuffer_Lock(buf, &data, NULL, &len));
    ASSERT(len == 1280 * 960);
    unsigned min = 255, max = 0;
    ULONGLONG sum = 0;
    BOOL synthetic = TRUE;
    for (DWORD i = 0; i < len; i++) {
      if (data[i] < min) min = data[i];
      if (data[i] > max) max = data[i];
      sum += data[i];
      if (data[i] != (BYTE)((i + cb.timestamp / 166666) % 251)) synthetic = FALSE;
    }
    ASSERT(!synthetic);
    char filename[64];
    snprintf(filename, sizeof(filename), "frame-%02u.pgm", n - 29);
    FILE *f = fopen(filename, "wb");
    ASSERT(f);
    ASSERT(fprintf(f, "P5\n1280 960\n255\n") > 0);
    ASSERT(fwrite(data, 1, len, f) == len);
    ASSERT(!fclose(f));
    fprintf(stderr, "SAVED %s: bytes=%lu min=%u max=%u mean=%.3f (bridge-generated timestamp)\n",
            filename, len, min, max, (double)sum / len);
    CHECK(IMFMediaBuffer_Unlock(buf));
    IMFMediaBuffer_Release(buf);
    IMFSample_Release(cb.sample);
    cb.sample = NULL;
    captured++;
  }
  IMFSourceReader_Flush(reader, MF_SOURCE_READER_ALL_STREAMS);
  IMFSourceReader_Release(reader);
  IMFMediaSource_Shutdown(source);
  IMFMediaSource_Release(source);
  IMFActivate_ShutdownObject(devices[0]);
  IMFActivate_Release(devices[0]);
  CoTaskMemFree(devices);
  IMFAttributes_Release(attrs);
  ASSERT(cb.refs == 1);
  CloseHandle(cb.ready);
  MFShutdown();
  CoUninitialize();
  fprintf(stderr, "%s: %u physical frames delivered to Windows MF; full scanner integration NOT TESTED\n",
          result ? "FAILED" : "PASSED", captured);
  ExitProcess(result);
}
