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
  CHECK(CoInitializeEx(NULL, COINIT_MULTITHREADED));
  CHECK(MFStartup(MF_VERSION, MFSTARTUP_LITE));
  WCHAR dllname[32] = L"pikacam.dll";
  GetEnvironmentVariableW(L"PIKA_TEST_DLL", dllname, 32);
  HMODULE dll = LoadLibraryW(dllname);
  ASSERT(dll);
  HRESULT(WINAPI * enumerate)(IMFAttributes *, IMFActivate ***, UINT32 *) =
      (void *)GetProcAddress(dll, "MFEnumDeviceSources");
  HRESULT(WINAPI * create)(IMFAttributes *, IMFMediaSource **) =
      (void *)GetProcAddress(dll, "MFCreateDeviceSource");
  LONG(WINAPI * live)(void) =
      (void *)GetProcAddress(dll, "PikaBridgeLiveSources");
  ASSERT(enumerate && create && live);
  if (!lstrcmpW(dllname, L"mf.dll")) {
    HRESULT(WINAPI * clock_create)(IMFPresentationClock **) =
        (void *)GetProcAddress(dll, "MFCreatePresentationClock");
    IMFPresentationClock *clock = NULL;
    ASSERT(clock_create);
    CHECK(clock_create(&clock));
    ASSERT(clock);
    IMFPresentationClock_Release(clock);
    fprintf(stderr, "PASS unchanged MF export forwarded to local stock DLL\n");
  }
  IMFAttributes *attrs = NULL;
  CHECK(MFCreateAttributes(&attrs, 4));
  CHECK(IMFAttributes_SetGUID(attrs, &MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE,
                              &MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_GUID));
  IMFActivate **devices = NULL;
  UINT32 count = 0;
  CHECK(enumerate(attrs, &devices, &count));
  char mode[32] = {0};
  GetEnvironmentVariableA("PIKA_CAMERA_BACKEND", mode, sizeof(mode));
  if (!strcmp(mode, "disabled")) {
    ASSERT(count == 0);
    fprintf(stderr, "PASS disabled backend enumerates zero devices\n");
    IMFAttributes_Release(attrs);
    MFShutdown();
    CoUninitialize();
    ExitProcess(0);
  }
  ASSERT(count == 1);
  WCHAR name[128], link[128];
  CHECK(IMFActivate_GetString(devices[0], &MF_DEVSOURCE_ATTRIBUTE_FRIENDLY_NAME,
                              name, 128, NULL));
  CHECK(IMFActivate_GetString(
      devices[0], &MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_SYMBOLIC_LINK,
      link, 128, NULL));
  fprintf(stderr, "Camera: %ls; link: %ls\n", name, link);
  ASSERT(!wcsstr(link, L"vid_2bc5"));
  for (unsigned round = 0; round < 4; round++) {
    IMFMediaSource *source = NULL;
    if (round == 1) {
      CHECK(IMFAttributes_SetString(
          attrs, &MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_SYMBOLIC_LINK,
          link));
      CHECK(create(attrs, &source));
    } else
      CHECK(IMFActivate_ActivateObject(devices[0], &IID_IMFMediaSource,
                                       (void **)&source));
    DWORD caps = 0;
    CHECK(IMFMediaSource_GetCharacteristics(source, &caps));
    ASSERT(caps & MFMEDIASOURCE_IS_LIVE);
    IMFPresentationDescriptor *pd = NULL;
    CHECK(IMFMediaSource_CreatePresentationDescriptor(source, &pd));
    ASSERT(pd);
    PROPVARIANT seek = {0};
    seek.vt = VT_I8;
    seek.hVal.QuadPart = 1234;
    ASSERT(IMFMediaSource_Start(source, pd, NULL, &seek) ==
           MF_E_INVALIDREQUEST);
    IMFPresentationDescriptor_Release(pd);
    callback cb = {0};
    IMFAttributes *reader_attrs = NULL;
    BOOL asynchronous = (round == 3);
    if (asynchronous) {
      cb.iface.lpVtbl = &cb_vtable;
      cb.refs = 1;
      cb.ready = CreateEventW(NULL, TRUE, FALSE, NULL);
      ASSERT(cb.ready);
      CHECK(MFCreateAttributes(&reader_attrs, 2));
      CHECK(IMFAttributes_SetUnknown(reader_attrs,
                                     &MF_SOURCE_READER_ASYNC_CALLBACK,
                                     (IUnknown *)&cb.iface));
      CHECK(IMFAttributes_SetUINT32(
          reader_attrs, &MF_SOURCE_READER_DISCONNECT_MEDIASOURCE_ON_SHUTDOWN,
          FALSE));
    }
    IMFSourceReader *reader = NULL;
    CHECK(MFCreateSourceReaderFromMediaSource(source, reader_attrs, &reader));
    if (reader_attrs)
      IMFAttributes_Release(reader_attrs);
    IMFMediaType *type = NULL;
    CHECK(IMFSourceReader_GetNativeMediaType(reader, 0, 0, &type));
    UINT64 size = 0;
    GUID subtype;
    CHECK(IMFMediaType_GetUINT64(type, &MF_MT_FRAME_SIZE, &size));
    CHECK(IMFMediaType_GetGUID(type, &MF_MT_SUBTYPE, &subtype));
    ASSERT(size == ((UINT64)1280 << 32 | 960));
    ASSERT(IsEqualGUID(&subtype, &MFVideoFormat_L8));
    IMFMediaType_Release(type);
    LONGLONG previous = -1;
    for (unsigned n = 0; n < 8; n++) {
      DWORD stream = 999, flags = 0;
      LONGLONG timestamp = -1;
      IMFSample *sample = NULL;
      HRESULT read_hr;
      if (asynchronous) {
        ResetEvent(cb.ready);
        CHECK(IMFSourceReader_ReadSample(reader, 0, 0, NULL, NULL, NULL, NULL));
        ASSERT(WaitForSingleObject(cb.ready, 5000) == WAIT_OBJECT_0);
        read_hr = cb.status;
        stream = cb.stream;
        flags = cb.flags;
        timestamp = cb.timestamp;
        sample = cb.sample;
        cb.sample = NULL;
      } else
        read_hr = IMFSourceReader_ReadSample(reader, 0, 0, &stream, &flags,
                                             &timestamp, &sample);
      if (GetEnvironmentVariableA("PIKA_EXPECT_FAILURE", mode, sizeof(mode))) {
        ASSERT(FAILED(read_hr) || (flags & MF_SOURCE_READERF_ENDOFSTREAM));
        ASSERT(!sample);
        if (sample)
          IMFSample_Release(sample);
        IMFSourceReader_Release(reader);
        IMFMediaSource_Shutdown(source);
        IMFMediaSource_Release(source);
        IMFActivate_ShutdownObject(devices[0]);
        ASSERT(live() == 0);
        IMFActivate_Release(devices[0]);
        CoTaskMemFree(devices);
        IMFAttributes_Release(attrs);
        MFShutdown();
        CoUninitialize();
        fprintf(stderr, "PASS disconnected transport reports failure and shuts "
                        "down cleanly\n");
        ExitProcess(0);
      }
      CHECK(read_hr);
      ASSERT(sample && stream == 0 && !(flags & MF_SOURCE_READERF_ERROR));
      ASSERT(timestamp > previous);
      previous = timestamp;
      IMFMediaBuffer *buf = NULL;
      CHECK(IMFSample_ConvertToContiguousBuffer(sample, &buf));
      BYTE *data = NULL;
      DWORD len = 0;
      CHECK(IMFMediaBuffer_Lock(buf, &data, NULL, &len));
      ASSERT(len == 1280 * 960);
      ULONGLONG sequence = timestamp / 166666;
      for (DWORD i = 0; i < len; i++)
        ASSERT(data[i] == (BYTE)((i + sequence) % 251));
      CHECK(IMFMediaBuffer_Unlock(buf));
      IMFMediaBuffer_Release(buf);
      IMFSample_Release(sample);
    }
    CHECK(IMFSourceReader_Flush(reader, MF_SOURCE_READER_ALL_STREAMS));
    IMFSourceReader_Release(reader);
    HRESULT hr = IMFMediaSource_Shutdown(source);
    ASSERT(hr == S_OK || hr == MF_E_SHUTDOWN);
    ASSERT(IMFMediaSource_GetCharacteristics(source, &caps) == MF_E_SHUTDOWN);
    IMFMediaSource_Release(source);
    CHECK(IMFActivate_ShutdownObject(devices[0]));
    ASSERT(live() == 0);
    if (asynchronous) {
      ASSERT(cb.refs == 1);
      CloseHandle(cb.ready);
      fprintf(stderr, "PASS asynchronous source-reader callback delivery\n");
    }
    fprintf(stderr,
            "PASS round %u: 8 frames, 1280x960 GREY, every byte checked, "
            "monotonic timestamps, shutdown and zero live sources\n",
            round + 1);
  }
  IMFActivate_Release(devices[0]);
  CoTaskMemFree(devices);
  IMFAttributes_Release(attrs);
  MFShutdown();
  CoUninitialize();
  fprintf(stderr, "PASS synthetic Media Foundation source-reader pipeline. "
                  "Physical Pika NOT TESTED.\n");
  ExitProcess(0);
}
