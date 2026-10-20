/* Native Linux V4L2 recorder. Only libc; no Wine, SDK or image processing.
 * Invoked by recorder.py after identity, lock and ownership checks.
 * Raw metadata is retained independently, paired offline by V4L2 sequence.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <linux/videodev2.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/statvfs.h>
#include <time.h>
#include <unistd.h>

#define NBUF 8
struct endpoint {
    int fd, streaming, allocated, have_format, have_rate;
    enum v4l2_buf_type type;
    struct v4l2_format old_format;
    struct v4l2_streamparm old_rate;
    void *maps[NBUF]; size_t lengths[NBUF]; unsigned count;
    FILE *data, *index;
    uint64_t bytes, frames;
    const char *name;
};
static volatile sig_atomic_t stopped;
static int cleanup_errors;
static void stop(int sig) { stopped=sig; }
static uint64_t now(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t);
    return (uint64_t)t.tv_sec*1000000000+t.tv_nsec;
}
static int xi(int fd,unsigned long req,void *arg) {
    int r; do {r=ioctl(fd,req,arg);} while(r<0 && errno==EINTR);
    if(r<0) fprintf(stderr,"ioctl %lx: %s\n",req,strerror(errno));
    return r;
}
static int open_stream(struct endpoint *e,const char *node,int meta,unsigned fps,int color) {
    e->type=meta?V4L2_BUF_TYPE_META_CAPTURE:V4L2_BUF_TYPE_VIDEO_CAPTURE;
    e->fd=open(node,O_RDWR|O_NONBLOCK|O_CLOEXEC|O_NOFOLLOW);
    if(e->fd<0) {perror(node);return -1;}
    struct v4l2_capability cap={0};
    if(xi(e->fd,VIDIOC_QUERYCAP,&cap))return -1;
    unsigned caps=(cap.capabilities&V4L2_CAP_DEVICE_CAPS)?cap.device_caps:cap.capabilities;
    if(!(caps&V4L2_CAP_STREAMING)||!(caps&(meta?V4L2_CAP_META_CAPTURE:V4L2_CAP_VIDEO_CAPTURE)))return -1;
    e->old_format.type=e->type;
    if(xi(e->fd,VIDIOC_G_FMT,&e->old_format))return -1;
    if(meta) {
        if(e->old_format.fmt.meta.dataformat!=V4L2_META_FMT_UVC)return -1;
    } else {
        e->old_rate.type=e->type;
        if(xi(e->fd,VIDIOC_G_PARM,&e->old_rate))return -1;
        e->have_format=e->have_rate=1;
        struct v4l2_format fmt={.type=e->type};
        fmt.fmt.pix.width=1280;fmt.fmt.pix.height=960;
        fmt.fmt.pix.pixelformat=color?V4L2_PIX_FMT_MJPEG:V4L2_PIX_FMT_GREY;
        fmt.fmt.pix.field=V4L2_FIELD_NONE;
        if(xi(e->fd,VIDIOC_S_FMT,&fmt))return -1;
        if(fmt.fmt.pix.width!=1280||fmt.fmt.pix.height!=960||
           fmt.fmt.pix.pixelformat!=(color?V4L2_PIX_FMT_MJPEG:V4L2_PIX_FMT_GREY)||
           (!color&&fmt.fmt.pix.bytesperline!=1280))return -1;
        struct v4l2_streamparm rate={.type=e->type};
        rate.parm.capture.timeperframe.numerator=1;
        rate.parm.capture.timeperframe.denominator=fps;
        if(xi(e->fd,VIDIOC_S_PARM,&rate))return -1;
        if(rate.parm.capture.timeperframe.numerator!=1||rate.parm.capture.timeperframe.denominator!=fps)return -1;
        fprintf(stderr,"%s negotiated 1280x960 %.4s %u fps\n",e->name,(char*)&fmt.fmt.pix.pixelformat,fps);
    }
    struct v4l2_requestbuffers req={.type=e->type,.memory=V4L2_MEMORY_MMAP,.count=NBUF};
    if(xi(e->fd,VIDIOC_REQBUFS,&req))return -1;
    e->allocated=1;
    if(!req.count||req.count>NBUF)return -1;
    e->count=req.count;
    for(unsigned i=0;i<e->count;i++) {
        struct v4l2_buffer b={.type=e->type,.memory=V4L2_MEMORY_MMAP,.index=i};
        if(xi(e->fd,VIDIOC_QUERYBUF,&b))return -1;
        e->lengths[i]=b.length;
        e->maps[i]=mmap(NULL,b.length,PROT_READ|PROT_WRITE,MAP_SHARED,e->fd,b.m.offset);
        if(e->maps[i]==MAP_FAILED||xi(e->fd,VIDIOC_QBUF,&b))return -1;
    }
    if(xi(e->fd,VIDIOC_STREAMON,&e->type))return -1;
    e->streaming=1;
    return 0;
}
static void close_stream(struct endpoint *e) {
    if(e->fd>=0) {
        if(e->streaming&&xi(e->fd,VIDIOC_STREAMOFF,&e->type))cleanup_errors++;
        for(unsigned i=0;i<e->count;i++)
            if(e->maps[i]&&e->maps[i]!=MAP_FAILED&&munmap(e->maps[i],e->lengths[i]))cleanup_errors++;
        struct v4l2_requestbuffers req={.type=e->type,.memory=V4L2_MEMORY_MMAP};
        if(e->allocated&&xi(e->fd,VIDIOC_REQBUFS,&req))cleanup_errors++;
        struct v4l2_format restore_format=e->old_format;
        struct v4l2_streamparm restore_rate=e->old_rate;
        if(e->have_format&&xi(e->fd,VIDIOC_S_FMT,&restore_format))cleanup_errors++;
        if(e->have_rate&&xi(e->fd,VIDIOC_S_PARM,&restore_rate))cleanup_errors++;
        if(e->have_format) {
            struct v4l2_format f={.type=e->type};
            if(xi(e->fd,VIDIOC_G_FMT,&f)||f.fmt.pix.width!=e->old_format.fmt.pix.width||
               f.fmt.pix.height!=e->old_format.fmt.pix.height||
               f.fmt.pix.pixelformat!=e->old_format.fmt.pix.pixelformat)cleanup_errors++;
        }
        if(e->have_rate) {
            struct v4l2_streamparm p={.type=e->type};
            if(xi(e->fd,VIDIOC_G_PARM,&p)||
               p.parm.capture.timeperframe.numerator!=e->old_rate.parm.capture.timeperframe.numerator||
               p.parm.capture.timeperframe.denominator!=e->old_rate.parm.capture.timeperframe.denominator)cleanup_errors++;
        }
        if(close(e->fd))cleanup_errors++;
    }
    if(e->data && (fflush(e->data)||ferror(e->data)||fsync(fileno(e->data))))cleanup_errors++;
    if(e->data&&fclose(e->data))cleanup_errors++;
    if(e->index && (fflush(e->index)||ferror(e->index)||fsync(fileno(e->index))))cleanup_errors++;
    if(e->index&&fclose(e->index))cleanup_errors++;
    fprintf(stderr,"%s: frames=%"PRIu64" bytes=%"PRIu64" cleanup_errors=%d\n",e->name,e->frames,e->bytes,cleanup_errors);
}
static int drain_one(struct endpoint *e) {
    struct v4l2_buffer b={.type=e->type,.memory=V4L2_MEMORY_MMAP};
    if(ioctl(e->fd,VIDIOC_DQBUF,&b)<0) {
        if(errno==EAGAIN||errno==EINTR)return 0;
        perror("DQBUF");return -1;
    }
    uint64_t received=now();
    if(b.index>=e->count||b.bytesused>e->lengths[b.index])return -1;
    int ok=fwrite(e->maps[b.index],1,b.bytesused,e->data)==b.bytesused;
    if(fprintf(e->index,"{\"sequence\":%u,\"offset\":%"PRIu64",\"length\":%u,\"flags\":%u,\"v4l2_us\":%"PRIu64",\"received_monotonic_ns\":%"PRIu64"}\n",
       b.sequence,e->bytes,b.bytesused,b.flags,(uint64_t)b.timestamp.tv_sec*1000000+b.timestamp.tv_usec,received)<0)ok=0;
    e->bytes+=b.bytesused;e->frames++;
    if(xi(e->fd,VIDIOC_QBUF,&b))return -1;
    return ok?1:-1;
}
int main(int argc,char **argv) {
    if(argc!=9) {fprintf(stderr,"Internal helper: use record-pika.sh\n");return 2;}
    /* output, seconds, IR fps, IR node, IR metadata, colour node or -, colour metadata, colour fps */
    char *end; double seconds=strtod(argv[2],&end);
    if(*end||!(seconds>=0.2&&seconds<=30))return 2;
    unsigned fps=strtoul(argv[3],&end,10);if(*end||fps<10||fps>120)return 2;
    unsigned rgbfps=strtoul(argv[8],&end,10);if(*end||rgbfps<5||rgbfps>60)return 2;
    int count=strcmp(argv[6],"-")?4:2,result=1;
    struct endpoint ep[4]={{.fd=-1,.name="ir-meta"},{.fd=-1,.name="ir"},{.fd=-1,.name="color-meta"},{.fd=-1,.name="color"}};
    const char *nodes[]={argv[5],argv[4],argv[7],argv[6]};
    struct sigaction action={.sa_handler=stop};sigemptyset(&action.sa_mask);
    sigaction(SIGINT,&action,NULL);sigaction(SIGTERM,&action,NULL);sigaction(SIGHUP,&action,NULL);
    if(chdir(argv[1])) {perror("output directory");return 2;}
    FILE *maps=fopen("native-process-maps.txt","wx");FILE *src=fopen("/proc/self/maps","r");
    if(!maps||!src)return 2;
    char line[4096];while(fgets(line,sizeof(line),src))fputs(line,maps);fclose(src);fclose(maps);
    for(int i=0;i<count;i++) {
        char filename[64];snprintf(filename,sizeof(filename),"%s.bin",ep[i].name);
        ep[i].data=fopen(filename,"wbx");snprintf(filename,sizeof(filename),"%s.jsonl",ep[i].name);
        ep[i].index=fopen(filename,"wx");
        if(!ep[i].data||!ep[i].index)goto done;
        if(stopped||open_stream(&ep[i],nodes[i],!(i%2),i<2?fps:rgbfps,i>=2))goto done;
    }
    uint64_t start=now(),deadline=start+(uint64_t)(seconds*1e9),last_space=start;
    while(!stopped&&now()<deadline) {
        struct pollfd p[4];for(int i=0;i<count;i++)p[i]=(struct pollfd){.fd=ep[i].fd,.events=POLLIN};
        int r=poll(p,count,100);
        if(r<0) {if(errno==EINTR)continue;perror("poll");goto done;}
        for(int i=0;i<count;i++) {
            if(p[i].revents&(POLLERR|POLLHUP|POLLNVAL)){fprintf(stderr,"%s poll error %x\n",ep[i].name,p[i].revents);goto done;}
            if(p[i].revents&POLLIN)if(drain_one(&ep[i])<0)goto done;
        }
        if(now()-last_space>1000000000) {
            struct statvfs fs;
            if(statvfs(".",&fs)||(uint64_t)fs.f_bavail*fs.f_frsize<1024ULL*1024*1024) {
                fprintf(stderr,"Insufficient free space\n");goto done;
            }
            last_space=now();
        }
    }
    result=stopped?128+stopped:0;
    for(int i=0;i<count;i++)if(!ep[i].frames) {fprintf(stderr,"No buffers: %s\n",ep[i].name);result=1;}
 done:
    /* Stop video before its metadata endpoint. */
    for(int i=count-1;i>=0;i--)close_stream(&ep[i]);
    return cleanup_errors?3:result;
}
