// The card's picture frame has the shape of the camera picture. Only the
// playing stream knows its size, which depends on the camera settings of the
// device, so the browser remembers it per camera: the card then has the right
// shape before the next stream starts and does not jump when it does.
// The CSS fallback matches 960x576 live / 800x480 native snapshots. Legacy
// streams still own their measured ratio; custom/archive images never change it.
const PROPERTY = "--c300x-picture-ratio";
const storageKey = (entityId) => `c300x-picture-ratio:${entityId}`;

export function c300xPictureRatio(width, height) {
  const ratio = Number(width) / Number(height);
  return width > 0 && height > 0 && ratio >= 0.5 && ratio <= 3
    ? Math.round(ratio * 10000) / 10000 : null;
}

function stored(entityId) {
  try {
    const ratio = Number(globalThis.localStorage?.getItem(storageKey(entityId)));
    return ratio >= 0.5 && ratio <= 3 ? ratio : null;
  } catch (_error) {
    return null;
  }
}

function remember(entityId, ratio) {
  try {
    globalThis.localStorage?.setItem(storageKey(entityId), String(ratio));
  } catch (_error) {
    // Private windows and full storage: the frame still follows this stream.
  }
}

// `entityId` is a function: the camera is known only once Home Assistant is,
// and the card can be given another one. The card calls `sync` then.
export function c300xFollowPictureSize(host, video, entityId) {
  let shown = "";
  const apply = (ratio) => {
    if (ratio) host.style.setProperty(PROPERTY, String(ratio));
    else host.style.removeProperty(PROPERTY);
  };
  const follow = () => {
    const ratio = c300xPictureRatio(video.videoWidth, video.videoHeight);
    if (!ratio) return;
    apply(ratio);
    const id = entityId();
    if (id && stored(id) !== ratio) remember(id, ratio);
  };
  const sync = () => {
    const id = entityId() || "";
    if (id === shown) return;
    shown = id;
    apply(id ? stored(id) : null);
  };
  sync();
  video.addEventListener("loadedmetadata", follow);
  video.addEventListener("resize", follow);
  return { sync };
}
