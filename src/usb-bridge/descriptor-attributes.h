/* Generated typed delegation to Wine IMFAttributes. */
static HRESULT WINAPI sdattr_GetItem(IMFStreamDescriptor *This, REFGUID guidKey,
                                   PROPVARIANT *pValue) {
  return IMFAttributes_GetItem(from_pinned_descriptor(This)->attrs, guidKey, pValue);
}
static HRESULT WINAPI sdattr_GetItemType(IMFStreamDescriptor *This, REFGUID guidKey,
                                       MF_ATTRIBUTE_TYPE *pType) {
  return IMFAttributes_GetItemType(from_pinned_descriptor(This)->attrs, guidKey,
                                   pType);
}
static HRESULT WINAPI sdattr_CompareItem(IMFStreamDescriptor *This, REFGUID guidKey,
                                       REFPROPVARIANT Value, BOOL *pbResult) {
  return IMFAttributes_CompareItem(from_pinned_descriptor(This)->attrs, guidKey, Value,
                                   pbResult);
}
static HRESULT WINAPI sdattr_Compare(IMFStreamDescriptor *This, IMFAttributes *pTheirs,
                                   MF_ATTRIBUTES_MATCH_TYPE MatchType,
                                   BOOL *pbResult) {
  return IMFAttributes_Compare(from_pinned_descriptor(This)->attrs, pTheirs, MatchType,
                               pbResult);
}
static HRESULT WINAPI sdattr_GetUINT32(IMFStreamDescriptor *This, REFGUID guidKey,
                                     UINT32 *punValue) {
  return IMFAttributes_GetUINT32(from_pinned_descriptor(This)->attrs, guidKey,
                                 punValue);
}
static HRESULT WINAPI sdattr_GetUINT64(IMFStreamDescriptor *This, REFGUID guidKey,
                                     UINT64 *punValue) {
  return IMFAttributes_GetUINT64(from_pinned_descriptor(This)->attrs, guidKey,
                                 punValue);
}
static HRESULT WINAPI sdattr_GetDouble(IMFStreamDescriptor *This, REFGUID guidKey,
                                     double *pfValue) {
  return IMFAttributes_GetDouble(from_pinned_descriptor(This)->attrs, guidKey,
                                 pfValue);
}
static HRESULT WINAPI sdattr_GetGUID(IMFStreamDescriptor *This, REFGUID guidKey,
                                   GUID *pguidValue) {
  return IMFAttributes_GetGUID(from_pinned_descriptor(This)->attrs, guidKey,
                               pguidValue);
}
static HRESULT WINAPI sdattr_GetStringLength(IMFStreamDescriptor *This, REFGUID guidKey,
                                           UINT32 *pcchLength) {
  return IMFAttributes_GetStringLength(from_pinned_descriptor(This)->attrs, guidKey,
                                       pcchLength);
}
static HRESULT WINAPI sdattr_GetString(IMFStreamDescriptor *This, REFGUID guidKey,
                                     LPWSTR pwszValue, UINT32 cchBufSize,
                                     UINT32 *pcchLength) {
  return IMFAttributes_GetString(from_pinned_descriptor(This)->attrs, guidKey,
                                 pwszValue, cchBufSize, pcchLength);
}
static HRESULT WINAPI sdattr_GetAllocatedString(IMFStreamDescriptor *This,
                                              REFGUID guidKey,
                                              LPWSTR *ppwszValue,
                                              UINT32 *pcchLength) {
  return IMFAttributes_GetAllocatedString(from_pinned_descriptor(This)->attrs, guidKey,
                                          ppwszValue, pcchLength);
}
static HRESULT WINAPI sdattr_GetBlobSize(IMFStreamDescriptor *This, REFGUID guidKey,
                                       UINT32 *pcbBlobSize) {
  return IMFAttributes_GetBlobSize(from_pinned_descriptor(This)->attrs, guidKey,
                                   pcbBlobSize);
}
static HRESULT WINAPI sdattr_GetBlob(IMFStreamDescriptor *This, REFGUID guidKey,
                                   UINT8 *pBuf, UINT32 cbBufSize,
                                   UINT32 *pcbBlobSize) {
  return IMFAttributes_GetBlob(from_pinned_descriptor(This)->attrs, guidKey, pBuf,
                               cbBufSize, pcbBlobSize);
}
static HRESULT WINAPI sdattr_GetAllocatedBlob(IMFStreamDescriptor *This, REFGUID guidKey,
                                            UINT8 **ppBuf, UINT32 *pcbSize) {
  return IMFAttributes_GetAllocatedBlob(from_pinned_descriptor(This)->attrs, guidKey,
                                        ppBuf, pcbSize);
}
static HRESULT WINAPI sdattr_GetUnknown(IMFStreamDescriptor *This, REFGUID guidKey,
                                      REFIID riid, LPVOID *ppv) {
  return IMFAttributes_GetUnknown(from_pinned_descriptor(This)->attrs, guidKey, riid,
                                  ppv);
}
static HRESULT WINAPI sdattr_SetItem(IMFStreamDescriptor *This, REFGUID guidKey,
                                   REFPROPVARIANT Value) {
  return IMFAttributes_SetItem(from_pinned_descriptor(This)->attrs, guidKey, Value);
}
static HRESULT WINAPI sdattr_DeleteItem(IMFStreamDescriptor *This, REFGUID guidKey) {
  return IMFAttributes_DeleteItem(from_pinned_descriptor(This)->attrs, guidKey);
}
static HRESULT WINAPI sdattr_DeleteAllItems(IMFStreamDescriptor *This) {
  return IMFAttributes_DeleteAllItems(from_pinned_descriptor(This)->attrs);
}
static HRESULT WINAPI sdattr_SetUINT32(IMFStreamDescriptor *This, REFGUID guidKey,
                                     UINT32 unValue) {
  return IMFAttributes_SetUINT32(from_pinned_descriptor(This)->attrs, guidKey,
                                 unValue);
}
static HRESULT WINAPI sdattr_SetUINT64(IMFStreamDescriptor *This, REFGUID guidKey,
                                     UINT64 unValue) {
  return IMFAttributes_SetUINT64(from_pinned_descriptor(This)->attrs, guidKey,
                                 unValue);
}
static HRESULT WINAPI sdattr_SetDouble(IMFStreamDescriptor *This, REFGUID guidKey,
                                     double fValue) {
  return IMFAttributes_SetDouble(from_pinned_descriptor(This)->attrs, guidKey, fValue);
}
static HRESULT WINAPI sdattr_SetGUID(IMFStreamDescriptor *This, REFGUID guidKey,
                                   REFGUID guidValue) {
  return IMFAttributes_SetGUID(from_pinned_descriptor(This)->attrs, guidKey,
                               guidValue);
}
static HRESULT WINAPI sdattr_SetString(IMFStreamDescriptor *This, REFGUID guidKey,
                                     LPCWSTR wszValue) {
  return IMFAttributes_SetString(from_pinned_descriptor(This)->attrs, guidKey,
                                 wszValue);
}
static HRESULT WINAPI sdattr_SetBlob(IMFStreamDescriptor *This, REFGUID guidKey,
                                   const UINT8 *pBuf, UINT32 cbBufSize) {
  return IMFAttributes_SetBlob(from_pinned_descriptor(This)->attrs, guidKey, pBuf,
                               cbBufSize);
}
static HRESULT WINAPI sdattr_SetUnknown(IMFStreamDescriptor *This, REFGUID guidKey,
                                      IUnknown *pUnknown) {
  return IMFAttributes_SetUnknown(from_pinned_descriptor(This)->attrs, guidKey,
                                  pUnknown);
}
static HRESULT WINAPI sdattr_LockStore(IMFStreamDescriptor *This) {
  return IMFAttributes_LockStore(from_pinned_descriptor(This)->attrs);
}
static HRESULT WINAPI sdattr_UnlockStore(IMFStreamDescriptor *This) {
  return IMFAttributes_UnlockStore(from_pinned_descriptor(This)->attrs);
}
static HRESULT WINAPI sdattr_GetCount(IMFStreamDescriptor *This, UINT32 *pcItems) {
  return IMFAttributes_GetCount(from_pinned_descriptor(This)->attrs, pcItems);
}
static HRESULT WINAPI sdattr_GetItemByIndex(IMFStreamDescriptor *This, UINT32 unIndex,
                                          GUID *pguidKey, PROPVARIANT *pValue) {
  return IMFAttributes_GetItemByIndex(from_pinned_descriptor(This)->attrs, unIndex,
                                      pguidKey, pValue);
}
static HRESULT WINAPI sdattr_CopyAllItems(IMFStreamDescriptor *This,
                                        IMFAttributes *pDest) {
  return IMFAttributes_CopyAllItems(from_pinned_descriptor(This)->attrs, pDest);
}
#define SD_ATTRIBUTE_VTABLE_ENTRIES                                               \
  sdattr_GetItem, sdattr_GetItemType, sdattr_CompareItem, sdattr_Compare,              \
      sdattr_GetUINT32, sdattr_GetUINT64, sdattr_GetDouble, sdattr_GetGUID,            \
      sdattr_GetStringLength, sdattr_GetString, sdattr_GetAllocatedString,           \
      sdattr_GetBlobSize, sdattr_GetBlob, sdattr_GetAllocatedBlob, sdattr_GetUnknown,  \
      sdattr_SetItem, sdattr_DeleteItem, sdattr_DeleteAllItems, sdattr_SetUINT32,      \
      sdattr_SetUINT64, sdattr_SetDouble, sdattr_SetGUID, sdattr_SetString,            \
      sdattr_SetBlob, sdattr_SetUnknown, sdattr_LockStore, sdattr_UnlockStore,         \
      sdattr_GetCount, sdattr_GetItemByIndex, sdattr_CopyAllItems,
