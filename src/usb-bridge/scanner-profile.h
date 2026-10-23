/* Per-model values the launcher (scripts/models.py) passes in the environment,
 * shared by the Windows bridge and the native helpers. Without them the
 * original Pika values apply. Plain C: no Windows or Linux headers.
 *
 * Stream modes, one variable per camera endpoint (PIKA_MODES_0 / _1):
 *   FOURCC:WIDTHxHEIGHT:RATE,RATE,...;FOURCC:...
 * FOURCC is a V4L2 code: GREY, MJPG, YUYV, or NV12/BGR3 (decoded from MJPG).
 * Extension units (PIKA_XU): UNIT:GUIDHEX:SELECTORMASK;... where GUIDHEX is
 * the descriptor byte order and bit n of the hex mask allows selector n+1. */
#define PROFILE_MAX_MODES 16
#define PROFILE_MAX_RATES 16
#define PROFILE_MAX_TYPES 64
#define PROFILE_MAX_UNITS 4
#define PROFILE_FOURCC(a, b, c, d) ((unsigned)(a) | (unsigned)(b) << 8 | (unsigned)(c) << 16 | (unsigned)(d) << 24)
typedef struct { unsigned fourcc, width, height, count, rates[PROFILE_MAX_RATES]; } profile_mode;
typedef struct { unsigned count; profile_mode modes[PROFILE_MAX_MODES]; } profile_modes;
typedef struct { unsigned unit, mask; unsigned char guid[16]; } profile_unit;
typedef struct { unsigned count; profile_unit units[PROFILE_MAX_UNITS]; } profile_units;
static const char *const profile_default_modes[2] = {
    "GREY:1280x960:120,110,100,90,80,70,60,50,40,30,20,15,10;"
    "MJPG:1280x960:120,110,100,90,80,70,60,50,40,30,20,15,10",
    "YUYV:1280x960:60,50,40,30,20,15,10,5;MJPG:1280x960:60,50,40,30,20,15,10,5;"
    "NV12:1280x960:60,50,40,30,20,15,10,5;BGR3:1280x960:60,50,40,30,20,15,10,5"};
static const char profile_default_units[] = "4:a15157a5c5f35e4a8d5a6854b8fa2716:7";
static const unsigned profile_default_pid = 0x0c0b;

static inline int profile_number(const char **p, unsigned max, unsigned *out) {
  unsigned long n = 0;
  const char *s = *p;
  if (*s < '0' || *s > '9') return -1;
  while (*s >= '0' && *s <= '9') {
    n = n * 10 + (unsigned)(*s++ - '0');
    if (n > max) return -1;
  }
  *p = s;
  *out = (unsigned)n;
  return 0;
}
static inline int profile_hex(char c) {
  return c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
}
static inline int profile_known_fourcc(unsigned f) {
  return f == PROFILE_FOURCC('G', 'R', 'E', 'Y') || f == PROFILE_FOURCC('M', 'J', 'P', 'G') ||
         f == PROFILE_FOURCC('Y', 'U', 'Y', 'V') || f == PROFILE_FOURCC('N', 'V', '1', '2') ||
         f == PROFILE_FOURCC('B', 'G', 'R', '3');
}
/* Returns 0 for a complete, valid table; -1 leaves *out unspecified. */
static inline int profile_parse_modes(const char *s, profile_modes *out) {
  unsigned types = 0;
  out->count = 0;
  if (!s || !*s) return -1;
  for (;;) {
    if (out->count == PROFILE_MAX_MODES) return -1;
    profile_mode *m = &out->modes[out->count++];
    for (unsigned i = 0; i < 4; i++)
      if (!s[i] || s[i] == ':') return -1;
    m->fourcc = PROFILE_FOURCC(s[0], s[1], s[2], s[3]);
    s += 4;
    if (!profile_known_fourcc(m->fourcc) || *s++ != ':' || profile_number(&s, 8192, &m->width) ||
        *s++ != 'x' || profile_number(&s, 8192, &m->height) || *s++ != ':' || m->width < 16 || m->height < 16)
      return -1;
    for (m->count = 0;; s++) {
      if (m->count == PROFILE_MAX_RATES || profile_number(&s, 1000, &m->rates[m->count]) || !m->rates[m->count])
        return -1;
      m->count++;
      if (*s != ',') break;
    }
    types += m->count;
    if (types > PROFILE_MAX_TYPES) return -1;
    if (!*s) return 0;
    if (*s++ != ';') return -1;
  }
}
static inline int profile_parse_units(const char *s, profile_units *out) {
  out->count = 0;
  if (!s || !*s) return -1;
  for (;;) {
    if (out->count == PROFILE_MAX_UNITS) return -1;
    profile_unit *u = &out->units[out->count++];
    if (profile_number(&s, 255, &u->unit) || !u->unit || *s++ != ':') return -1;
    for (unsigned i = 0; i < 16; i++, s += 2) {
      int hi = profile_hex(s[0]), lo = hi < 0 ? -1 : profile_hex(s[1]);
      if (lo < 0) return -1;
      u->guid[i] = (unsigned char)(hi << 4 | lo);
    }
    if (*s++ != ':') return -1;
    u->mask = 0;
    for (unsigned digits = 0; profile_hex(*s) >= 0; s++, digits++) {
      if (digits == 8) return -1;
      u->mask = u->mask << 4 | (unsigned)profile_hex(*s);
    }
    if (!u->mask) return -1;
    if (!*s) return 0;
    if (*s++ != ';') return -1;
  }
}
static inline int profile_parse_pid(const char *s, unsigned *pid) {
  unsigned n = 0, digits = 0;
  for (; s && profile_hex(*s) >= 0; s++, digits++) n = n << 4 | (unsigned)profile_hex(*s);
  if (!s || *s || digits != 4 || !n) return -1;
  *pid = n;
  return 0;
}
static inline const profile_mode *profile_find(const profile_modes *t, unsigned fourcc, unsigned width, unsigned height, unsigned fps) {
  for (unsigned i = 0; i < t->count; i++) {
    const profile_mode *m = &t->modes[i];
    if (m->fourcc != fourcc || m->width != width || m->height != height) continue;
    for (unsigned r = 0; r < m->count; r++)
      if (m->rates[r] == fps) return m;
  }
  return 0;
}
