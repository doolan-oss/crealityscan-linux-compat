/* Verifies via sysfs that /dev/videoN belongs to the selected scanner model:
 * vendor 2bc5 and the product ID from PIKA_USB_PID (the Pika's by default).
 * Requires scanner-profile.h. */
static unsigned scanner_pid(void) {
  unsigned pid;
  const char *text = getenv("PIKA_USB_PID");
  return text && !profile_parse_pid(text, &pid) ? pid : profile_default_pid;
}
static int scanner_node(const char *node) {
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
      ok = fgets(s, sizeof(s), f) && strtoul(s, NULL, 16) == scanner_pid();
      fclose(f);
      return ok;
    }
    char *slash = strrchr(resolved, '/');
    if (!slash || slash == resolved)
      return 0;
    *slash = 0;
  }
}
