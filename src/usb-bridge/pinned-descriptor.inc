/* SourceReaderEx native selection must restrict the converter's input search;
 * otherwise Wine picks the first advertised type, including the wrong rate. */
typedef struct pinned_handler { IMFMediaTypeHandler iface; LONG refs; IMFMediaTypeHandler *real; IMFMediaType *pin; CRITICAL_SECTION lock; } pinned_handler;
typedef struct pinned_descriptor { IMFStreamDescriptor iface; LONG refs; IMFAttributes *attrs; pinned_handler *handler; } pinned_descriptor;
static pinned_handler *ph(IMFMediaTypeHandler*p){return CONTAINING_RECORD(p,pinned_handler,iface);}
static pinned_descriptor *from_pinned_descriptor(IMFStreamDescriptor*p){return CONTAINING_RECORD(p,pinned_descriptor,iface);}
static ULONG WINAPI ph_add(IMFMediaTypeHandler*p){return InterlockedIncrement(&ph(p)->refs);}
static ULONG WINAPI ph_release(IMFMediaTypeHandler*p){pinned_handler*h=ph(p);ULONG n=InterlockedDecrement(&h->refs);if(!n){if(h->pin)IMFMediaType_Release(h->pin);IMFMediaTypeHandler_Release(h->real);DeleteCriticalSection(&h->lock);free(h);}return n;}
static HRESULT WINAPI ph_qi(IMFMediaTypeHandler*p,REFIID iid,void**o){if(!o)return E_POINTER;*o=NULL;if(IsEqualIID(iid,&IID_IUnknown)||IsEqualIID(iid,&IID_IMFMediaTypeHandler)){*o=p;ph_add(p);return S_OK;}return E_NOINTERFACE;}
static BOOL ph_equal(IMFMediaType*a,IMFMediaType*b){DWORD flags=0;IMFMediaType_IsEqual(a,b,&flags);return (flags&7)==7;}
static HRESULT WINAPI ph_supported(IMFMediaTypeHandler*p,IMFMediaType*t,IMFMediaType**closest){
 if(closest)*closest=NULL;if(!t)return E_POINTER;pinned_handler*h=ph(p);EnterCriticalSection(&h->lock);
 HRESULT hr=h->pin?(ph_equal(h->pin,t)?S_OK:MF_E_INVALIDMEDIATYPE):IMFMediaTypeHandler_IsMediaTypeSupported(h->real,t,closest);
 LeaveCriticalSection(&h->lock);return hr;
}
static HRESULT WINAPI ph_count(IMFMediaTypeHandler*p,DWORD*n){if(!n)return E_POINTER;pinned_handler*h=ph(p);EnterCriticalSection(&h->lock);HRESULT hr=S_OK;if(h->pin)*n=1;else hr=IMFMediaTypeHandler_GetMediaTypeCount(h->real,n);LeaveCriticalSection(&h->lock);return hr;}
static HRESULT WINAPI ph_at(IMFMediaTypeHandler*p,DWORD index,IMFMediaType**out){
 if(!out)return E_POINTER;*out=NULL;pinned_handler*h=ph(p);EnterCriticalSection(&h->lock);HRESULT hr;
 if(h->pin){hr=index?MF_E_NO_MORE_TYPES:S_OK;if(!index){*out=h->pin;IMFMediaType_AddRef(*out);}}
 else hr=IMFMediaTypeHandler_GetMediaTypeByIndex(h->real,index,out);
 LeaveCriticalSection(&h->lock);return hr;
}
static HRESULT WINAPI ph_set(IMFMediaTypeHandler*p,IMFMediaType*t){pinned_handler*h=ph(p);EnterCriticalSection(&h->lock);HRESULT hr=ph_supported(p,t,NULL);if(SUCCEEDED(hr))hr=IMFMediaTypeHandler_SetCurrentMediaType(h->real,t);LeaveCriticalSection(&h->lock);return hr;}
static HRESULT WINAPI ph_current(IMFMediaTypeHandler*p,IMFMediaType**t){return IMFMediaTypeHandler_GetCurrentMediaType(ph(p)->real,t);}
static HRESULT WINAPI ph_major(IMFMediaTypeHandler*p,GUID*g){return IMFMediaTypeHandler_GetMajorType(ph(p)->real,g);}
static const IMFMediaTypeHandlerVtbl ph_vtable={ph_qi,ph_add,ph_release,ph_supported,ph_count,ph_at,ph_set,ph_current,ph_major};
static ULONG WINAPI pd_add(IMFStreamDescriptor*p){return InterlockedIncrement(&from_pinned_descriptor(p)->refs);}
static ULONG WINAPI pd_release(IMFStreamDescriptor*p){pinned_descriptor*d=from_pinned_descriptor(p);ULONG n=InterlockedDecrement(&d->refs);if(!n){IMFAttributes_Release(d->attrs);ph_release(&d->handler->iface);free(d);}return n;}
static HRESULT WINAPI pd_qi(IMFStreamDescriptor*p,REFIID iid,void**o){if(!o)return E_POINTER;*o=NULL;if(IsEqualIID(iid,&IID_IUnknown)||IsEqualIID(iid,&IID_IMFAttributes)||IsEqualIID(iid,&IID_IMFStreamDescriptor)){*o=p;pd_add(p);return S_OK;}return E_NOINTERFACE;}
#include "descriptor-attributes.h"
static HRESULT WINAPI pd_id(IMFStreamDescriptor*p,DWORD*i){return IMFStreamDescriptor_GetStreamIdentifier((IMFStreamDescriptor*)from_pinned_descriptor(p)->attrs,i);}
static HRESULT WINAPI pd_handler(IMFStreamDescriptor*p,IMFMediaTypeHandler**out){if(!out)return E_POINTER;*out=&from_pinned_descriptor(p)->handler->iface;ph_add(*out);return S_OK;}
static const IMFStreamDescriptorVtbl pd_vtable={pd_qi,pd_add,pd_release,SD_ATTRIBUTE_VTABLE_ENTRIES pd_id,pd_handler};
static HRESULT wrap_descriptor(IMFStreamDescriptor**slot){
 pinned_descriptor*d=calloc(1,sizeof(*d));pinned_handler*h=calloc(1,sizeof(*h));
 if(!d||!h){free(d);free(h);return E_OUTOFMEMORY;}
 HRESULT hr=IMFStreamDescriptor_GetMediaTypeHandler(*slot,&h->real);if(FAILED(hr)){free(d);free(h);return hr;}
 h->iface.lpVtbl=&ph_vtable;h->refs=1;InitializeCriticalSection(&h->lock);
 d->iface.lpVtbl=&pd_vtable;d->refs=1;d->attrs=(IMFAttributes*)*slot;d->handler=h;*slot=&d->iface;return S_OK;
}
static HRESULT pin_descriptor(IMFStreamDescriptor*sd,IMFMediaType*t){
 if(sd->lpVtbl!=&pd_vtable)return E_NOTIMPL;
 pinned_handler*h=from_pinned_descriptor(sd)->handler;EnterCriticalSection(&h->lock);
 HRESULT hr=t?IMFMediaTypeHandler_IsMediaTypeSupported(h->real,t,NULL):S_OK;
 if(SUCCEEDED(hr)&&t)hr=IMFMediaTypeHandler_SetCurrentMediaType(h->real,t);
 if(SUCCEEDED(hr)){if(t)IMFMediaType_AddRef(t);if(h->pin)IMFMediaType_Release(h->pin);h->pin=t;}
 LeaveCriticalSection(&h->lock);return hr;
}
