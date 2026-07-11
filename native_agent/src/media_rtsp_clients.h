#ifndef C300X_MEDIA_RTSP_CLIENTS_H
#define C300X_MEDIA_RTSP_CLIENTS_H

#include "video_rtsp.h"

#include <netinet/in.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

typedef struct {
    bool active;
    int fd;
    bool described;
    bool played;
    bool parked;
    bool transport_tcp;
    bool audio_enabled;
    bool recorder;
    bool backchannel_enabled;
    int video_interleaved_channel;
    int audio_interleaved_channel;
    int backchannel_interleaved_channel;
    struct sockaddr_in udp_client;
    char session_id[32];
} rtsp_client_slot_t;

typedef struct {
    int fd;
    bool transport_tcp;
    int channel;
    struct sockaddr_in udp_client;
} rtsp_send_target_t;

static inline int c300x_rtsp_client_slots_physical_count(
    const rtsp_client_slot_t *slots
) {
    int count = 0;

    for (size_t index = 0; index < C300X_VIDEO_RING_PREVIEW_MAX_RTSP_CLIENTS; index++) {
        if (slots[index].active && slots[index].fd >= 0) {
            count++;
        }
    }
    return count;
}

static inline int c300x_rtsp_client_slots_active_count(
    const rtsp_client_slot_t *slots
) {
    int count = 0;

    for (size_t index = 0; index < C300X_VIDEO_RING_PREVIEW_MAX_RTSP_CLIENTS; index++) {
        if (slots[index].active && slots[index].fd >= 0 && !slots[index].parked) {
            count++;
        }
    }
    return count;
}

static inline rtsp_client_slot_t *c300x_rtsp_client_slot(
    rtsp_client_slot_t *slots,
    int slot_index
) {
    if (slot_index < 0 || slot_index >= (int)C300X_VIDEO_RING_PREVIEW_MAX_RTSP_CLIENTS) {
        return NULL;
    }
    rtsp_client_slot_t *slot = &slots[slot_index];
    return slot->active && slot->fd >= 0 ? slot : NULL;
}

static inline rtsp_client_slot_t *c300x_rtsp_client_slot_for_fd(
    rtsp_client_slot_t *slots,
    int slot_index,
    int fd
) {
    rtsp_client_slot_t *slot = c300x_rtsp_client_slot(slots, slot_index);

    return slot != NULL && slot->fd == fd ? slot : NULL;
}

static inline bool c300x_rtsp_client_slot_evict(rtsp_client_slot_t *slot) {
    if (slot == NULL || !slot->active || slot->fd < 0) {
        return false;
    }
    (void)shutdown(slot->fd, SHUT_RDWR);
    memset(slot, 0, sizeof(*slot));
    slot->fd = -1;
    return true;
}

static inline int c300x_rtsp_client_slots_evict_parked(
    rtsp_client_slot_t *slots
) {
    for (size_t index = 0; index < C300X_VIDEO_RING_PREVIEW_MAX_RTSP_CLIENTS; index++) {
        if (slots[index].active && slots[index].fd >= 0 && slots[index].parked) {
            return c300x_rtsp_client_slot_evict(&slots[index]) ? 1 : 0;
        }
    }
    return 0;
}

static inline bool c300x_rtsp_client_slots_compatible(
    rtsp_client_slot_t *slots,
    int current_fd,
    bool wants_audio,
    bool recorder
) {
    for (size_t index = 0; index < C300X_VIDEO_RING_PREVIEW_MAX_RTSP_CLIENTS; index++) {
        rtsp_client_slot_t *slot = &slots[index];
        // Identify "self" by fd, not slot index: a slot reused by another client
        // (ABA) must still be evaluated for compatibility, not skipped as self.
        if (!slot->active || slot->fd < 0 || slot->parked || slot->fd == current_fd) {
            continue;
        }
        if (!slot->described) {
            continue;
        }
        if (slot->audio_enabled != wants_audio || slot->recorder != recorder) {
            return false;
        }
    }
    return true;
}

static inline size_t c300x_rtsp_client_slots_send_targets(
    const rtsp_client_slot_t *slots,
    bool audio,
    rtsp_send_target_t *targets,
    size_t targets_len
) {
    size_t count = 0;

    for (size_t index = 0; index < C300X_VIDEO_RING_PREVIEW_MAX_RTSP_CLIENTS && count < targets_len; index++) {
        const rtsp_client_slot_t *slot = &slots[index];
        if (!slot->active || slot->fd < 0 || slot->parked) {
            continue;
        }
        if (audio && !slot->audio_enabled) {
            continue;
        }
        targets[count].fd = slot->fd;
        targets[count].transport_tcp = slot->transport_tcp;
        targets[count].channel = audio ? slot->audio_interleaved_channel : slot->video_interleaved_channel;
        targets[count].udp_client = slot->udp_client;
        count++;
    }
    return count;
}

#endif
