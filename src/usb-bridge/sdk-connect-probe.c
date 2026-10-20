/* Discovery reproducer using CrealityScan's original OrbbecSDK.dll.
 * Optional PIKA_NET_IP tests the generic network API (not Pika's RPC transport).
 * Optional PIKA_RPC_IP exercises the SDK network-server API. Its name does
 * not establish that it enables client-side discovery; this is experimental.
 * No stream start, firmware operation or SDK replacement.
 * API signatures: upstream OrbbecSDK include/libobsensor/h/{Context,Device,Error}.h.
 */
typedef void *P; typedef unsigned int U; typedef int I;
__declspec(dllimport) P LoadLibraryA(const char*);
__declspec(dllimport) P GetProcAddress(P,const char*);
__declspec(dllimport) P GetStdHandle(U);
__declspec(dllimport) I WriteFile(P,const void*,U,U*,P);
__declspec(dllimport) U GetEnvironmentVariableA(const char*,char*,U);
__declspec(dllimport) U GetLastError(void);
__declspec(dllimport) void ExitProcess(U);
__declspec(dllimport) void Sleep(U);
static void out(const char*s){U n=0,w;if(!s)s="(null)";while(s[n])++n;WriteFile(GetStdHandle((U)-11),s,n,&w,0);}
static void num(U n){char b[16];U i=15;b[i]=0;do{b[--i]='0'+n%10;n/=10;}while(n);out(b+i);}
static P api(P lib,const char*n){P p=GetProcAddress(lib,n);if(!p){out("Missing API: ");out(n);out("\r\n");ExitProcess(2);}return p;}
static const char *(*message)(P);
static void check(const char *stage,P e){if(e){out("ERROR ");out(stage);out(": ");out(message(e));out("\r\n");ExitProcess(2);}}
static char dir[2048],net_ip[64];
static char assets[2048],logs[2048],app[2048];
static const char *scanconfig[16];
#include "sdk-stream-probe.inc"
void mainCRTStartup(void){
 out("CrealityScan bundled SDK USB identity/control diagnostic\r\n");
 U n=GetEnvironmentVariableA("ORBBEC_SDK_DIR",dir,sizeof(dir));if(!n||n>=sizeof(dir))ExitProcess(2);
 I (*setdir)(const char*)=api(LoadLibraryA("kernel32.dll"),"SetDllDirectoryA");
 if(!setdir(dir))ExitProcess(2);
 P lib=LoadLibraryA("OrbbecSDK.dll");if(!lib){out("DLL load failed: ");num(GetLastError());out("\r\n");ExitProcess(2);}
 P bridge=LoadLibraryA("mf.dll");
 if(!GetEnvironmentVariableA("PIKA_AUTOLOAD_TEST",net_ip,sizeof(net_ip))){void (*prepare)(void)=api(bridge,"PikaBridgePrepareSDK");prepare();}
 message=api(lib,"ob_error_message");
 I (*version)(void)=api(lib,"ob_get_version");
 void (*logging)(I,P*)=api(lib,"ob_set_logger_to_console");
 void (*severity)(I,P*)=api(lib,"ob_set_logger_severity");
 P (*create)(P*)=api(lib,"ob_create_context");
 P (*query)(P,P*)=api(lib,"ob_query_device_list");
 U (*count)(P,P*)=api(lib,"ob_device_list_device_count");
 const char* (*name)(P,U,P*)=api(lib,"ob_device_list_get_device_name");
 void (*del_list)(P,P*)=api(lib,"ob_delete_device_list");
 void (*del_context)(P,P*)=api(lib,"ob_delete_context");
 out("SDK version number: ");num(version());out("\r\n");
 out("Exports ob_set_uvc_backend: ");out(GetProcAddress(lib,"ob_set_uvc_backend")?"yes":"no");out("\r\n");
 P e=0;logging(0,&e);check("console logging",e);severity(0,&e);check("log severity",e);
 P scanctx=0;
 if(GetEnvironmentVariableA("PIKA_SCAN_INIT",net_ip,sizeof(net_ip))){
   P scanlib=LoadLibraryA("lib_orbbec_scan.dll");if(!scanlib){out("Scan SDK load failed: ");num(GetLastError());ExitProcess(2);}
   I (*scancreate)(P*,const void*)=api(scanlib,"obscan_context_create");
   if(!GetEnvironmentVariableA("CREALITY_PROBE_ASSETS",assets,sizeof(assets))||!GetEnvironmentVariableA("CREALITY_PROBE_LOGS",logs,sizeof(logs))||!GetEnvironmentVariableA("CREALITY_PROBE_APP",app,sizeof(app)))ExitProcess(2);
   scanconfig[0]=assets;scanconfig[2]=logs;scanconfig[3]=app;
   out("Initializing through CrealityScan's original scan library...\r\n");
   I result=scancreate(&scanctx,scanconfig);out("Scan initialization result: ");num(result);out("\r\n");
   if(result||!scanctx)ExitProcess(2);
 }
 P ctx=create(&e);check("create context",e);if(!ctx)ExitProcess(2);
 if(GetEnvironmentVariableA("PIKA_RPC_IP",net_ip,sizeof(net_ip))){
   void (*enable_rpc)(P,const char*,P*)=api(lib,"ob_enable_network_server");
   out("Testing network-server API with ");out(net_ip);out("\r\n");
   enable_rpc(ctx,net_ip,&e);check("network-server API",e);
 }
 /* Network enumeration completes asynchronously after initial interface setup. */
 Sleep(6000);
 P list=query(ctx,&e);check("query list",e);U c=count(list,&e);check("count",e);
 out("SDK discovered devices: ");num(c);out("\r\n");
 for(U i=0;i<c;++i){out("SDK device: ");out(name(list,i,&e));check("device name",e);out("\r\n");}
 if(c){
   P (*getdev)(P,U,P*)=api(lib,"ob_device_list_get_device");
   P (*getinfo)(P,P*)=api(lib,"ob_device_get_device_info");
   const char* (*serial)(P,P*)=api(lib,"ob_device_info_serial_number");
   const char* (*firmware)(P,P*)=api(lib,"ob_device_info_firmware_version");
   P (*getsensors)(P,P*)=api(lib,"ob_device_get_sensor_list");
   U (*sensorcount)(P,P*)=api(lib,"ob_sensor_list_get_sensor_count");
   I (*sensortype)(P,U,P*)=api(lib,"ob_sensor_list_get_sensor_type");
   void (*deldev)(P,P*)=api(lib,"ob_delete_device");
   void (*delinfo)(P,P*)=api(lib,"ob_delete_device_info");
   void (*delsensors)(P,P*)=api(lib,"ob_delete_sensor_list");
   out("Opening first USB SDK device...\r\n");
   P dev=getdev(list,0,&e);check("open device",e);
   P info=getinfo(dev,&e);check("get device info",e);
   out("Physical serial: ");out(serial(info,&e));check("serial",e);out("\r\nFirmware: ");out(firmware(info,&e));check("firmware",e);out("\r\n");
   P sensors=getsensors(dev,&e);check("sensor list",e);
   U sc=sensorcount(sensors,&e);check("sensor count",e);out("SDK sensors: ");num(sc);out("\r\n");
   for(U i=0;i<sc;i++){out("Sensor type: ");num(sensortype(sensors,i,&e));check("sensor type",e);out("\r\n");}
   if(GetEnvironmentVariableA("PIKA_STREAM_PROFILES",net_ip,sizeof(net_ip))){
     P (*getsensor)(P,U,P*)=api(lib,"ob_sensor_list_get_sensor");
     P (*profiles)(P,P*)=api(lib,"ob_sensor_get_stream_profile_list");
     U (*pcount)(P,P*)=api(lib,"ob_stream_profile_list_count");
     P (*profile)(P,U,P*)=api(lib,"ob_stream_profile_list_get_profile");
     U (*format)(P,P*)=api(lib,"ob_stream_profile_format");
     U (*width)(P,P*)=api(lib,"ob_video_stream_profile_width");
     U (*height)(P,P*)=api(lib,"ob_video_stream_profile_height");
     U (*fps)(P,P*)=api(lib,"ob_video_stream_profile_fps");
     void (*delp)(P,P*)=api(lib,"ob_delete_stream_profile");
     void (*delpl)(P,P*)=api(lib,"ob_delete_stream_profile_list");
     void (*dels)(P,P*)=api(lib,"ob_delete_sensor");
     for(U i=0;i<sc;i++){
       I st=sensortype(sensors,i,&e);if(st!=2&&st!=6&&st!=7)continue;
       P sensor=getsensor(sensors,i,&e);check("get sensor",e);
       P pl=profiles(sensor,&e);check("profiles",e);U pc=pcount(pl,&e);check("profile count",e);
       out("PROFILE sensor=");num(st);out(" count=");num(pc);out("\r\n");
       for(U j=0;j<pc;j++){P pr=profile(pl,j,&e);check("profile",e);
         out("PROFILE index=");num(j);out(" format=");num(format(pr,&e));check("format",e);
         out(" width=");num(width(pr,&e));check("width",e);out(" height=");num(height(pr,&e));check("height",e);
         out(" fps=");num(fps(pr,&e));check("fps",e);out("\r\n");delp(pr,&e);check("del profile",e);
       }
       delpl(pl,&e);check("del profiles",e);dels(sensor,&e);check("del sensor",e);
     }
   }
   if(GetEnvironmentVariableA("PIKA_STREAM_TEST",net_ip,sizeof(net_ip)))stream_test(lib,sensors);
   delsensors(sensors,&e);check("delete sensors",e);delinfo(info,&e);check("delete info",e);deldev(dev,&e);check("delete device",e);
   out("PASSED: SDK device open, physical identity and sensor enumeration.\r\n");
 }
 del_list(list,&e);check("delete list",e);
 U direct=0;
 if(GetEnvironmentVariableA("PIKA_NET_IP",net_ip,sizeof(net_ip))){
   P (*netdev)(P,const char*,unsigned short,P*)=api(lib,"ob_create_net_device");
   P (*info)(P,P*)=api(lib,"ob_device_get_device_info");
   const char* (*devname)(P,P*)=api(lib,"ob_device_info_name");
   void (*del_info)(P,P*)=api(lib,"ob_delete_device_info");
   void (*del_dev)(P,P*)=api(lib,"ob_delete_device");
   out("Direct SDK connection to ");out(net_ip);out(":8090\r\n");
   P dev=netdev(ctx,net_ip,8090,&e);check("direct network connection",e);
   if(dev){P i=info(dev,&e);check("network device info",e);out("Direct SDK device: ");out(devname(i,&e));check("network device name",e);out("\r\n");
     del_info(i,&e);check("delete network device info",e);del_dev(dev,&e);check("delete network device",e);direct=1;}
 }
 del_context(ctx,&e);check("delete context",e);
 out(c?"Discovery and device opening passed. Use --streams for stream validation.\r\n":"FAILED: original SDK enumerates no scanner.\r\n");
 if(direct)out("PASS: direct SDK network connection; streaming NOT TESTED.\r\n");
 if(scanctx){
  P kernel=LoadLibraryA("kernel32.dll");P (*self)(void)=api(kernel,"GetCurrentProcess");I (*terminate)(P,U)=api(kernel,"TerminateProcess");
  terminate(self(),c||direct?0:1);
 }
 ExitProcess(c||direct?0:1);
}
