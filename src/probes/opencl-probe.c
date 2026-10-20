/* Transparent x64 Windows OpenCL probe; no downloaded binary or C runtime.
 * OpenCL 1.2 ABI declarations, dynamically loaded from Wine's opencl.dll.
 * Selects RX 6800 XT by name/AMD board name, then checks all 256 results. */
typedef unsigned int U; typedef int I; typedef unsigned long long Q;
typedef unsigned long long SZ; typedef void *P;
__declspec(dllimport) P LoadLibraryA(const char*);
__declspec(dllimport) P GetProcAddress(P,const char*);
__declspec(dllimport) P GetStdHandle(U);
__declspec(dllimport) I WriteFile(P,const void*,U,U*,P);
__declspec(dllimport) U GetEnvironmentVariableA(const char*,char*,U);
__declspec(dllimport) U GetModuleFileNameA(P,char*,U);
__declspec(dllimport) U GetLastError(void);
__declspec(dllimport) void ExitProcess(U);
static U len(const char *s){U n=0;while(s[n])++n;return n;}
static void out(const char*s){U n;WriteFile(GetStdHandle((U)-11),s,len(s),&n,0);}
static void num(Q n){char b[32];U i=31;b[i]=0;do{b[--i]='0'+n%10;n/=10;}while(n);out(b+i);}
static void line(const char*k,const char*v){out(k);out(v);out("\r\n");}
static void ck(const char*s,I e){if(e){out("FAIL ");out(s);out(" error=");if(e<0){out("-");num(-e);}else num(e);out("\r\n");ExitProcess(1);}}
static I has(const char*s,const char*t){for(;*s;++s){U j=0;while(t[j]&&s[j]==t[j])++j;if(!t[j])return 1;}return 0;}
#define FN(ret,name,args) static ret (*name) args
FN(I,clGetPlatformIDs,(U,P*,U*)); FN(I,clGetPlatformInfo,(P,U,SZ,P,SZ*));
FN(I,clGetDeviceIDs,(P,Q,U,P*,U*)); FN(I,clGetDeviceInfo,(P,U,SZ,P,SZ*));
FN(P,clCreateContext,(const SZ*,U,const P*,P,P,I*)); FN(P,clCreateCommandQueue,(P,P,Q,I*));
FN(P,clCreateProgramWithSource,(P,U,const char**,const SZ*,I*));
FN(I,clBuildProgram,(P,U,const P*,const char*,P,P)); FN(I,clGetProgramBuildInfo,(P,P,U,SZ,P,SZ*));
FN(P,clCreateKernel,(P,const char*,I*)); FN(P,clCreateBuffer,(P,Q,SZ,P,I*));
FN(I,clSetKernelArg,(P,U,SZ,const void*));
FN(I,clEnqueueNDRangeKernel,(P,P,U,const SZ*,const SZ*,const SZ*,U,const P*,P*));
FN(I,clEnqueueReadBuffer,(P,P,U,SZ,SZ,P,U,const P*,P*));
FN(I,clReleaseMemObject,(P)); FN(I,clReleaseKernel,(P)); FN(I,clReleaseProgram,(P));
FN(I,clReleaseCommandQueue,(P)); FN(I,clReleaseContext,(P));
#define LOAD(n) n=(void*)GetProcAddress(lib,#n);if(!n){line("FAIL missing export ",#n);ExitProcess(1);}
static char wanted[256];static char buf[16384];static P platforms[16],devices[32];static I values[256];
void mainCRTStartup(void){
 out("CrealityScan Windows x64 OpenCL correctness probe\r\n");
 GetEnvironmentVariableA("WINEDLLOVERRIDES",buf,sizeof(buf));line("WINEDLLOVERRIDES=",buf);
 if(!GetEnvironmentVariableA("CREALITY_GPU_NAME",wanted,sizeof(wanted))){out("FAIL set CREALITY_GPU_NAME\r\n");ExitProcess(1);}
 P lib=LoadLibraryA("opencl.dll");if(!lib){out("FAIL LoadLibrary(opencl.dll) Windows error=");num(GetLastError());out("\r\n");ExitProcess(1);}
 GetModuleFileNameA(lib,buf,sizeof(buf));line("Loaded OpenCL module: ",buf);
 LOAD(clGetPlatformIDs) LOAD(clGetPlatformInfo) LOAD(clGetDeviceIDs) LOAD(clGetDeviceInfo)
 LOAD(clCreateContext) LOAD(clCreateCommandQueue) LOAD(clCreateProgramWithSource) LOAD(clBuildProgram)
 LOAD(clGetProgramBuildInfo) LOAD(clCreateKernel) LOAD(clCreateBuffer) LOAD(clSetKernelArg)
 LOAD(clEnqueueNDRangeKernel) LOAD(clEnqueueReadBuffer) LOAD(clReleaseMemObject) LOAD(clReleaseKernel)
 LOAD(clReleaseProgram) LOAD(clReleaseCommandQueue) LOAD(clReleaseContext)
 U np=0;ck("clGetPlatformIDs",clGetPlatformIDs(16,platforms,&np));if(np>16)ExitProcess(1);
 P selected=0;for(U p=0;p<np;++p){
  ck("platform name",clGetPlatformInfo(platforms[p],0x0902,sizeof(buf),buf,0));line("Platform: ",buf);
  U nd=0;I err=clGetDeviceIDs(platforms[p],4,32,devices,&nd);if(err==-1)continue;ck("clGetDeviceIDs",err);if(nd>32)ExitProcess(1);
  for(U d=0;d<nd;++d){P dev=devices[d];ck("device name",clGetDeviceInfo(dev,0x102B,sizeof(buf),buf,0));line("GPU: ",buf);I match=has(buf,wanted);
   if(!clGetDeviceInfo(dev,0x4038,sizeof(buf),buf,0)){line("AMD board: ",buf);match|=has(buf,wanted);}
   U v=0;ck("compiler",clGetDeviceInfo(dev,0x1028,sizeof(v),&v,0));out("Compiler available: ");num(v);out("\r\n");
   U im=0;ck("images",clGetDeviceInfo(dev,0x1016,sizeof(im),&im,0));out("Image support: ");num(im);out("\r\n");
   Q mem=0;ck("memory",clGetDeviceInfo(dev,0x101F,sizeof(mem),&mem,0));out("Global memory bytes: ");num(mem);out("\r\n");
   if(match&&v&&im&&!selected)selected=dev;
  }
 }
 if(!selected){out("FAIL configured GPU with compiler and images not found\r\n");ExitProcess(1);}
 I e;P context=clCreateContext(0,1,&selected,0,0,&e);ck("context",e);
 P queue=clCreateCommandQueue(context,selected,0,&e);ck("queue",e);
 const char*src="__kernel void check(__global int *a){int i=get_global_id(0);a[i]=i*3+7;}";
 P program=clCreateProgramWithSource(context,1,&src,0,&e);ck("program",e);
 e=clBuildProgram(program,1,&selected,"",0,0);if(e){clGetProgramBuildInfo(program,selected,0x1183,sizeof(buf),buf,0);line("Build log: ",buf);ck("build",e);}
 P kernel=clCreateKernel(program,"check",&e);ck("kernel",e);
 P mem=clCreateBuffer(context,1,sizeof(values),0,&e);ck("buffer",e);ck("arg",clSetKernelArg(kernel,0,sizeof(mem),&mem));
 SZ count=256;ck("execute",clEnqueueNDRangeKernel(queue,kernel,1,0,&count,0,0,0,0));
 ck("read",clEnqueueReadBuffer(queue,mem,1,0,sizeof(values),values,0,0,0));
 for(I i=0;i<256;++i)if(values[i]!=i*3+7){out("FAIL incorrect kernel output\r\n");ExitProcess(1);}
 clReleaseMemObject(mem);clReleaseKernel(kernel);clReleaseProgram(program);clReleaseCommandQueue(queue);clReleaseContext(context);
 out("PASS: configured GPU compiled and executed OpenCL kernel; all 256 values correct.\r\n");ExitProcess(0);
}
