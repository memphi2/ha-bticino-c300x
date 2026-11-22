const button = (name, icon) => `<button class="${name}" type="button"><ha-icon icon="mdi:${icon}" aria-hidden="true"></ha-icon></button>`;

export const MEDIA_CONTROLS_TEMPLATE = `
  <style>
    :host { position: absolute; inset: 0; display: block; pointer-events: none; container-type: inline-size;
      color: #fff; font: var(--ha-font-body-m, 14px/1.4 var(--ha-font-family-body, var(--primary-font-family, sans-serif))); letter-spacing: 0; }
    :host([hidden]), [hidden] { display: none !important; }
    * { box-sizing: border-box; }
    .archive { position: absolute; inset: 0; pointer-events: auto;
      background: var(--c300x-media-background, #111); overflow: hidden; }
    .archive img, .archive video { display: block; width: 100%; height: 100%; object-fit: contain; }
    .stage { position: absolute; inset: 0; pointer-events: none; }
    /* Text on the picture has no plate: white with a dark outline, as the time written into an image. */
    .stamp, .info { color: #fff; text-shadow: 0 0 2px #000, 0 0 2px #000, 0 1px 3px #000; }
    /* The time of a video sits where an image carries its own: lower right, same size. */
    /* Without container units the time keeps a fixed size. */
    .stamp, .toolbar, .nav { --c300x-stamp-size: 12px; }
    @supports (width: 1cqw) { .stamp, .toolbar, .nav { --c300x-stamp-size: max(10px, 2.5cqw); } }
    .stamp { position: absolute; right: calc(var(--c300x-stamp-size) / 3);
      bottom: calc(var(--c300x-stamp-size) / 3); max-width: calc(100% - 16px); margin: 0;
      font-size: var(--c300x-stamp-size); line-height: 1.15; white-space: nowrap; font-variant-numeric: tabular-nums; }
    .info { position: absolute; top: 8px; left: 8px; max-width: calc(100% - 112px); display: flex;
      align-items: center; gap: 6px; padding: 2px 4px; }
    .mode, .status { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; min-width: 0; font-size: 12px; }
    .status { opacity: .8; }
    /* One row in a bar of its own; with a video it leaves the line of the time free below it. */
    .toolbar { position: absolute; bottom: 8px; inset-inline: 8px; display: flex; align-items: center; gap: 2px;
      padding: 0 6px; border-radius: 20px; pointer-events: auto; background: rgb(0 0 0 / .5);
      -webkit-backdrop-filter: blur(6px); backdrop-filter: blur(6px); }
    .toolbar[data-dated] { bottom: calc(var(--c300x-stamp-size) * 1.5 + 8px); }
    .timeline { order: 1; flex: 1; display: flex; align-items: center; gap: 8px; min-width: 0; padding: 0 4px; }
    .buttons { display: contents; }
    .play { order: 0; } .spacer, .mute, .volume { order: 2; }
    .timeline:not([hidden]) ~ .buttons .spacer { display: none; }
    .elapsed { white-space: nowrap; font-size: 12px; font-variant-numeric: tabular-nums; }
    .spacer { flex: 1; }
    button { width: 40px; height: 40px; flex: 0 0 40px; display: inline-flex; align-items: center;
      justify-content: center; padding: 0; border: 0; border-radius: 50%; background: none; cursor: pointer;
      color: #fff; pointer-events: auto; -webkit-tap-highlight-color: transparent; }
    button:hover { background: rgb(255 255 255 / .16); }
    button:disabled { opacity: .4; cursor: default; }
    button:focus-visible, input:focus-visible { outline: 2px solid var(--primary-color); outline-offset: -2px; }
    button[aria-pressed="true"] { color: var(--primary-color); }
    ha-icon { --mdc-icon-size: 24px; pointer-events: none; }
    input[type="range"] { min-width: 0; height: 24px; margin: 0; accent-color: var(--primary-color); cursor: pointer; }
    .seek { flex: 1; width: 0; }
    .volume { width: 64px; flex: 0 1 64px; }
    .stage > button { position: absolute; }
    .expand { inset: 0; width: 100%; height: 100%; border-radius: 0; cursor: zoom-in; }
    .expand:hover { background: none; }
    .nav, .close, .fullscreen { background: rgb(0 0 0 / .5); transition: opacity 140ms ease; }
    .nav:hover, .close:hover, .fullscreen:hover { background: rgb(0 0 0 / .75); }
    /* The arrows sit in the middle above the room of the bar, the same for images and videos. */
    .nav { --c300x-bar: calc(var(--c300x-stamp-size) * 1.5 + 48px); top: calc((100% - var(--c300x-bar)) / 2 - 20px); }
    .nav:disabled { opacity: 0; pointer-events: none; }
    .previous { left: 8px; }
    .next, .close { right: 8px; }
    .close, .fullscreen { top: 8px; }
    .fullscreen { right: 56px; }
    /* A narrow card gives the row to the seek bar: first the volume slider goes, then the times. */
    @container (max-width: 340px) { .timeline:not([hidden]) ~ .buttons .volume { display: none; } }
    @container (max-width: 280px) { .elapsed { display: none; } .volume { width: 40px; flex-basis: 40px; } button { width: 32px; height: 32px; flex-basis: 32px; }
      .nav { top: calc((100% - var(--c300x-bar)) / 2 - 16px); } .fullscreen { right: 48px; } }
  </style>
  <div class="archive" hidden>
    <img hidden alt="">
    <video hidden playsinline preload="metadata"></video>
  </div>
  <div class="stage">
    <button class="expand" type="button"></button>
    ${button("previous nav", "chevron-left")}${button("next nav", "chevron-right")}${button("fullscreen", "fullscreen")}${button("close", "close")}
    <div class="info"><span class="mode"></span><span class="status" role="status" aria-live="polite"></span></div>
    <time class="stamp" hidden></time>
  </div>
  <div class="toolbar" role="group">
    <div class="timeline" hidden><input class="seek" type="range" min="0" max="0" step="0.1" value="0"><span class="elapsed">0:00 / 0:00</span></div>
    <div class="buttons">
      ${button("play", "play")}
      <span class="spacer"></span>
      ${button("mute", "volume-high")}<input class="volume" type="range" min="0" max="1" step="0.05" value="1">
    </div>
  </div>`;
