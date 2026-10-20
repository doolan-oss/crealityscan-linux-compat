/* Single explicitly selected Pika GREY endpoint. Never scans /dev or resets
 * USB. Hardware mode requires --allow-hardware and verifies VID/PID via sysfs
 * before opening. Synthetic mode is a transport fixture and makes no device
 * syscalls.
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/videodev2.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>
#include <libyuv/convert.h>
#include <libyuv/convert_argb.h>
#include <libyuv/convert_from_argb.h>
#include <sys/wait.h>
#include <netinet/tcp.h>
#include <sys/file.h>
#define BYTES (1280 * 960)
struct metadata_capture { int fd,streaming; void *maps[4]; size_t lengths[4]; unsigned count; uint32_t pending_sequence; unsigned pending_length; unsigned char pending[256]; };
struct capture {
  struct metadata_capture meta;
  int fd, streaming;
  void *maps[4];
  size_t lengths[4];
  unsigned count;
  uint32_t sequence;
  unsigned frame_bytes;
  int compressed;
  struct v4l2_format previous_format;
  struct v4l2_streamparm previous_rate;
  int have_format, have_rate;
};
static volatile sig_atomic_t stopping;
static int cleanup_failed;
static void stop_handler(int sig) { (void)sig; stopping = 1; }
static int xioctl(int fd, unsigned long req, void *arg) {
  int r;
  do {
    r = ioctl(fd, req, arg);
  } while (r < 0 && errno == EINTR);
  if (r < 0)
    fprintf(stderr, "V4L2 ioctl 0x%lx failed: errno=%d %s\n", req, errno, strerror(errno));
  return r;
}
static int all(int fd, void *data, size_t n, int sending) {
  char *p = data;
  while (n && !stopping) {
    ssize_t r = sending ? send(fd, p, n, MSG_NOSIGNAL) : recv(fd, p, n, 0);
    if (r < 0 && errno == EINTR)
      continue;
    if (r <= 0)
      return -1;
    p += r;
    n -= r;
  }
  return n ? -1 : 0;
}
static int pika_node(const char *node) {
  const char *name = strrchr(node, '/');
  if (!name || strncmp(node, "/dev/video", 10))
    return 0;
  name++;
  for (const char *p = name + 5; *p; p++)
    if (*p < '0' || *p > '9')
      return 0;
  char path[PATH_MAX], resolved[PATH_MAX], file[PATH_MAX], s[32];
  snprintf(path, sizeof(path), "/sys/class/video4linux/%s/device", name);
  if (!realpath(path, resolved))
    return 0;
  for (;;) {
    if (snprintf(file, sizeof(file), "%s/idVendor", resolved) >=
        (int)sizeof(file))
      return 0;
    FILE *f = fopen(file, "r");
    if (f) {
      int ok = fgets(s, sizeof(s), f) && strtoul(s, NULL, 16) == 0x2bc5;
      fclose(f);
      if (!ok)
        return 0;
      if (snprintf(file, sizeof(file), "%s/idProduct", resolved) >=
          (int)sizeof(file))
        return 0;
      f = fopen(file, "r");
      if (!f)
        return 0;
      ok = fgets(s, sizeof(s), f) && strtoul(s, NULL, 16) == 0x0c0b;
      fclose(f);
      return ok;
    }
    char *slash = strrchr(resolved, '/');
    if (!slash || slash == resolved)
      return 0;
    *slash = 0;
  }
}
static int metadata_open(struct metadata_capture *m,const char *node) {
  if(!node||!pika_node(node))return -1;
  m->fd=open(node,O_RDWR|O_NONBLOCK|O_CLOEXEC|O_NOFOLLOW);if(m->fd<0)return -1;
  struct v4l2_format fmt={.type=V4L2_BUF_TYPE_META_CAPTURE};
  if(xioctl(m->fd,VIDIOC_G_FMT,&fmt)||fmt.fmt.meta.dataformat!=V4L2_META_FMT_UVC)return -1;
  struct v4l2_requestbuffers req={.count=4,.type=V4L2_BUF_TYPE_META_CAPTURE,.memory=V4L2_MEMORY_MMAP};
  if(xioctl(m->fd,VIDIOC_REQBUFS,&req)||!req.count||req.count>4)return -1;
  m->count=req.count;
  for(unsigned i=0;i<req.count;i++){
    struct v4l2_buffer b={.type=req.type,.memory=req.memory,.index=i};
    if(xioctl(m->fd,VIDIOC_QUERYBUF,&b))return -1;
    m->lengths[i]=b.length;m->maps[i]=mmap(NULL,b.length,PROT_READ|PROT_WRITE,MAP_SHARED,m->fd,b.m.offset);
    if(m->maps[i]==MAP_FAILED||xioctl(m->fd,VIDIOC_QBUF,&b))return -1;
  }
  enum v4l2_buf_type type=V4L2_BUF_TYPE_META_CAPTURE;
  if(xioctl(m->fd,VIDIOC_STREAMON,&type))return -1;
  m->streaming=1;fprintf(stderr,"METADATA STREAMON %s\n",node);return 0;
}
static void metadata_close(struct metadata_capture *m){
  if(m->fd<0)return;
  enum v4l2_buf_type type=V4L2_BUF_TYPE_META_CAPTURE;
  if(m->streaming&&xioctl(m->fd,VIDIOC_STREAMOFF,&type))cleanup_failed=1;
  for(unsigned i=0;i<m->count;i++)if(m->maps[i]&&m->maps[i]!=MAP_FAILED)munmap(m->maps[i],m->lengths[i]);
  struct v4l2_requestbuffers req={.type=type,.memory=V4L2_MEMORY_MMAP};
  if(xioctl(m->fd,VIDIOC_REQBUFS,&req))cleanup_failed=1;
  close(m->fd);m->fd=-1;
}
static unsigned metadata_frame(struct metadata_capture *m,uint32_t sequence,unsigned char *uvc){
  if(m->pending_length){
    if(m->pending_sequence==sequence){unsigned n=m->pending_length;memcpy(uvc,m->pending,n);m->pending_length=0;return n;}
    if(m->pending_sequence>sequence)return 0;
    m->pending_length=0;
  }
  for(unsigned attempt=0;attempt<8&&!stopping;attempt++){
    struct pollfd p={.fd=m->fd,.events=POLLIN};
    if(poll(&p,1,200)<=0)return 0;
    struct v4l2_buffer b={.type=V4L2_BUF_TYPE_META_CAPTURE,.memory=V4L2_MEMORY_MMAP};
    if(xioctl(m->fd,VIDIOC_DQBUF,&b))return 0;
    unsigned length=0;
    if(b.index<m->count&&b.bytesused<=m->lengths[b.index]&&b.sequence>=sequence){
      const unsigned char *data=m->maps[b.index];
      for(unsigned pos=0;pos+12<=b.bytesused;){
        unsigned n=data[pos+10];if(n<2||pos+10+n>b.bytesused)break;
        if(n>=12&&(data[pos+11]&0x0c)==0x0c){memcpy(uvc,data+pos+10,n);length=n;if(n>12)break;}
        pos+=10+n;
      }
      if(sequence<5)fprintf(stderr,"UVC metadata sequence=%u bytes=%u header=%u flags=%02x\n",sequence,b.bytesused,length,length?uvc[1]:0);
    }
    uint32_t meta_sequence=b.sequence;
    if(xioctl(m->fd,VIDIOC_QBUF,&b))return 0;
    if(meta_sequence==sequence)return length;
    if(meta_sequence>sequence){m->pending_sequence=meta_sequence;m->pending_length=length;memcpy(m->pending,uvc,length);return 0;}
  }
  return 0;
}
static void capture_close(struct capture *c) {
  if (c->fd < 0)
    return;
  if (c->streaming) {
    enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if (xioctl(c->fd, VIDIOC_STREAMOFF, &type)) cleanup_failed = 1;
  }
  metadata_close(&c->meta);
  for (unsigned i = 0; i < c->count; i++)
    if (c->maps[i] && c->maps[i] != MAP_FAILED)
      munmap(c->maps[i], c->lengths[i]);
  struct v4l2_requestbuffers req = {0};
  req.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
  req.memory = V4L2_MEMORY_MMAP;
  if (xioctl(c->fd, VIDIOC_REQBUFS, &req)) cleanup_failed = 1;
  if (c->have_format && xioctl(c->fd, VIDIOC_S_FMT, &c->previous_format)) cleanup_failed = 1;
  if (c->have_rate && xioctl(c->fd, VIDIOC_S_PARM, &c->previous_rate)) cleanup_failed = 1;
  fprintf(stderr, "CLOSED: stream stopped, buffers released, prior format/rate restored (any ioctl error fails cleanup)\n");
  close(c->fd);
  c->fd = -1;
}
static int capture_open(struct capture *c, const char *node, const char *metanode, uint32_t fourcc, unsigned fps) {
  memset(c, 0, sizeof(*c));
  c->fd = -1;c->meta.fd=-1;
  if (!pika_node(node)) {
    fprintf(stderr, "Refused non-Pika or unverified node\n");
    return -1;
  }
  c->fd = open(node, O_RDWR | O_NONBLOCK | O_CLOEXEC | O_NOFOLLOW);
  if (c->fd < 0) { perror("open video device"); return -1; }
  fprintf(stderr, "OPEN %s verified Pika 2bc5:0c0b\n", node);
  struct v4l2_capability cap = {0};
  if (xioctl(c->fd, VIDIOC_QUERYCAP, &cap) < 0)
    return -1;
  uint32_t caps = cap.capabilities & V4L2_CAP_DEVICE_CAPS ? cap.device_caps
                                                          : cap.capabilities;
  if (!(caps & V4L2_CAP_VIDEO_CAPTURE) || !(caps & V4L2_CAP_STREAMING))
    return -1;
  c->previous_format.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
  c->previous_rate.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
  c->have_format = !xioctl(c->fd, VIDIOC_G_FMT, &c->previous_format);
  c->have_rate = !xioctl(c->fd, VIDIOC_G_PARM, &c->previous_rate);
  if (!c->have_format || !c->have_rate) return -1;
  struct v4l2_format fmt = {0};
  fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
  fmt.fmt.pix.width = 1280;
  fmt.fmt.pix.height = 960;
  fmt.fmt.pix.pixelformat = fourcc;
  fmt.fmt.pix.field = V4L2_FIELD_NONE;
  if (xioctl(c->fd, VIDIOC_S_FMT, &fmt) < 0) return -1;
  fprintf(stderr, "NEGOTIATED: %ux%u fourcc=%.4s stride=%u size=%u\n",
          fmt.fmt.pix.width, fmt.fmt.pix.height, (char *)&fmt.fmt.pix.pixelformat,
          fmt.fmt.pix.bytesperline, fmt.fmt.pix.sizeimage);
  c->compressed = fourcc == V4L2_PIX_FMT_MJPEG;
  c->frame_bytes = BYTES * (fourcc == V4L2_PIX_FMT_YUYV ? 2 : 1);
  if (fmt.fmt.pix.width != 1280 || fmt.fmt.pix.height != 960 ||
      fmt.fmt.pix.pixelformat != fourcc || fmt.fmt.pix.sizeimage > BYTES * 3 ||
      (!c->compressed && fmt.fmt.pix.bytesperline != (unsigned)(1280 * (fourcc == V4L2_PIX_FMT_YUYV ? 2 : 1)))) {
    fprintf(stderr, "Unsupported negotiated format\n"); return -1;
  }
  struct v4l2_streamparm sp = {0};
  sp.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
  sp.parm.capture.timeperframe.numerator = 1;
  sp.parm.capture.timeperframe.denominator = fps;
  if (xioctl(c->fd, VIDIOC_S_PARM, &sp) < 0 ||
      sp.parm.capture.timeperframe.numerator != 1 ||
      sp.parm.capture.timeperframe.denominator != fps)
    return -1;
  struct v4l2_requestbuffers req = {0};
  req.count = 4;
  req.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
  req.memory = V4L2_MEMORY_MMAP;
  if (xioctl(c->fd, VIDIOC_REQBUFS, &req) < 0 || !req.count || req.count > 4)
    return -1;
  c->count = req.count;
  for (unsigned i = 0; i < c->count; i++) {
    struct v4l2_buffer b = {0};
    b.type = req.type;
    b.memory = req.memory;
    b.index = i;
    if (xioctl(c->fd, VIDIOC_QUERYBUF, &b) < 0)
      return -1;
    c->lengths[i] = b.length;
    c->maps[i] = mmap(NULL, b.length, PROT_READ | PROT_WRITE, MAP_SHARED, c->fd,
                      b.m.offset);
    if (c->maps[i] == MAP_FAILED || xioctl(c->fd, VIDIOC_QBUF, &b) < 0)
      return -1;
  }
  if(metadata_open(&c->meta,metanode))return -1;
  enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
  if (xioctl(c->fd, VIDIOC_STREAMON, &type) < 0)
    return -1;
  fprintf(stderr, "STREAMON: %s 1280x960 %.4s %ufps raw physical buffers\n", node, (char *)&fourcc, fps);
  c->streaming = 1;
  return 0;
}
static int capture_frame(struct capture *c, unsigned char *out, uint32_t *header, unsigned char *meta) {
  struct pollfd p = {.fd = c->fd, .events = POLLIN};
  int r;
  do {
    r = poll(&p, 1, 2000);
  } while (r < 0 && errno == EINTR && !stopping);
  if (r <= 0 || !(p.revents & POLLIN)) {
    fprintf(stderr, "CAPTURE FAILED: poll=%d revents=0x%x after maximum 2000ms; errno=%d\n", r, p.revents, r < 0 ? errno : 0);
    return -1;
  }
  struct v4l2_buffer b = {0};
  b.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
  b.memory = V4L2_MEMORY_MMAP;
  if (xioctl(c->fd, VIDIOC_DQBUF, &b) < 0)
    return -1;
  if (b.sequence < 5 || !(b.sequence % 120)) fprintf(stderr, "DQBUF: sequence=%u bytes=%u flags=0x%x timestamp=%ld.%06ld\n",
          b.sequence, b.bytesused, b.flags, (long)b.timestamp.tv_sec, (long)b.timestamp.tv_usec);
  int ok = b.index < c->count && (c->compressed ? b.bytesused > 0 && b.bytesused <= BYTES * 3 : b.bytesused == c->frame_bytes) &&
           b.bytesused <= c->lengths[b.index] &&
           !(b.flags & V4L2_BUF_FLAG_ERROR);
  if (ok) {
    memcpy(out, c->maps[b.index], b.bytesused);
    uint64_t us = (uint64_t)b.timestamp.tv_sec * 1000000 + b.timestamp.tv_usec;
    header[1] = b.bytesused; header[2] = b.sequence; header[3] = b.flags;
    header[4] = us; header[5] = us >> 32;
  }
  if (xioctl(c->fd, VIDIOC_QBUF, &b) < 0)
    return -1;
  if(ok)header[6]=metadata_frame(&c->meta,header[2],meta);
  return ok ? 0 : -1;
}

/* Authenticated private protocol v1. Setup: token[64], magic/endpoint/fourcc/fps
 * uint32 little endian. Reply errno uint32. 'N': header[8] then raw payload.
 * Header = errno, length, native sequence, flags, monotonic usec lo/hi, 0, 0.
 * 'S': stop, restore original format/rate, reply errno and close connection.
 * Both camera endpoints can stream concurrently in separate child processes.
 */
static void client(int sock, const char **nodes) {
  char token[64], expected[64] = {0}; uint32_t req[4], status = 0;
  const char *secret = getenv("PIKA_CAMERA_TOKEN");
  if (!secret || strlen(secret) >= sizeof(expected)) return;
  strcpy(expected, secret);
  if (all(sock, token, 64, 0) || memcmp(token, expected, 64) || all(sock, req, sizeof(req), 0)) return;
  if (req[0] != 0x314b4950 || req[1] > 1 ||
      (req[2] != V4L2_PIX_FMT_MJPEG && req[2] != (req[1] ? V4L2_PIX_FMT_YUYV : V4L2_PIX_FMT_GREY) && !(req[1] && (req[2] == V4L2_PIX_FMT_NV12 || req[2] == V4L2_PIX_FMT_BGR24))) ||
      !req[3] || req[3] > (req[1] ? 60 : 120)) return;
  char lockname[32]; snprintf(lockname, sizeof(lockname), "frame-endpoint-%u.lock", req[1]);
  int lockfd = open(lockname, O_CREAT | O_RDWR | O_CLOEXEC | O_NOFOLLOW, 0600);
  if (lockfd < 0 || flock(lockfd, LOCK_EX | LOCK_NB)) {
    status = EBUSY; all(sock, &status, 4, 1); if (lockfd >= 0) close(lockfd); return;
  }
  int convert_nv12=req[1]&&req[2]==V4L2_PIX_FMT_NV12;
  int convert_rgb=req[1]&&req[2]==V4L2_PIX_FMT_BGR24;
  int convert_color=convert_nv12||convert_rgb;
  struct capture c = {.fd = -1};
  if (capture_open(&c, nodes[req[1]], getenv(req[1]?"PIKA_METADATA_1":"PIKA_METADATA_0"), convert_color?V4L2_PIX_FMT_MJPEG:req[2], req[3])) status = errno ? errno : EIO;
  if (!all(sock, &status, 4, 1) && !status) {
    unsigned char *pixels = malloc(BYTES * 3);
    unsigned char *converted = convert_color?malloc(BYTES*3):NULL;
    unsigned char *argb = convert_rgb?malloc(BYTES*4):NULL;
    if(convert_rgb)fprintf(stderr,"COLOR CONVERSION: real MJPEG decoded to BGR24; original UVC metadata preserved\n");
    if(convert_nv12)fprintf(stderr,"COLOR CONVERSION: real MJPEG decoded to NV12; original UVC metadata preserved\n");
    char op;
    while (pixels && (!convert_color||converted)&&(!convert_rgb||argb) && !stopping && !all(sock, &op, 1, 0)) {
      if (op == 'S') {
        capture_close(&c); status = cleanup_failed ? EIO : 0;
        all(sock, &status, 4, 1); break;
      }
      if (op != 'N') break;
      uint32_t h[8] = {0};unsigned char meta[256]={0};
      for(unsigned skipped=0;skipped<8;skipped++){
        if(capture_frame(&c,pixels,h,meta)){h[0]=errno?errno:EIO;break;}
        if(h[6])break;
      }
      if(!h[0]&&!h[6]){h[0]=ENODATA;fprintf(stderr,"No paired UVC metadata after 8 frames\n");}
      unsigned char *output=pixels;
      if(!h[0]&&convert_color){
        int width=0,height=0;
        if(MJPGSize(pixels,h[1],&width,&height)||width!=1280||height!=960||
           (convert_rgb?(MJPGToARGB(pixels,h[1],argb,1280*4,1280,960,1280,960)||ARGBToRGB24(argb,1280*4,converted,1280*3,1280,960)):MJPGToNV12(pixels,h[1],converted,1280,converted+BYTES,1280,1280,960,1280,960))){
          h[0]=EILSEQ;fprintf(stderr,"MJPEG color conversion failed\n");
        }else {h[1]=convert_rgb?BYTES*3:BYTES*3/2;output=converted;}
      }
      if (all(sock, h, sizeof(h), 1) || h[0] || all(sock, output, h[1], 1) || all(sock,meta,h[6],1)) break;
    }
    free(argb);free(converted);free(pixels);
  }
  capture_close(&c); close(lockfd);
}
int main(int argc, char **argv) {
  if (argc != 3 || !pika_node(argv[1]) || !pika_node(argv[2])) return 2;
  const char *port = getenv("PIKA_CAMERA_PORT"); char *end;
  long number = port ? strtol(port, &end, 10) : 0;
  if (!number || *end || number < 1024 || number > 65535) return 2;
  struct sigaction sa = {.sa_handler = stop_handler};
  sigaction(SIGTERM, &sa, NULL); sigaction(SIGINT, &sa, NULL); signal(SIGPIPE, SIG_IGN);
  int listener = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0), yes = 1;
  if (listener < 0) return 2;
  setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
  struct sockaddr_in a = {.sin_family = AF_INET, .sin_port = htons(number), .sin_addr.s_addr = htonl(INADDR_LOOPBACK)};
  if (bind(listener, (void *)&a, sizeof(a)) || listen(listener, 2)) return 2;
  pid_t children[8] = {0};
  puts("READY private Pika raw frame service v1"); fflush(stdout);
  while (!stopping) {
    for (unsigned i = 0; i < 8; i++) if (children[i]) {
      int status; if (waitpid(children[i], &status, WNOHANG) > 0) { if (status) cleanup_failed = 1; children[i] = 0; }
    }
    struct pollfd p = {.fd = listener, .events = POLLIN};
    if (poll(&p, 1, 100) <= 0) continue;
    int sock = accept4(listener, NULL, NULL, SOCK_CLOEXEC); if (sock < 0) continue;
    setsockopt(sock,IPPROTO_TCP,TCP_NODELAY,&yes,sizeof(yes));
    struct timeval timeout = {.tv_sec = 4};
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
    unsigned i; for (i = 0; i < 8 && children[i]; i++);
    if (i == 8) { close(sock); continue; }
    pid_t pid = fork();
    if (!pid) { close(listener); cleanup_failed = 0; client(sock, (const char **)&argv[1]); close(sock); _exit(cleanup_failed ? 3 : 0); }
    if (pid > 0) children[i] = pid;
    close(sock);
  }
  close(listener);
  for (unsigned i = 0; i < 8; i++) if (children[i]) kill(children[i], SIGTERM);
  for (unsigned i = 0; i < 8; i++) if (children[i]) { int status; waitpid(children[i], &status, 0); if (status) cleanup_failed = 1; }
  return cleanup_failed ? 3 : 0;
}
