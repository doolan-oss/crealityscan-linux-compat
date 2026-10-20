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
#include "control-interfaces.h"
void mainCRTStartup(void) {
 CHECK(CoInitializeEx(NULL,COINIT_MULTITHREADED)); CHECK(MFStartup(MF_VERSION,MFSTARTUP_LITE));
 HMODULE dll=LoadLibraryW(L"mf.dll");ASSERT(dll);
 HRESULT(WINAPI *enumerate)(IMFAttributes*,IMFActivate***,UINT32*)=(void*)GetProcAddress(dll,"MFEnumDeviceSources");ASSERT(enumerate);
 IMFAttributes *attrs=NULL;CHECK(MFCreateAttributes(&attrs,2));
 CHECK(IMFAttributes_SetGUID(attrs,&MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE,&MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_GUID));
 IMFActivate **devices=NULL;UINT32 count=0;CHECK(enumerate(attrs,&devices,&count));ASSERT(count==2);
 for(UINT32 i=0;i<count;i++) {
  IMFMediaSource *source=NULL;CHECK(IMFActivate_ActivateObject(devices[i],&IID_IMFMediaSource,(void**)&source));
  BridgeTopology *topo=NULL;CHECK(IMFMediaSource_QueryInterface(source,&bridge_iid_topology,(void**)&topo));
  DWORD n=0;GUID type;CHECK(topo->lpVtbl->NumNodes(topo,&n));ASSERT(n==1);
  CHECK(topo->lpVtbl->NodeType(topo,0,&type));ASSERT(IsEqualGUID(&type,&bridge_node_type));
  BridgeKs *ks=NULL;CHECK(topo->lpVtbl->CreateNode(topo,0,&bridge_iid_ks,(void**)&ks));
  for(ULONG selector=1;selector<=3;selector++) {
   BridgeNode node={.Property={bridge_xu_guid,selector,0x10000001},.NodeId=0};ULONG len=0;
   HRESULT hr=ks->lpVtbl->Property(ks,&node.Property,sizeof(node),NULL,0,&len);
   ASSERT(hr==HRESULT_FROM_WIN32(ERROR_MORE_DATA));ASSERT(len>0&&len<=1024);
   fprintf(stderr,"PASS endpoint=%u XU selector=%lu native length=%lu\n",i,selector,len);
  }
  IAMVideoProcAmp *proc=NULL;CHECK(IMFMediaSource_QueryInterface(source,&IID_IAMVideoProcAmp,(void**)&proc));
  LONG min,max,step,def,flags,value;
  CHECK(IAMVideoProcAmp_GetRange(proc,VideoProcAmp_Gain,&min,&max,&step,&def,&flags));
  CHECK(IAMVideoProcAmp_Get(proc,VideoProcAmp_Gain,&value,&flags));
  fprintf(stderr,"PASS endpoint=%u real gain range=%ld..%ld current=%ld flags=%ld\n",i,min,max,value,flags);
  CHECK(IAMVideoProcAmp_Set(proc,VideoProcAmp_Gain,value,2));
  LONG after;CHECK(IAMVideoProcAmp_Get(proc,VideoProcAmp_Gain,&after,&flags));ASSERT(after==value);
  IAMCameraControl *cam=NULL;CHECK(IMFMediaSource_QueryInterface(source,&IID_IAMCameraControl,(void**)&cam));
  CHECK(IAMCameraControl_Get(cam,CameraControl_Exposure,&value,&flags));
  fprintf(stderr,"PASS endpoint=%u exposure(log2 seconds)=%ld flags=%ld\n",i,value,flags);
  IAMCameraControl_Release(cam);IAMVideoProcAmp_Release(proc);ks->lpVtbl->Release(ks);topo->lpVtbl->Release(topo);
  IMFMediaSource_Shutdown(source);IMFMediaSource_Release(source);IMFActivate_ShutdownObject(devices[i]);IMFActivate_Release(devices[i]);
 }
 CoTaskMemFree(devices);IMFAttributes_Release(attrs);MFShutdown();CoUninitialize();
 fprintf(stderr,"PASSED: both physical camera topology, XU length queries and standard control round trips\n");ExitProcess(0);
}
