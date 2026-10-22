/* Confined to this SDK's import and our source. Wine implements SourceReaderEx
 * but leaves SetNativeMediaType as a stub. Select a validated native type using
 * the source descriptor and the normal reader type-selection path instead. */
#include <mfreadwrite.h>
typedef struct bridge_reader { IMFSourceReaderEx iface; LONG refs; IMFSourceReader *real; IMFMediaSource *source; } bridge_reader;
static bridge_reader *reader_from(IMFSourceReaderEx *p){return CONTAINING_RECORD(p,bridge_reader,iface);}
static ULONG WINAPI reader_add(IMFSourceReaderEx *p){return InterlockedIncrement(&reader_from(p)->refs);}
static ULONG WINAPI reader_release(IMFSourceReaderEx *p){bridge_reader*r=reader_from(p);ULONG n=InterlockedDecrement(&r->refs);if(!n){IMFSourceReader_Release(r->real);IMFMediaSource_Release(r->source);free(r);}return n;}
static HRESULT WINAPI reader_qi(IMFSourceReaderEx*p,REFIID iid,void**out){
 if(!out)return E_POINTER;*out=NULL;
 if(IsEqualIID(iid,&IID_IUnknown)||IsEqualIID(iid,&IID_IMFSourceReader)||IsEqualIID(iid,&IID_IMFSourceReaderEx)){*out=p;reader_add(p);return S_OK;}
 return E_NOINTERFACE;
}
#define FORWARD(name,method,args,call) static HRESULT WINAPI name args {return IMFSourceReader_##method call;}
FORWARD(reader_get_selection,GetStreamSelection,(IMFSourceReaderEx*p,DWORD i,BOOL*s),(reader_from(p)->real,i,s))
FORWARD(reader_set_selection,SetStreamSelection,(IMFSourceReaderEx*p,DWORD i,BOOL s),(reader_from(p)->real,i,s))
static HRESULT WINAPI reader_native(IMFSourceReaderEx*p,DWORD i,DWORD t,IMFMediaType**o){
 bridge_reader*r=reader_from(p);camera*c=from_source(r->source);
 if(t==0&&!c->running)pin_descriptor(c->sd,NULL);
 return IMFSourceReader_GetNativeMediaType(r->real,i,t,o);
}
FORWARD(reader_current,GetCurrentMediaType,(IMFSourceReaderEx*p,DWORD i,IMFMediaType**o),(reader_from(p)->real,i,o))
/* Records which formats the SDK asks for; useful when adding a scanner model. */
static void log_type(const char *what,camera *c,IMFMediaType *t,HRESULT hr){
 GUID subtype={0};UINT64 size=0,rate=0;
 if(t){IMFMediaType_GetGUID(t,&MF_MT_SUBTYPE,&subtype);IMFMediaType_GetUINT64(t,&MF_MT_FRAME_SIZE,&size);IMFMediaType_GetUINT64(t,&MF_MT_FRAME_RATE,&rate);}
 LOG("reader %s endpoint=%u subtype=%08lx size=%ux%u rate=%u/%u result=%lx",what,c->endpoint,subtype.Data1,
     (unsigned)(size>>32),(unsigned)size,(unsigned)(rate>>32),(unsigned)rate,hr);
}
static HRESULT WINAPI reader_set_current(IMFSourceReaderEx*p,DWORD i,DWORD*reserved,IMFMediaType*t){
 bridge_reader*r=reader_from(p);camera*c=from_source(r->source);GUID subtype;UINT64 size=0;
 /* Decode RGB in the native helper so the real UVC metadata remains attached.
  * Wine's RGB transform discards that metadata, breaking sensor synchronization. */
 if(t&&c->endpoint&&SUCCEEDED(IMFMediaType_GetGUID(t,&MF_MT_SUBTYPE,&subtype))&&IsEqualGUID(&subtype,&MFVideoFormat_RGB24)){
  if(FAILED(IMFMediaType_GetUINT64(t,&MF_MT_FRAME_SIZE,&size))||!size)size=((UINT64)WIDTH<<32)|HEIGHT;
  DWORD width=size>>32,height=(DWORD)size;
  IMFMediaType*rgb=NULL;HRESULT hr=MFCreateMediaType(&rgb);
  if(SUCCEEDED(hr))hr=IMFMediaType_CopyAllItems(t,(IMFAttributes*)rgb);
  if(SUCCEEDED(hr))hr=IMFMediaType_SetUINT32(rgb,&MF_MT_DEFAULT_STRIDE,width*3);
  if(SUCCEEDED(hr))hr=IMFMediaType_SetUINT32(rgb,&MF_MT_SAMPLE_SIZE,width*height*3);
  if(SUCCEEDED(hr))hr=pin_descriptor(c->sd,rgb);
  if(SUCCEEDED(hr))hr=IMFSourceReader_SetCurrentMediaType(r->real,i,reserved,rgb);
  log_type("SetCurrentMediaType RGB24 decoded natively",c,t,hr);
  if(rgb)IMFMediaType_Release(rgb);return hr;
 }
 HRESULT hr=IMFSourceReader_SetCurrentMediaType(r->real,i,reserved,t);
 log_type("SetCurrentMediaType",c,t,hr);return hr;
}
FORWARD(reader_position,SetCurrentPosition,(IMFSourceReaderEx*p,REFGUID f,REFPROPVARIANT v),(reader_from(p)->real,f,v))
FORWARD(reader_read,ReadSample,(IMFSourceReaderEx*p,DWORD i,DWORD f,DWORD*a,DWORD*s,LONGLONG*t,IMFSample**sample),(reader_from(p)->real,i,f,a,s,t,sample))
FORWARD(reader_flush,Flush,(IMFSourceReaderEx*p,DWORD i),(reader_from(p)->real,i))
FORWARD(reader_service,GetServiceForStream,(IMFSourceReaderEx*p,DWORD i,REFGUID s,REFIID iid,void**o),(reader_from(p)->real,i,s,iid,o))
FORWARD(reader_attribute,GetPresentationAttribute,(IMFSourceReaderEx*p,DWORD i,REFGUID g,PROPVARIANT*v),(reader_from(p)->real,i,g,v))
#undef FORWARD
static HRESULT WINAPI reader_set_native(IMFSourceReaderEx*p,DWORD index,IMFMediaType*t,DWORD*flags){
 if(!t||!flags)return E_POINTER;*flags=0;
 if(index!=0&&index!=MF_SOURCE_READER_FIRST_VIDEO_STREAM)return MF_E_INVALIDSTREAMNUMBER;
 bridge_reader*r=reader_from(p);camera*c=from_source(r->source);
 HRESULT hr=pin_descriptor(c->sd,t);
 if(SUCCEEDED(hr))hr=IMFSourceReader_SetCurrentMediaType(r->real,index,NULL,t);
 log_type("SetNativeMediaType",c,t,hr);return hr;
}
static HRESULT WINAPI reader_add_transform(IMFSourceReaderEx*p,DWORD i,IUnknown*t){return E_NOTIMPL;}
static HRESULT WINAPI reader_remove_transform(IMFSourceReaderEx*p,DWORD i){return E_NOTIMPL;}
static HRESULT WINAPI reader_get_transform(IMFSourceReaderEx*p,DWORD i,DWORD t,GUID*g,IMFTransform**o){if(o)*o=NULL;return E_NOTIMPL;}
static const IMFSourceReaderExVtbl reader_vtable={reader_qi,reader_add,reader_release,reader_get_selection,reader_set_selection,reader_native,reader_current,reader_set_current,reader_position,reader_read,reader_flush,reader_service,reader_attribute,reader_set_native,reader_add_transform,reader_remove_transform,reader_get_transform};
static HRESULT WINAPI bridge_create_reader(IMFMediaSource*source,IMFAttributes*attrs,IMFSourceReader**out){
 if(!out)return E_POINTER;*out=NULL;
 HMODULE mod=GetModuleHandleW(L"mfreadwrite.dll");if(!mod)return E_FAIL;
 HRESULT (WINAPI *create)(IMFMediaSource*,IMFAttributes*,IMFSourceReader**)=(void*)GetProcAddress(mod,"MFCreateSourceReaderFromMediaSource");if(!create)return E_FAIL;
 if(!sdk_mode()||!source||source->lpVtbl!=&source_vtable)return create(source,attrs,out);
 bridge_reader*r=calloc(1,sizeof(*r));if(!r)return E_OUTOFMEMORY;
 HRESULT hr=create(source,attrs,&r->real);if(FAILED(hr)){free(r);return hr;}
 r->refs=1;r->iface.lpVtbl=&reader_vtable;r->source=source;IMFMediaSource_AddRef(source);*out=(IMFSourceReader*)&r->iface;return S_OK;
}
