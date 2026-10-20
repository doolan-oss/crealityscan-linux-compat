/* Process-local projection of the verified Linux USB device for this SDK only.
 * No registry/PnP driver installation, no SDK file patch. Unrelated API calls
 * retain their original targets. Logical bridge handles never reach Wine. */
#include <setupapi.h>
#include <cfgmgr32.h>
#include <ddk/hidsdi.h>
static int camera_set, parent_set, controller_handle, hub_handle;
#define CAMERA_SET ((HDEVINFO)&camera_set)
#define PARENT_SET ((HDEVINFO)&parent_set)
#define CONTROLLER ((HANDLE)&controller_handle)
#define HUB ((HANDLE)&hub_handle)
#define CAMERA_INST 0x6f120000u
#define PARENT_INST 0x6f120002u
#define HUB_INST 0x6f120003u
#define HCD_INST 0x6f120004u
static const GUID camera_class={0xca3e7ab9,0xb4c3,0x4ae6,{0x82,0x51,0x57,0x9e,0xf9,0x33,0x89,0x0f}};
static const GUID image_class={0x6bdd1fc6,0x810f,0x11d0,{0xbe,0xc7,8,0,0x2b,0xe2,9,0x2f}};
static const GUID usb_interface={0xa5dcbf10,0x6530,0x11d2,{0x90,0x1f,0,0xc0,0x4f,0xb9,0x51,0xed}};
static WCHAR device_ids[5][512], parent_link[512], hub_name[256], driver_key[256];
static BYTE usb_descriptor[18];
static DWORD physical_port, physical_ports, physical_address;
static BYTE config_descriptor[8192]; static DWORD config_size;
static const GUID hub_interface={0xf18a0e88,0xc30c,0x11d0,{0x88,0x15,0,0xa0,0xc9,6,0xbe,0xd8}};
static const GUID hcd_interface={0x3abf6f2d,0x71c4,0x462a,{0x8a,0x92,0x1e,0x68,0x61,0xe6,0xaf,0x27}};
static struct tree_set {LONG used;HDEVINFO native;DWORD count;DEVINST ids[3];} tree_sets[16];
static struct tree_set *tree_lookup(HDEVINFO h){for(unsigned i=0;i<16;i++)if(h==&tree_sets[i]&&tree_sets[i].used)return &tree_sets[i];return NULL;}
static HDEVINFO tree_wrap(HDEVINFO native,BOOL all){
 if(native==INVALID_HANDLE_VALUE)return native;
 for(unsigned i=0;i<16;i++)if(!InterlockedCompareExchange(&tree_sets[i].used,1,0)){
  struct tree_set *t=&tree_sets[i];t->native=native;t->count=all?3:2;
  t->ids[0]=HUB_INST;t->ids[1]=PARENT_INST;t->ids[2]=HCD_INST;return t;
 }
 SetupDiDestroyDeviceInfoList(native);SetLastError(ERROR_NOT_ENOUGH_MEMORY);return INVALID_HANDLE_VALUE;
}
static BOOL virtual_dev(SP_DEVINFO_DATA *d){return d&&d->DevInst>=CAMERA_INST&&d->DevInst<=HCD_INST;}
static HDEVINFO native_set(HDEVINFO h){struct tree_set *t=tree_lookup(h);return t?t->native:h;}

static void info_fill(SP_DEVINFO_DATA *p,DEVINST id) {
 if(p){p->cbSize=sizeof(*p);p->ClassGuid=camera_class;p->DevInst=id;p->Reserved=0;}
}
static HDEVINFO WINAPI bridge_classes_ex(const GUID *g,PCWSTR e,HWND w,DWORD flags,HDEVINFO set,PCWSTR machine,void *reserved) {
 if(e && !lstrcmpiW(e,L"USB"))return tree_wrap(SetupDiGetClassDevsExW(g,e,w,flags,set,machine,reserved),FALSE);
 if(g && (IsEqualGUID(g,&camera_class)||IsEqualGUID(g,&image_class)))return CAMERA_SET;
 return SetupDiGetClassDevsExW(g,e,w,flags,set,machine,reserved);
}
static HDEVINFO WINAPI bridge_classes(const GUID *g,PCWSTR e,HWND w,DWORD flags) {
 if(e && !lstrcmpiW(e,device_ids[2]))return PARENT_SET;
 if(e && !lstrcmpiW(e,L"USB"))return tree_wrap(SetupDiGetClassDevsW(g,e,w,flags),FALSE);
 if(!g&&!e&&(flags&DIGCF_ALLCLASSES)&&(flags&DIGCF_DEVICEINTERFACE))return tree_wrap(SetupDiGetClassDevsW(g,e,w,flags),TRUE);
 if(g && (IsEqualGUID(g,&camera_class)||IsEqualGUID(g,&image_class)))return CAMERA_SET;
 return SetupDiGetClassDevsW(g,e,w,flags);
}
static BOOL WINAPI bridge_destroy(HDEVINFO set) {
 struct tree_set *t=tree_lookup(set);if(t){BOOL ok=SetupDiDestroyDeviceInfoList(t->native);InterlockedExchange(&t->used,0);return ok;}
 if(set==CAMERA_SET||set==PARENT_SET)return TRUE;
 return SetupDiDestroyDeviceInfoList(set);
}
static BOOL WINAPI bridge_enum_info(HDEVINFO set,DWORD i,SP_DEVINFO_DATA *p) {
 struct tree_set *t=tree_lookup(set);
 if(t){if(i<t->count){info_fill(p,t->ids[i]);return TRUE;}return SetupDiEnumDeviceInfo(t->native,i-t->count,p);}
 if(set!=CAMERA_SET&&set!=PARENT_SET)return SetupDiEnumDeviceInfo(set,i,p);
 if(!p||p->cbSize!=sizeof(*p)){SetLastError(ERROR_INVALID_PARAMETER);return FALSE;}
 if(i>=(set==CAMERA_SET?2u:1u)){SetLastError(ERROR_NO_MORE_ITEMS);return FALSE;}
 info_fill(p,set==CAMERA_SET?CAMERA_INST+i:PARENT_INST);LOG("device info instance=%lx",p->DevInst);return TRUE;
}
static CONFIGRET WINAPI bridge_id_size(PULONG size,DEVINST id,ULONG flags) {
 if(id>=CAMERA_INST&&id<=HCD_INST){if(!size)return CR_INVALID_POINTER;*size=lstrlenW(device_ids[id-CAMERA_INST]);return CR_SUCCESS;}
 return CM_Get_Device_ID_Size(size,id,flags);
}
static CONFIGRET WINAPI bridge_id(DEVINST id,PWSTR buffer,ULONG n,ULONG flags) {
 if(id>=CAMERA_INST&&id<=HCD_INST){LOG("CM device ID=%ls",device_ids[id-CAMERA_INST]);if(!buffer)return CR_INVALID_POINTER;if(n<=(ULONG)lstrlenW(device_ids[id-CAMERA_INST]))return CR_BUFFER_SMALL;lstrcpyW(buffer,device_ids[id-CAMERA_INST]);return CR_SUCCESS;}
 return CM_Get_Device_IDW(id,buffer,n,flags);
}
static CONFIGRET WINAPI bridge_parent(PDEVINST parent,DEVINST id,ULONG flags) {
 if(id==PARENT_INST||id==HUB_INST){if(!parent)return CR_INVALID_POINTER;*parent=id==PARENT_INST?HUB_INST:HCD_INST;return CR_SUCCESS;}
 if(id==HCD_INST)return CR_NO_SUCH_DEVNODE;
 if(id>=CAMERA_INST&&id<PARENT_INST){if(!parent)return CR_INVALID_POINTER;*parent=PARENT_INST;return CR_SUCCESS;}
 WCHAR native_id[512];
 if(CM_Get_Device_IDW(id,native_id,512,0)==CR_SUCCESS &&
    !wcsncmp(native_id,L"USB\\VID_2BC5&PID_0C0B&MI_04\\",28)) {
  if(!parent)return CR_INVALID_POINTER;
  *parent=PARENT_INST;LOG("mapped real Wine HID USB parent to physical composite device");return CR_SUCCESS;
 }
 return CM_Get_Parent(parent,id,flags);
}
static CONFIGRET WINAPI bridge_child(PDEVINST child,DEVINST id,ULONG flags) {
 if(id==HCD_INST||id==HUB_INST){if(!child)return CR_INVALID_POINTER;*child=id==HCD_INST?HUB_INST:PARENT_INST;return CR_SUCCESS;}
 if(id==PARENT_INST){
  WCHAR serial[128],revision[16],path[512];
  GetEnvironmentVariableW(L"PIKA_USB_SERIAL",serial,128);GetEnvironmentVariableW(L"PIKA_USB_REVISION",revision,16);
  swprintf(path,512,L"USB\\VID_2BC5&PID_0C0B&MI_04\\%ls&%ls&0&0&0",revision,serial);
  CONFIGRET ret=CM_Locate_DevNodeW(child,path,0);LOG("physical HID child query result=%lu",ret);return ret;
 }
 return CM_Get_Child(child,id,flags);
}
static BOOL WINAPI bridge_enum_interfaces(HDEVINFO set,SP_DEVINFO_DATA *dev,const GUID *g,DWORD i,SP_DEVICE_INTERFACE_DATA *out) {
 if(virtual_dev(dev)){
  const GUID *expected=dev->DevInst==HUB_INST?&hub_interface:dev->DevInst==HCD_INST?&hcd_interface:&usb_interface;
  if(i||!g||!IsEqualGUID(g,expected)){SetLastError(ERROR_NO_MORE_ITEMS);return FALSE;}
  if(!out){SetLastError(ERROR_INVALID_PARAMETER);return FALSE;}
  out->InterfaceClassGuid=*expected;out->Flags=SPINT_ACTIVE;out->Reserved=dev->DevInst;return TRUE;
 }
 if(set!=PARENT_SET)return SetupDiEnumDeviceInterfaces(native_set(set),dev,g,i,out);
 if(i||!g||!IsEqualGUID(g,&usb_interface)){SetLastError(ERROR_NO_MORE_ITEMS);return FALSE;}
 if(!out||out->cbSize!=sizeof(*out)){SetLastError(ERROR_INVALID_PARAMETER);return FALSE;}
 out->InterfaceClassGuid=usb_interface;out->Flags=SPINT_ACTIVE;out->Reserved=PARENT_INST;return TRUE;
}
static BOOL WINAPI bridge_detail(HDEVINFO set,SP_DEVICE_INTERFACE_DATA *iface,SP_DEVICE_INTERFACE_DETAIL_DATA_W *out,DWORD size,DWORD *needed,SP_DEVINFO_DATA *dev) {
 if(set!=PARENT_SET)return SetupDiGetDeviceInterfaceDetailW(native_set(set),iface,out,size,needed,dev);
 DWORD n=offsetof(SP_DEVICE_INTERFACE_DETAIL_DATA_W,DevicePath)+(lstrlenW(parent_link)+1)*2;
 if(needed)*needed=n;
 if(!out||size<n){SetLastError(ERROR_INSUFFICIENT_BUFFER);return FALSE;}
 lstrcpyW(out->DevicePath,parent_link);info_fill(dev,PARENT_INST);return TRUE;
}
static BOOL WINAPI bridge_registry(HDEVINFO set,SP_DEVINFO_DATA *dev,DWORD prop,DWORD *type,BYTE *buffer,DWORD size,DWORD *needed) {
 if(set!=PARENT_SET)return SetupDiGetDeviceRegistryPropertyW(native_set(set),dev,prop,type,buffer,size,needed);
 if(prop!=SPDRP_DRIVER){SetLastError(ERROR_INVALID_DATA);return FALSE;}
 DWORD n=(lstrlenW(driver_key)+1)*2;if(needed)*needed=n;if(type)*type=REG_SZ;
 if(!buffer||size<n){SetLastError(ERROR_INSUFFICIENT_BUFFER);return FALSE;}
 memcpy(buffer,driver_key,n);return TRUE;
}
static __attribute__((noinline)) HANDLE WINAPI bridge_open(PCWSTR name,DWORD access,DWORD share,SECURITY_ATTRIBUTES *sa,DWORD creation,DWORD attrs,HANDLE templ) {
 if(name&&!lstrcmpiW(name,L"\\\\.\\HCD0"))return CONTROLLER;
 WCHAR path[512];swprintf(path,512,L"\\\\.\\%ls",hub_name);
 if(name&&!lstrcmpiW(name,path))return HUB;
 return CreateFileW(name,access,share,sa,creation,attrs,templ);
}
static BOOL WINAPI bridge_close(HANDLE h) {
 if(h==HUB||h==CONTROLLER)return TRUE;
 return CloseHandle(h);
}
static BOOL WINAPI bridge_ioctl(HANDLE h,DWORD code,void *input,DWORD insize,void *output,DWORD size,DWORD *returned,OVERLAPPED *ov) {
 if(h!=HUB&&h!=CONTROLLER)return DeviceIoControl(h,code,input,insize,output,size,returned,ov);
 if(returned)*returned=0;
 if(!output){SetLastError(ERROR_INVALID_PARAMETER);return FALSE;}
 DWORD function=(code>>2)&0xfff;
 // USB root-hub name: HCD_GET_ROOT_HUB_NAME=258.
 if(h==CONTROLLER&&function==258&&size>=4){
  DWORD n=4+(lstrlenW(hub_name)+1)*2;*(DWORD*)output=n;
  if(size>=n)memcpy((BYTE*)output+4,hub_name,n-4);
  if(returned)*returned=size>=n?n:4;return TRUE;
 }
 // USB_GET_NODE_INFORMATION=258, on the logical bridge hub.
 if(h==HUB&&function==258&&size>=7){memset(output,0,size);((BYTE*)output)[4]=9;((BYTE*)output)[5]=0x29;((BYTE*)output)[6]=(BYTE)physical_ports;if(returned)*returned=size;return TRUE;}
 DWORD port=input&&insize>=4?*(DWORD*)input:0;
 // USB_GET_NODE_CONNECTION_INFORMATION_EX=274, packed USB descriptor ABI.
 if(h==HUB&&function==274&&size>=35){
  memset(output,0,size);*(DWORD*)output=port;
  if(port==physical_port){memcpy((BYTE*)output+4,usb_descriptor,18);((BYTE*)output)[22]=1;((BYTE*)output)[23]=3;*(USHORT*)((BYTE*)output+25)=(USHORT)physical_address;*(DWORD*)((BYTE*)output+31)=1;}
  if(returned)*returned=size;return TRUE;
 }
 // USB_GET_NODE_CONNECTION_DRIVERKEY_NAME=264.
 if(h==HUB&&function==264&&port==physical_port&&size>=8){
  DWORD n=8+(lstrlenW(driver_key)+1)*2;*(DWORD*)output=port;*((DWORD*)output+1)=n;
  if(size>=n)memcpy((BYTE*)output+8,driver_key,n-8);
  if(returned)*returned=size>=n?n:8;return TRUE;
 }
 if(h==HUB&&function==260&&port==physical_port&&insize>=12&&size>=12){
  BYTE dtype=((BYTE*)input)[7];DWORD requested=*(USHORT*)((BYTE*)input+10);
  const BYTE *bytes=dtype==2?config_descriptor:usb_descriptor;
  DWORD available=dtype==2?config_size:dtype==1?18:0;
  if(!available){SetLastError(ERROR_NOT_SUPPORTED);return FALSE;}
  DWORD n=requested<available?requested:available;if(n>size-12)n=size-12;
  memcpy((BYTE*)output+12,bytes,n);if(returned)*returned=n+12;return TRUE;
 }
 LOG("unsupported topology ioctl=%lx function=%lu size=%lu",code,function,size);
 SetLastError(ERROR_NOT_SUPPORTED);return FALSE;
}
static HDEVINFO WINAPI bridge_classes_a(const GUID *g,PCSTR e,HWND w,DWORD flags) {
 WCHAR wide[512];PCWSTR p=NULL;if(e){MultiByteToWideChar(CP_ACP,0,e,-1,wide,512);p=wide;}
 return bridge_classes(g,p,w,flags);
}
static BOOL WINAPI bridge_instance_a(HDEVINFO set,SP_DEVINFO_DATA *dev,CHAR *out,DWORD size,DWORD *needed) {
 if(!virtual_dev(dev))return SetupDiGetDeviceInstanceIdA(native_set(set),dev,out,size,needed);
 if(!dev||dev->DevInst<CAMERA_INST||dev->DevInst>HCD_INST){SetLastError(ERROR_INVALID_PARAMETER);return FALSE;}
 WCHAR *id=device_ids[dev->DevInst-CAMERA_INST];DWORD n=lstrlenW(id)+1;if(needed)*needed=n;
 if(!out||size<n){SetLastError(ERROR_INSUFFICIENT_BUFFER);return FALSE;}
 WideCharToMultiByte(CP_ACP,0,id,-1,out,size,NULL,NULL);return TRUE;
}
static BOOL WINAPI bridge_registry_a(HDEVINFO set,SP_DEVINFO_DATA *dev,DWORD prop,DWORD *type,BYTE *buffer,DWORD size,DWORD *needed) {
 if(!virtual_dev(dev))return SetupDiGetDeviceRegistryPropertyA(native_set(set),dev,prop,type,buffer,size,needed);
 char driver[512];
 const char *value=NULL;
 switch(prop){
 case SPDRP_ENUMERATOR_NAME:value="USB";break;
 case SPDRP_SERVICE:value=dev->DevInst==PARENT_INST?"usbccgp":"usbhub3";break;
 case SPDRP_UPPERFILTERS:case SPDRP_LOWERFILTERS:SetLastError(ERROR_INVALID_DATA);return FALSE;
 case SPDRP_LOCATION_INFORMATION:snprintf(driver,sizeof(driver),"Port_#%04lu.Hub_#0001",physical_port);value=driver;break;
 case SPDRP_INSTALL_STATE:case SPDRP_ADDRESS:
  if(needed)*needed=4;if(type)*type=REG_DWORD;if(!buffer||size<4){SetLastError(ERROR_INSUFFICIENT_BUFFER);return FALSE;}
  *(DWORD*)buffer=prop==SPDRP_ADDRESS?physical_port:0;return TRUE;
 case SPDRP_DRIVER:WideCharToMultiByte(CP_ACP,0,driver_key,-1,driver,sizeof(driver),NULL,NULL);value=driver;break;
 case SPDRP_DEVICEDESC:case SPDRP_FRIENDLYNAME:value="Creality Pika";break;
 case SPDRP_MFG:value="Creality";break;
 case SPDRP_HARDWAREID:value="USB\\VID_2BC5&PID_0C0B";break;
 case SPDRP_COMPATIBLEIDS:value="USB\\COMPOSITE";break;
 default:LOG("unsupported parent registry property A %lu",prop);SetLastError(ERROR_INVALID_DATA);return FALSE;
 }
 BOOL multi=prop==SPDRP_HARDWAREID||prop==SPDRP_COMPATIBLEIDS;
 DWORD n=strlen(value)+1+multi;if(needed)*needed=n;if(type)*type=multi?REG_MULTI_SZ:REG_SZ;
 if(!buffer||size<n){SetLastError(ERROR_INSUFFICIENT_BUFFER);return FALSE;}
 memset(buffer,0,n);memcpy(buffer,value,strlen(value));return TRUE;
}
static BOOL WINAPI bridge_detail_a(HDEVINFO set,SP_DEVICE_INTERFACE_DATA *iface,SP_DEVICE_INTERFACE_DETAIL_DATA_A *out,DWORD size,DWORD *needed,SP_DEVINFO_DATA *dev) {
 if(!iface||iface->Reserved<CAMERA_INST||iface->Reserved>HCD_INST)return SetupDiGetDeviceInterfaceDetailA(native_set(set),iface,out,size,needed,dev);
 WCHAR wide[512];
 if(iface->Reserved==HUB_INST)swprintf(wide,512,L"\\\\.\\%ls",hub_name);
 else if(iface->Reserved==HCD_INST)lstrcpyW(wide,L"\\\\.\\HCD0");
 else lstrcpyW(wide,parent_link);
 char path[1024];WideCharToMultiByte(CP_ACP,0,wide,-1,path,1024,NULL,NULL);
 DWORD n=offsetof(SP_DEVICE_INTERFACE_DETAIL_DATA_A,DevicePath)+strlen(path)+1;if(needed)*needed=n;
 if(!out||size<n){SetLastError(ERROR_INSUFFICIENT_BUFFER);return FALSE;}
 strcpy(out->DevicePath,path);info_fill(dev,(DEVINST)iface->Reserved);return TRUE;
}
static HKEY WINAPI bridge_open_reg(HDEVINFO set,SP_DEVINFO_DATA *dev,DWORD scope,DWORD profile,DWORD key,REGSAM access){
 if(virtual_dev(dev)){SetLastError(ERROR_FILE_NOT_FOUND);return INVALID_HANDLE_VALUE;}
 return SetupDiOpenDevRegKey(native_set(set),dev,scope,profile,key,access);
}
static HANDLE WINAPI bridge_open_a(PCSTR name,DWORD access,DWORD share,SECURITY_ATTRIBUTES *sa,DWORD creation,DWORD attrs,HANDLE templ){
 WCHAR wide[512];if(name&&MultiByteToWideChar(CP_ACP,0,name,-1,wide,512)){
  WCHAR path[512];swprintf(path,512,L"\\\\.\\%ls",hub_name);
  if(!lstrcmpiW(wide,path)||!lstrcmpiW(wide,L"\\\\.\\HCD0"))return bridge_open(wide,access,share,sa,creation,attrs,templ);
 }
 return CreateFileA(name,access,share,sa,creation,attrs,templ);
}
static BOOLEAN WINAPI bridge_hid_string(HANDLE handle,ULONG index,void *buffer,ULONG length){
 HIDD_ATTRIBUTES attrs={.Size=sizeof(attrs)};
 if(HidD_GetAttributes(handle,&attrs)&&attrs.VendorID==0x2bc5&&attrs.ProductID==0x0c0b){
  WCHAR key[64];swprintf(key,64,L"PIKA_USB_STRING_%lu",index);
  DWORD needed=GetEnvironmentVariableW(key,NULL,0);
  if(!needed){SetLastError(ERROR_NOT_SUPPORTED);return FALSE;}
  if(!buffer||length<needed*2){SetLastError(ERROR_INSUFFICIENT_BUFFER);return FALSE;}
  GetEnvironmentVariableW(key,buffer,length/2);
  LOG("physical USB indexed string %lu: %ls",index,(WCHAR*)buffer);return TRUE;
 }
 return HidD_GetIndexedString(handle,index,buffer,length);
}
static FARPROC WINAPI bridge_getproc(HMODULE m,LPCSTR name) {
 if ((ULONG_PTR)name>65535) {
#define MAP(n,f) if(!strcmp(name,n))return (FARPROC)(void*)f
  MAP("HidD_GetIndexedString",bridge_hid_string);
  MAP("SetupDiGetDeviceInterfaceDetailA",bridge_detail_a);
  MAP("SetupDiOpenDevRegKey",bridge_open_reg);
  MAP("SetupDiGetClassDevsA",bridge_classes_a);
  MAP("SetupDiGetDeviceInstanceIdA",bridge_instance_a);
  MAP("SetupDiGetDeviceRegistryPropertyA",bridge_registry_a);
  MAP("CM_Get_Child",bridge_child);
  MAP("CM_Get_Parent",bridge_parent);
  MAP("CM_Get_Device_IDW",bridge_id);
  MAP("CM_Get_Device_ID_Size",bridge_id_size);
  MAP("SetupDiGetClassDevsW",bridge_classes);
  MAP("SetupDiGetClassDevsExW",bridge_classes_ex);
  MAP("SetupDiEnumDeviceInfo",bridge_enum_info);
  MAP("SetupDiDestroyDeviceInfoList",bridge_destroy);
  MAP("SetupDiEnumDeviceInterfaces",bridge_enum_interfaces);
  MAP("SetupDiGetDeviceInterfaceDetailW",bridge_detail);
  MAP("SetupDiGetDeviceRegistryPropertyW",bridge_registry);
#undef MAP
  if(!strncmp(name,"CM_",3)||!strncmp(name,"SetupDi",7))LOG("dynamic device API passthrough: %s",name);
 }
 return GetProcAddress(m,name);
}
static void install_device_tree(void) {
 static BOOL installed;
 if(installed||!sdk_mode())return;
 HMODULE module=GetModuleHandleW(L"OrbbecSDK-stock.dll");
 if(!module)module=GetModuleHandleW(L"OrbbecSDK.dll");if(!module)return;
 WCHAR serial[128],revision[16],location[64];char descriptor[64],port[16],ports[16];
 if(!GetEnvironmentVariableW(L"PIKA_USB_SERIAL",serial,128)||!GetEnvironmentVariableW(L"PIKA_USB_REVISION",revision,16)||
    !GetEnvironmentVariableW(L"PIKA_USB_HUB",location,64)||!GetEnvironmentVariableA("PIKA_USB_DESCRIPTOR",descriptor,64)||
    !GetEnvironmentVariableA("PIKA_USB_PORT",port,16)||!GetEnvironmentVariableA("PIKA_USB_PORTS",ports,16))return;
 if(strlen(descriptor)!=36)return;
 for(unsigned i=0;i<18;i++){char hex[3]={descriptor[i*2],descriptor[i*2+1],0};usb_descriptor[i]=(BYTE)strtoul(hex,NULL,16);}
 static char config[16385];char address[16];
 if(!GetEnvironmentVariableA("PIKA_USB_CONFIG",config,sizeof(config))||!GetEnvironmentVariableA("PIKA_USB_ADDRESS",address,16))return;
 config_size=strlen(config)/2;if(config_size>sizeof(config_descriptor))return;
 for(unsigned i=0;i<config_size;i++){char hex[3]={config[i*2],config[i*2+1],0};config_descriptor[i]=(BYTE)strtoul(hex,NULL,16);}
 physical_address=atoi(address);
 physical_port=atoi(port);physical_ports=atoi(ports);
 if(!physical_port||physical_port>physical_ports||physical_ports>255)return;
 for(unsigned i=0;i<2;i++)swprintf(device_ids[i],512,L"USB\\VID_2BC5&PID_0C0B&MI_%02u\\%ls&%ls&0&0&0",i*2,revision,serial);
 swprintf(device_ids[2],512,L"USB\\VID_2BC5&PID_0C0B\\%ls",serial);
 swprintf(parent_link,512,L"\\\\?\\usb#vid_2bc5&pid_0c0b#%ls#{a5dcbf10-6530-11d2-901f-00c04fb951ed}",serial);
 swprintf(hub_name,256,L"USB#PIKA_BRIDGE_HUB#%ls#{f18a0e88-c30c-11d0-8815-00a0c906bed8}",location);
 swprintf(device_ids[3],512,L"USB\\ROOT_HUB30\\%ls",location);
 swprintf(device_ids[4],512,L"PCI\\PIKA_BRIDGE_HOST\\%ls",location);
 swprintf(driver_key,256,L"PikaLinuxBridge\\%ls",serial);
 struct hook {const char *name;void *target;} hooks[]={
  {"MFCreateSourceReaderFromMediaSource",bridge_create_reader},
  {"SetupDiGetClassDevsExW",bridge_classes_ex},{"SetupDiGetClassDevsW",bridge_classes},
  {"SetupDiEnumDeviceInfo",bridge_enum_info},{"SetupDiDestroyDeviceInfoList",bridge_destroy},
  {"CM_Get_Device_ID_Size",bridge_id_size},{"CM_Get_Device_IDW",bridge_id},{"CM_Get_Parent",bridge_parent},
  {"SetupDiEnumDeviceInterfaces",bridge_enum_interfaces},{"SetupDiGetDeviceInterfaceDetailW",bridge_detail},
  {"SetupDiGetDeviceRegistryPropertyW",bridge_registry},{"CreateFileW",bridge_open},
  {"CreateFileA",bridge_open_a},{"CloseHandle",bridge_close},{"DeviceIoControl",bridge_ioctl},{"GetProcAddress",bridge_getproc}};
 BYTE *base=(BYTE*)module;IMAGE_DOS_HEADER *dos=(void*)base;
 IMAGE_NT_HEADERS *nt=(void*)(base+dos->e_lfanew);
 IMAGE_IMPORT_DESCRIPTOR *imports=(void*)(base+nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress);
 unsigned total=0;
 for(;imports->Name;imports++){
  if(!imports->OriginalFirstThunk)continue;
  IMAGE_THUNK_DATA *names=(void*)(base+imports->OriginalFirstThunk),*slots=(void*)(base+imports->FirstThunk);
  for(;names->u1.AddressOfData;names++,slots++){
   if(IMAGE_SNAP_BY_ORDINAL(names->u1.Ordinal))continue;
   IMAGE_IMPORT_BY_NAME *name=(void*)(base+names->u1.AddressOfData);
   for(unsigned i=0;i<sizeof(hooks)/sizeof(hooks[0]);i++)if(!strcmp((char*)name->Name,hooks[i].name)){
    DWORD old;if(VirtualProtect(&slots->u1.Function,sizeof(void*),PAGE_READWRITE,&old)){
     InterlockedExchangePointer((void**)&slots->u1.Function,hooks[i].target);
     DWORD ignored;VirtualProtect(&slots->u1.Function,sizeof(void*),old,&ignored);total++;
    }
   }
  }
 }
 installed=TRUE;LOG("installed %u process-local SDK device-tree API mappings for physical Pika",total);
}

void WINAPI PikaBridgePrepareSDK(void) { install_device_tree(); }
