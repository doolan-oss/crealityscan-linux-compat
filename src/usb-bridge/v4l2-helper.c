/* Single explicitly selected Pika GREY endpoint. Never scans /dev or resets
 * USB. Hardware mode requires --allow-hardware and verifies VID/PID via sysfs
 * (scanner-node.h) before opening. Synthetic mode is a transport fixture and makes no device
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
#include "scanner-profile.h"
#include "scanner-node.h"
#define BYTES (1280 * 960)
struct capture {
  int fd, streaming;
  void *maps[4];
  size_t lengths[4];
  unsigned count;
  uint32_t sequence;
  unsigned frame_bytes;
  int yuyv;
  struct v4l2_format previous_format;
  struct v4l2_streamparm previous_rate;
  int have_format, have_rate;
};
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
  while (n) {
    ssize_t r = sending ? send(fd, p, n, MSG_NOSIGNAL) : recv(fd, p, n, 0);
    if (r < 0 && errno == EINTR)
      continue;
    if (r <= 0)
      return -1;
    p += r;
    n -= r;
  }
  return 0;
}
static void capture_close(struct capture *c) {
  if (c->fd < 0)
    return;
  if (c->streaming) {
    enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    xioctl(c->fd, VIDIOC_STREAMOFF, &type);
  }
  for (unsigned i = 0; i < c->count; i++)
    if (c->maps[i] && c->maps[i] != MAP_FAILED)
      munmap(c->maps[i], c->lengths[i]);
  struct v4l2_requestbuffers req = {0};
  req.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
  req.memory = V4L2_MEMORY_MMAP;
  xioctl(c->fd, VIDIOC_REQBUFS, &req);
  if (c->have_format) xioctl(c->fd, VIDIOC_S_FMT, &c->previous_format);
  if (c->have_rate) xioctl(c->fd, VIDIOC_S_PARM, &c->previous_rate);
  fprintf(stderr, "CLOSED: stream stopped, buffers released, prior format/rate restoration requested\n");
  close(c->fd);
  c->fd = -1;
}
static int capture_open(struct capture *c, const char *node) {
  memset(c, 0, sizeof(*c));
  c->fd = -1;
  if (!scanner_node(node)) {
    fprintf(stderr, "Refused node not belonging to scanner 2bc5:%04x\n", scanner_pid());
    return -1;
  }
  c->fd = open(node, O_RDWR | O_NONBLOCK | O_CLOEXEC | O_NOFOLLOW);
  if (c->fd < 0) { perror("open video device"); return -1; }
  fprintf(stderr, "OPEN %s verified scanner 2bc5:%04x\n", node, scanner_pid());
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
  fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_GREY;
  fmt.fmt.pix.field = V4L2_FIELD_NONE;
  if (xioctl(c->fd, VIDIOC_S_FMT, &fmt) < 0) return -1;
  fprintf(stderr, "NEGOTIATED: %ux%u fourcc=%.4s stride=%u size=%u\n",
          fmt.fmt.pix.width, fmt.fmt.pix.height, (char *)&fmt.fmt.pix.pixelformat,
          fmt.fmt.pix.bytesperline, fmt.fmt.pix.sizeimage);
  c->yuyv = fmt.fmt.pix.pixelformat == V4L2_PIX_FMT_YUYV;
  c->frame_bytes = BYTES * (c->yuyv ? 2 : 1);
  if (fmt.fmt.pix.width != 1280 || fmt.fmt.pix.height != 960 ||
      (!c->yuyv && fmt.fmt.pix.pixelformat != V4L2_PIX_FMT_GREY) ||
      fmt.fmt.pix.bytesperline != (unsigned)(1280 * (c->yuyv ? 2 : 1))) {
    fprintf(stderr, "Unsupported negotiated format; only packed GREY/YUYV accepted\n");
    return -1;
  }
  struct v4l2_streamparm sp = {0};
  sp.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
  sp.parm.capture.timeperframe.numerator = 1;
  sp.parm.capture.timeperframe.denominator = 60;
  if (xioctl(c->fd, VIDIOC_S_PARM, &sp) < 0 ||
      sp.parm.capture.timeperframe.numerator != 1 ||
      sp.parm.capture.timeperframe.denominator != 60)
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
  enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
  if (xioctl(c->fd, VIDIOC_STREAMON, &type) < 0)
    return -1;
  fprintf(stderr, "STREAMON: 1280x960 60fps (GREY output, YUYV luma extracted when applicable); waiting for physical buffers\n");
  c->streaming = 1;
  return 0;
}
static int capture_frame(struct capture *c, unsigned char *out) {
  struct pollfd p = {.fd = c->fd, .events = POLLIN};
  int r;
  do {
    r = poll(&p, 1, 2000);
  } while (r < 0 && errno == EINTR);
  if (r <= 0 || !(p.revents & POLLIN)) {
    fprintf(stderr, "CAPTURE FAILED: poll=%d revents=0x%x after maximum 2000ms; errno=%d\n", r, p.revents, r < 0 ? errno : 0);
    return -1;
  }
  struct v4l2_buffer b = {0};
  b.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
  b.memory = V4L2_MEMORY_MMAP;
  if (xioctl(c->fd, VIDIOC_DQBUF, &b) < 0)
    return -1;
  fprintf(stderr, "DQBUF: sequence=%u bytes=%u flags=0x%x timestamp=%ld.%06ld\n",
          b.sequence, b.bytesused, b.flags, (long)b.timestamp.tv_sec, (long)b.timestamp.tv_usec);
  int ok = b.index < c->count && b.bytesused == c->frame_bytes &&
           b.bytesused <= c->lengths[b.index] &&
           !(b.flags & V4L2_BUF_FLAG_ERROR);
  if (ok) {
    if (c->yuyv) {
      const unsigned char *src = c->maps[b.index];
      for (unsigned i = 0; i < BYTES; i++) out[i] = src[i * 2];
    } else memcpy(out, c->maps[b.index], BYTES);
  }
  if (xioctl(c->fd, VIDIOC_QBUF, &b) < 0)
    return -1;
  return ok ? 0 : -1;
}
int main(int argc, char **argv) {
  int synthetic = argc == 2 && !strcmp(argv[1], "--synthetic");
  int hardware = argc == 4 && !strcmp(argv[1], "--allow-hardware") &&
                 !strcmp(argv[2], "--device");
  if (!synthetic && !hardware) {
    fprintf(stderr,
            "Usage: %s --synthetic | --allow-hardware --device /dev/videoN\n",
            argv[0]);
    return 2;
  }
  const char *token = getenv("PIKA_CAMERA_TOKEN"),
             *port = getenv("PIKA_CAMERA_PORT");
  if (!token || strlen(token) < 16 || strlen(token) > 63 || !port) {
    fprintf(stderr, "Explicit private token and port required\n");
    return 2;
  }
  char *end;
  long number = strtol(port, &end, 10);
  if (*end || number < 1024 || number > 65535)
    return 2;
  int server = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
  if (server < 0)
    return 1;
  int on = 1;
  setsockopt(server, SOL_SOCKET, SO_REUSEADDR, &on, sizeof(on));
  struct sockaddr_in a = {.sin_family = AF_INET,
                          .sin_addr.s_addr = htonl(INADDR_LOOPBACK),
                          .sin_port = htons(number)};
  if (bind(server, (void *)&a, sizeof(a)) || listen(server, 1)) {
    perror("listen");
    return 1;
  }
  fprintf(stderr,
          "READY %s on loopback port %ld; physical device opens deferred until "
          "authenticated frame request\n",
          synthetic ? "SYNTHETIC TRANSPORT" : "EXPERIMENTAL V4L2", number);
  unsigned char *frame = malloc(BYTES);
  if (!frame)
    return 1;
  for (;;) {
    int client = accept4(server, NULL, NULL, SOCK_CLOEXEC);
    if (client < 0) {
      if (errno == EINTR)
        continue;
      break;
    }
    struct timeval timeout = {.tv_sec = 4};
    setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    setsockopt(client, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
    char received[64] = {0}, expected[64] = {0};
    memcpy(expected, token, strlen(token));
    if (all(client, received, 64, 0) || memcmp(received, expected, 64)) {
      close(client);
      continue;
    }
    struct capture c = {.fd = -1};
    uint32_t seq = 0;
    char request[6];
    while (!all(client, request, 6, 0)) {
      if (memcmp(request, "FRAME\n", 6))
        break;
      int fail = 0;
      if (synthetic) {
        for (unsigned i = 0; i < BYTES; i++)
          frame[i] = (i + seq) % 251;
      } else {
        if (c.fd < 0)
          fail = capture_open(&c, argv[3]);
        if (!fail)
          fail = capture_frame(&c, frame);
      }
      uint32_t reply[4] = {fail ? 1 : 0, fail ? 0 : BYTES, seq++, 0};
      if (all(client, reply, sizeof(reply), 1) || fail ||
          all(client, frame, BYTES, 1))
        break;
    }
    capture_close(&c);
    close(client);
    if (hardware) break; /* One physical session per bounded test. */
  }
  free(frame);
  close(server);
  return 0;
}
