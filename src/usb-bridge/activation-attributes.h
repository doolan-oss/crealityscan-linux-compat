/* Generated typed delegation to Wine IMFAttributes. */
static HRESULT WINAPI attr_GetItem(IMFActivate *This, REFGUID guidKey,
                                   PROPVARIANT *pValue) {
  return IMFAttributes_GetItem(from_activation(This)->attrs, guidKey, pValue);
}
static HRESULT WINAPI attr_GetItemType(IMFActivate *This, REFGUID guidKey,
                                       MF_ATTRIBUTE_TYPE *pType) {
  return IMFAttributes_GetItemType(from_activation(This)->attrs, guidKey,
                                   pType);
}
static HRESULT WINAPI attr_CompareItem(IMFActivate *This, REFGUID guidKey,
                                       REFPROPVARIANT Value, BOOL *pbResult) {
  return IMFAttributes_CompareItem(from_activation(This)->attrs, guidKey, Value,
                                   pbResult);
}
static HRESULT WINAPI attr_Compare(IMFActivate *This, IMFAttributes *pTheirs,
                                   MF_ATTRIBUTES_MATCH_TYPE MatchType,
                                   BOOL *pbResult) {
  return IMFAttributes_Compare(from_activation(This)->attrs, pTheirs, MatchType,
                               pbResult);
}
static HRESULT WINAPI attr_GetUINT32(IMFActivate *This, REFGUID guidKey,
                                     UINT32 *punValue) {
  return IMFAttributes_GetUINT32(from_activation(This)->attrs, guidKey,
                                 punValue);
}
static HRESULT WINAPI attr_GetUINT64(IMFActivate *This, REFGUID guidKey,
                                     UINT64 *punValue) {
  return IMFAttributes_GetUINT64(from_activation(This)->attrs, guidKey,
                                 punValue);
}
static HRESULT WINAPI attr_GetDouble(IMFActivate *This, REFGUID guidKey,
                                     double *pfValue) {
  return IMFAttributes_GetDouble(from_activation(This)->attrs, guidKey,
                                 pfValue);
}
static HRESULT WINAPI attr_GetGUID(IMFActivate *This, REFGUID guidKey,
                                   GUID *pguidValue) {
  return IMFAttributes_GetGUID(from_activation(This)->attrs, guidKey,
                               pguidValue);
}
static HRESULT WINAPI attr_GetStringLength(IMFActivate *This, REFGUID guidKey,
                                           UINT32 *pcchLength) {
  return IMFAttributes_GetStringLength(from_activation(This)->attrs, guidKey,
                                       pcchLength);
}
static HRESULT WINAPI attr_GetString(IMFActivate *This, REFGUID guidKey,
                                     LPWSTR pwszValue, UINT32 cchBufSize,
                                     UINT32 *pcchLength) {
  return IMFAttributes_GetString(from_activation(This)->attrs, guidKey,
                                 pwszValue, cchBufSize, pcchLength);
}
static HRESULT WINAPI attr_GetAllocatedString(IMFActivate *This,
                                              REFGUID guidKey,
                                              LPWSTR *ppwszValue,
                                              UINT32 *pcchLength) {
  return IMFAttributes_GetAllocatedString(from_activation(This)->attrs, guidKey,
                                          ppwszValue, pcchLength);
}
static HRESULT WINAPI attr_GetBlobSize(IMFActivate *This, REFGUID guidKey,
                                       UINT32 *pcbBlobSize) {
  return IMFAttributes_GetBlobSize(from_activation(This)->attrs, guidKey,
                                   pcbBlobSize);
}
static HRESULT WINAPI attr_GetBlob(IMFActivate *This, REFGUID guidKey,
                                   UINT8 *pBuf, UINT32 cbBufSize,
                                   UINT32 *pcbBlobSize) {
  return IMFAttributes_GetBlob(from_activation(This)->attrs, guidKey, pBuf,
                               cbBufSize, pcbBlobSize);
}
static HRESULT WINAPI attr_GetAllocatedBlob(IMFActivate *This, REFGUID guidKey,
                                            UINT8 **ppBuf, UINT32 *pcbSize) {
  return IMFAttributes_GetAllocatedBlob(from_activation(This)->attrs, guidKey,
                                        ppBuf, pcbSize);
}
static HRESULT WINAPI attr_GetUnknown(IMFActivate *This, REFGUID guidKey,
                                      REFIID riid, LPVOID *ppv) {
  return IMFAttributes_GetUnknown(from_activation(This)->attrs, guidKey, riid,
                                  ppv);
}
static HRESULT WINAPI attr_SetItem(IMFActivate *This, REFGUID guidKey,
                                   REFPROPVARIANT Value) {
  return IMFAttributes_SetItem(from_activation(This)->attrs, guidKey, Value);
}
static HRESULT WINAPI attr_DeleteItem(IMFActivate *This, REFGUID guidKey) {
  return IMFAttributes_DeleteItem(from_activation(This)->attrs, guidKey);
}
static HRESULT WINAPI attr_DeleteAllItems(IMFActivate *This) {
  return IMFAttributes_DeleteAllItems(from_activation(This)->attrs);
}
static HRESULT WINAPI attr_SetUINT32(IMFActivate *This, REFGUID guidKey,
                                     UINT32 unValue) {
  return IMFAttributes_SetUINT32(from_activation(This)->attrs, guidKey,
                                 unValue);
}
static HRESULT WINAPI attr_SetUINT64(IMFActivate *This, REFGUID guidKey,
                                     UINT64 unValue) {
  return IMFAttributes_SetUINT64(from_activation(This)->attrs, guidKey,
                                 unValue);
}
static HRESULT WINAPI attr_SetDouble(IMFActivate *This, REFGUID guidKey,
                                     double fValue) {
  return IMFAttributes_SetDouble(from_activation(This)->attrs, guidKey, fValue);
}
static HRESULT WINAPI attr_SetGUID(IMFActivate *This, REFGUID guidKey,
                                   REFGUID guidValue) {
  return IMFAttributes_SetGUID(from_activation(This)->attrs, guidKey,
                               guidValue);
}
static HRESULT WINAPI attr_SetString(IMFActivate *This, REFGUID guidKey,
                                     LPCWSTR wszValue) {
  return IMFAttributes_SetString(from_activation(This)->attrs, guidKey,
                                 wszValue);
}
static HRESULT WINAPI attr_SetBlob(IMFActivate *This, REFGUID guidKey,
                                   const UINT8 *pBuf, UINT32 cbBufSize) {
  return IMFAttributes_SetBlob(from_activation(This)->attrs, guidKey, pBuf,
                               cbBufSize);
}
static HRESULT WINAPI attr_SetUnknown(IMFActivate *This, REFGUID guidKey,
                                      IUnknown *pUnknown) {
  return IMFAttributes_SetUnknown(from_activation(This)->attrs, guidKey,
                                  pUnknown);
}
static HRESULT WINAPI attr_LockStore(IMFActivate *This) {
  return IMFAttributes_LockStore(from_activation(This)->attrs);
}
static HRESULT WINAPI attr_UnlockStore(IMFActivate *This) {
  return IMFAttributes_UnlockStore(from_activation(This)->attrs);
}
static HRESULT WINAPI attr_GetCount(IMFActivate *This, UINT32 *pcItems) {
  return IMFAttributes_GetCount(from_activation(This)->attrs, pcItems);
}
static HRESULT WINAPI attr_GetItemByIndex(IMFActivate *This, UINT32 unIndex,
                                          GUID *pguidKey, PROPVARIANT *pValue) {
  return IMFAttributes_GetItemByIndex(from_activation(This)->attrs, unIndex,
                                      pguidKey, pValue);
}
static HRESULT WINAPI attr_CopyAllItems(IMFActivate *This,
                                        IMFAttributes *pDest) {
  return IMFAttributes_CopyAllItems(from_activation(This)->attrs, pDest);
}
#define ATTRIBUTE_VTABLE_ENTRIES                                               \
  attr_GetItem, attr_GetItemType, attr_CompareItem, attr_Compare,              \
      attr_GetUINT32, attr_GetUINT64, attr_GetDouble, attr_GetGUID,            \
      attr_GetStringLength, attr_GetString, attr_GetAllocatedString,           \
      attr_GetBlobSize, attr_GetBlob, attr_GetAllocatedBlob, attr_GetUnknown,  \
      attr_SetItem, attr_DeleteItem, attr_DeleteAllItems, attr_SetUINT32,      \
      attr_SetUINT64, attr_SetDouble, attr_SetGUID, attr_SetString,            \
      attr_SetBlob, attr_SetUnknown, attr_LockStore, attr_UnlockStore,         \
      attr_GetCount, attr_GetItemByIndex, attr_CopyAllItems,
