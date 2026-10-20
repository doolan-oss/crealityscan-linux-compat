/* App-local loader shim: all SDK exports forward unchanged to the original.
 * Prepare only Windows device API compatibility before SDK context creation. */
#include <windows.h>
BOOL WINAPI DllMain(HINSTANCE self,DWORD reason,void *reserved){
 if(reason==DLL_PROCESS_ATTACH){
  DisableThreadLibraryCalls(self);
  HMODULE sdk=LoadLibraryW(L"OrbbecSDK-stock.dll");
  HMODULE mf=LoadLibraryW(L"mf.dll");
  void (WINAPI *prepare)(void)=mf?(void*)GetProcAddress(mf,"PikaBridgePrepareSDK"):NULL;
  if(!sdk||!prepare)return FALSE;
  prepare();
 }
 return TRUE;
}
