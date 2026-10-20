/* Called after genuine scan-library initialization and device enumeration.
 * Callback owns each SDK frame and releases it after checking/saving bytes. */
static P (*frame_data)(P,P*);
static U (*frame_size)(P,P*);
static unsigned long long (*frame_time)(P,P*);
static void (*delete_frame)(P,P*);
static long InterlockedIncrement(volatile long *p){return __atomic_add_fetch(p,1,__ATOMIC_SEQ_CST);}
__declspec(dllimport) U GetTickCount(void);
__declspec(dllimport) P CreateFileA(const char*,U,U,P,U,U,P);
__declspec(dllimport) I CloseHandle(P);
static volatile long frame_counts[3], frame_bad[3];
static unsigned long long last_times[3];
static const char *frame_names[]={"usb-sdk-color.bin","usb-sdk-left.bin","usb-sdk-right.bin"};
static void stream_callback(P frame,void *user){
 U slot=(U)(unsigned long long)user;P e=0;
 U size=frame_size(frame,&e);P data=e?0:frame_data(frame,&e);
 unsigned long long stamp=e?0:frame_time(frame,&e);
 if(e||!data||!size||!stamp||size>16*1024*1024)InterlockedIncrement(&frame_bad[slot]);
 else {
   long n=InterlockedIncrement(&frame_counts[slot]);
   if(n>1&&stamp<=last_times[slot])InterlockedIncrement(&frame_bad[slot]);
   last_times[slot]=stamp;
   if(n==1){P file=CreateFileA(frame_names[slot],0x40000000,0,0,2,0x80,0);U written;
     if(file!=(P)-1){WriteFile(file,data,size,&written,0);CloseHandle(file);}
   }
 }
 e=0;delete_frame(frame,&e);
}
static void stream_test(P lib,P sensorlist){
 P (*get)(P,I,P*)=api(lib,"ob_sensor_list_get_sensor_by_type");
 P (*profiles)(P,P*)=api(lib,"ob_sensor_get_stream_profile_list");
 P (*profile)(P,U,U,I,U,P*)=api(lib,"ob_stream_profile_list_get_video_stream_profile");
 void (*start)(P,P,void (*)(P,void*),void*,P*)=api(lib,"ob_sensor_start");
 void (*stop)(P,P*)=api(lib,"ob_sensor_stop");
 void (*delp)(P,P*)=api(lib,"ob_delete_stream_profile");
 void (*delpl)(P,P*)=api(lib,"ob_delete_stream_profile_list");
 void (*dels)(P,P*)=api(lib,"ob_delete_sensor");
 frame_data=api(lib,"ob_frame_data");frame_size=api(lib,"ob_frame_data_size");
 frame_time=api(lib,"ob_frame_time_stamp_us");delete_frame=api(lib,"ob_delete_frame");
 I color_format=5;char rgbtest[8];if(GetEnvironmentVariableA("PIKA_STREAM_RGB",rgbtest,sizeof(rgbtest)))color_format=22;
 P sensors[3]={0},lists[3]={0},pr[3]={0},e=0;I types[3]={2,6,7};
 for(U i=0;i<3;i++){
  sensors[i]=get(sensorlist,types[i],&e);check("stream sensor",e);
  lists[i]=profiles(sensors[i],&e);check("stream profiles",e);
  pr[i]=profile(lists[i],1280,960,i?9:color_format,i?60:30,&e);check("stream select Y8/MJPG",e);
 }
 for(U cycle=0;cycle<2;cycle++){
  for(U i=0;i<3;i++){frame_counts[i]=frame_bad[i]=0;last_times[i]=0;
   out("START sensor=");num(types[i]);out(" cycle=");num(cycle);out("\r\n");
   start(sensors[i],pr[i],stream_callback,(void*)(unsigned long long)i,&e);check("start stream",e);
  }
  Sleep(4000);
  for(I i=2;i>=0;i--){stop(sensors[i],&e);check("stop stream",e);}
  I passed=1;
  for(U i=0;i<3;i++){
   out("FRAMES sensor=");num(types[i]);out(" count=");num(frame_counts[i]);out(" invalid=");num(frame_bad[i]);out(" timestamp_us_hi32=");num((U)(last_times[i]>>32));out(" low32=");num((U)last_times[i]);out("\r\n");
   if(frame_counts[i]<3||frame_bad[i])passed=0;
  }
  if(!passed){out("FAILED: SDK streaming acceptance\r\n");ExitProcess(3);}
 }
 for(U i=0;i<3;i++){delp(pr[i],&e);check("delete profile",e);delpl(lists[i],&e);check("delete profiles",e);dels(sensors[i],&e);check("delete sensor",e);}
 out("PASSED: three real SDK camera streams, including stop/restart. App preview/scanning still requires validation.\r\n");
}
