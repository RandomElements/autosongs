/*
 * The configuration for a plain, portable build of LAME.
 *
 * LAME's own build system writes a config.h with hundreds of entries for
 * every platform it has ever been compiled on. Only a handful matter here:
 * the code has to know that the C library headers exist, and that the
 * machine is little endian and not a Windows.
 *
 * Everything else is left undefined on purpose, which turns off the
 * assembly paths, the SSE paths and the debugging paths.
 */
#ifndef AUTOSONGS_LAME_CONFIG_H
#define AUTOSONGS_LAME_CONFIG_H

#define STDC_HEADERS 1
#define HAVE_STDIO_H 1
#define HAVE_STDLIB_H 1
#define HAVE_STRING_H 1
#define HAVE_STDINT_H 1
#define HAVE_INTTYPES_H 1
#define HAVE_LIMITS_H 1
#define HAVE_MATH_H 1
#define HAVE_UNISTD_H 1
#define HAVE_ERRNO_H 1
#define HAVE_FCNTL_H 1
#define HAVE_STRCHR 1
#define HAVE_MEMCPY 1
#define HAVE_MEMMOVE 1

#define PACKAGE "lame"
#define PACKAGE_NAME "LAME"
#define PACKAGE_VERSION "3.100"
#define VERSION "3.100"

/* LAME's build system checks for these two types and adds them when the
 * platform does not have them. Android does not, so they are added here,
 * exactly as upstream's config.h.in does. */
#ifndef HAVE_IEEE754_FLOAT32_T
typedef float ieee754_float32_t;
#endif
#ifndef HAVE_IEEE754_FLOAT64_T
typedef double ieee754_float64_t;
#endif

#endif
