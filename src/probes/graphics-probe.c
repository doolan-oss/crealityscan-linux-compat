__declspec(dllimport) unsigned int GetEnvironmentVariableA(const char*,char*,unsigned int);
/* Minimal Windows WGL test: opens a window, renders a known color, checks pixels. */
typedef unsigned int U;typedef int I;typedef unsigned long long SZ;typedef void* P;
__declspec(dllimport) P GetStdHandle(U);
__declspec(dllimport) I WriteFile(P,const void*,U,U*,P);
__declspec(dllimport) void ExitProcess(U);
__declspec(dllimport) void Sleep(U);
__declspec(dllimport) P CreateWindowExA(U,const char*,const char*,U,I,I,I,I,P,P,P,P);
__declspec(dllimport) P GetDC(P);
__declspec(dllimport) I ReleaseDC(P,P);
__declspec(dllimport) I DestroyWindow(P);
__declspec(dllimport) I UpdateWindow(P);
struct PFD {unsigned short size,version;U flags;unsigned char type,color,rb,rs,gb,gs,bb,bs,ab,as,acc,ar,ag,abl,aa,depth,stencil,aux,layer,res;U lm,vm,dm;};
__declspec(dllimport) I ChoosePixelFormat(P,const struct PFD*);
__declspec(dllimport) I SetPixelFormat(P,I,const struct PFD*);
__declspec(dllimport) I SwapBuffers(P);
__declspec(dllimport) P wglCreateContext(P);
__declspec(dllimport) I wglMakeCurrent(P,P);
__declspec(dllimport) I wglDeleteContext(P);
__declspec(dllimport) const char* glGetString(U);
__declspec(dllimport) void glClearColor(float,float,float,float);
__declspec(dllimport) void glClear(U);
__declspec(dllimport) void glReadPixels(I,I,I,I,U,U,P);
__declspec(dllimport) U glGetError(void);
static U len(const char*s){U n=0;while(s&&s[n])++n;return n;}
static void out(const char*s){U n;WriteFile(GetStdHandle((U)-11),s,len(s),&n,0);}
static I has(const char*s,const char*t){for(;s&&*s;++s){U j=0;while(t[j]&&s[j]==t[j])++j;if(!t[j])return 1;}return 0;}
static void ck(const char*s,I ok){if(!ok){out("FAIL ");out(s);out("\r\n");ExitProcess(1);}}
static struct PFD pfd={40,1,0x25,0,32,0,0,0,0,0,0,8,0,0,0,0,0,0,24,8,0,0,0,0,0,0};
void mainCRTStartup(void){
 P window=CreateWindowExA(0,"STATIC","CrealityScan graphics diagnostic",0x10CF0000,100,100,480,300,0,0,0,0);ck("CreateWindow",window!=0);
 P dc=GetDC(window);I format=ChoosePixelFormat(dc,&pfd);ck("pixel format",format!=0);ck("SetPixelFormat",SetPixelFormat(dc,format,&pfd));
 P context=wglCreateContext(dc);ck("OpenGL context",context!=0);ck("wglMakeCurrent",wglMakeCurrent(dc,context));
 const char*renderer=glGetString(0x1F01);out("GL_RENDERER=");out(renderer);out("\r\nGL_VERSION=");out(glGetString(0x1F02));out("\r\nGL_VENDOR=");out(glGetString(0x1F00));out("\r\n");
 char wanted[256];ck("configured GPU name",GetEnvironmentVariableA("CREALITY_GPU_NAME",wanted,sizeof(wanted))>0);
 ck("configured GPU renderer",has(renderer,wanted));glClearColor(0.25f,0.5f,0.75f,1.0f);glClear(0x4000);
 unsigned char pixel[4];glReadPixels(1,1,1,1,0x1908,0x1401,pixel);ck("OpenGL error",!glGetError());
 ck("rendered pixel",pixel[0]>=63&&pixel[0]<=65&&pixel[1]>=127&&pixel[1]<=129&&pixel[2]>=190&&pixel[2]<=192);
 SwapBuffers(dc);UpdateWindow(window);Sleep(2000);wglMakeCurrent(0,0);wglDeleteContext(context);ReleaseDC(window,dc);DestroyWindow(window);
 out("PASS: Windows OpenGL on configured GPU; rendered pixel checked.\r\n");ExitProcess(0);
}

int _fltused=0;
