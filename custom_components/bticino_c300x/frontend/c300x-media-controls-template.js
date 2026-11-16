const button = (name, icon) => `<button class="${name}" type="button"><ha-icon icon="mdi:${icon}" aria-hidden="true"></ha-icon></button>`;

export const MEDIA_CONTROLS_TEMPLATE = `
  <style>
    :host { position: absolute; inset: 0; display: block; pointer-events: none; container-type: inline-size;
      color: var(--primary-text-color); font: var(--ha-font-body-m, 14px/1.4 var(--ha-font-family-body, var(--primary-font-family, sans-serif))); letter-spacing: 0; }
    :host([hidden]), [hidden] { display: none !important; }
    * { box-sizing: border-box; }
    .archive { position: absolute; inset: 0 0 var(--c300x-media-toolbar-height, 76px); pointer-events: auto;
      background: var(--c300x-media-background, #111); overflow: hidden; }
    .archive img, .archive video { display: block; width: 100%; height: 100%; object-fit: contain; }
    .stamp { position: absolute; right: 8px; bottom: 6px; max-width: calc(100% - 16px); margin: 0;
      padding: 2px 4px; font-size: 12px; overflow-wrap: anywhere; color: #fff; background: rgb(0 0 0 / .65); }
    .toolbar { position: absolute; bottom: 0; inset-inline: 0; height: var(--c300x-media-toolbar-height, 76px);
      display: grid; grid-template-rows: 28px minmax(40px, 1fr); padding: 0 4px 4px; pointer-events: auto;
      background: var(--ha-card-background, var(--card-background-color, #fff)); border-top: 1px solid var(--divider-color); }
    .info { display: flex; align-items: center; gap: 8px; min-width: 0; padding: 0 4px; }
    .mode, .status { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; min-width: 0; font-size: 12px; }
    .status { color: var(--secondary-text-color); }
    .timeline { display: flex; align-items: center; gap: 6px; flex: 1; min-width: 0; }
    .elapsed { white-space: nowrap; font-size: 12px; font-variant-numeric: tabular-nums; }
    .buttons { display: flex; align-items: center; gap: 0; min-width: 0; }
    .spacer { flex: 1; }
    button { width: 40px; height: 40px; flex: 0 0 40px; display: inline-flex; align-items: center;
      justify-content: center; padding: 0; border: 0; border-radius: 4px; background: none; cursor: pointer;
      color: var(--primary-text-color); -webkit-tap-highlight-color: transparent; }
    button:hover { background: var(--secondary-background-color); }
    button:disabled { color: var(--disabled-text-color); cursor: default; }
    button:focus-visible, input:focus-visible { outline: 2px solid var(--primary-color); outline-offset: -2px; }
    button[aria-pressed="true"] { color: var(--primary-color); }
    ha-icon { --mdc-icon-size: 24px; pointer-events: none; }
    input[type="range"] { min-width: 0; height: 24px; margin: 0; accent-color: var(--primary-color); cursor: pointer; }
    .seek { flex: 1; width: 0; }
    .volume { width: 64px; flex: 0 1 64px; }
    @container (max-width: 340px) { .volume { width: 40px; flex-basis: 40px; } button { width: 36px; flex-basis: 36px; } }
    @container (max-width: 280px) { button { width: 32px; flex-basis: 32px; } }
    @container (max-width: 239px) {
      .buttons { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); grid-template-rows: 40px 40px; }
      .buttons > button { justify-self: center; }
      .previous { grid-area: 1 / 1; } .current { grid-area: 1 / 2; }
      .next { grid-area: 1 / 3; } .play { grid-area: 1 / 4; }
      .mute { grid-area: 2 / 1; } .volume { grid-area: 2 / 2 / 3 / 4; width: 100%; min-width: 48px; }
      .fullscreen { grid-area: 2 / 4; } .spacer { display: none; }
      .info { gap: 4px; }
      .info:has(.timeline:not([hidden])) .mode { display: none; }
    }
  </style>
  <div class="archive" hidden>
    <img hidden alt="">
    <video hidden playsinline preload="metadata"></video>
    <time class="stamp" hidden></time>
  </div>
  <div class="toolbar" role="group">
    <div class="info">
      <span class="mode"></span><span class="status" role="status" aria-live="polite"></span>
      <div class="timeline" hidden><input class="seek" type="range" min="0" max="0" step="0.1" value="0"><span class="elapsed">0:00 / 0:00</span></div>
    </div>
    <div class="buttons">
      ${button("previous", "chevron-left")}${button("current", "image-outline")}${button("next", "chevron-right")}
      ${button("play", "play")}
      <span class="spacer"></span>
      ${button("mute", "volume-high")}<input class="volume" type="range" min="0" max="1" step="0.05" value="1">
      ${button("fullscreen", "fullscreen")}
    </div>
  </div>`;
