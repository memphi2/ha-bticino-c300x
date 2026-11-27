#ifndef C300X_MEDIA_GOP_CACHE_H
#define C300X_MEDIA_GOP_CACHE_H

#include "media_rtsp_clients.h"

#include <stddef.h>

/* Bounds of the cached keyframe group: bytes of whole RTP packets, packets,
 * and RTP time from its IDR access unit (90 kHz clock). */
#define C300X_MEDIA_GOP_CACHE_BYTES (512u * 1024u)
#define C300X_MEDIA_GOP_CACHE_PACKETS 640u
#define C300X_MEDIA_GOP_CACHE_MAX_MS 1500u

/* Where a video packet comes from: a ring's call or an on-demand view. */
enum c300x_media_gop_source {
    C300X_MEDIA_GOP_RING = 1,
    C300X_MEDIA_GOP_ONDEMAND = 2,
};

/* Sends one RTP packet of the station's H.264 video to the RTSP targets.
 * A target that has not had video yet starts with the cached group (SPS, PPS
 * and IDR first) or waits for the next IDR; each one gets its own sequence
 * numbers and timestamps. The cache and the targets follow one source at a
 * time: the other one's packets go nowhere until the first has been reset or
 * idle for a second. Consumes the targets' descriptors and writer
 * references, also for a packet it drops. Call without the bridge lock. */
void c300x_media_gop_forward(enum c300x_media_gop_source source, const rtsp_send_target_t *targets,
                             size_t count, const unsigned char *packet, size_t packet_len);

/* That source's session ended: forget its stream and free the cache. A
 * cache that follows the other source stays. */
void c300x_media_gop_reset(enum c300x_media_gop_source source);

#endif
