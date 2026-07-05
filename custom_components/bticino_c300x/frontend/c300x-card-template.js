export const C300X_DOORBELL_CARD_TEMPLATE = `
      <style>
        :host {
          display: block;
          height: 100%;
        }
        ha-card {
          overflow: hidden;
          height: 100%;
          display: flex;
          flex-direction: column;
        }
        .media {
          position: relative;
          width: 100%;
          flex: 1 1 auto;
          background: #111;
          min-height: 0;
        }
        video {
          width: 100%;
          height: 100%;
          object-fit: contain;
          display: block;
          background: #111;
        }
        .remote-audio {
          position: absolute;
          width: 1px;
          height: 1px;
          opacity: 0;
          pointer-events: none;
        }
        .transition-video {
          position: absolute;
          width: 1px;
          height: 1px;
          opacity: 0;
          pointer-events: none;
        }
        .empty {
          position: absolute;
          inset: 0;
          display: flex;
          align-items: center;
          justify-content: center;
          color: var(--secondary-text-color);
          font-size: 14px;
          pointer-events: none;
        }
        .body {
          min-height: 48px;
          padding: 4px 16px;
          display: flex;
          align-items: center;
          flex: 0 0 auto;
        }
        .entity-main {
          display: flex;
          align-items: center;
          min-width: 0;
          flex: 1 1 auto;
        }
        .row-actions {
          display: flex;
          align-items: center;
          gap: 8px;
          margin: 0 16px 0 0;
          flex: 0 0 auto;
        }
        .row-action,
        .home-action,
        .mic-action {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 40px;
          height: 40px;
          margin: 0;
          padding: 0;
          border: 0;
          color: var(--state-icon-color);
          background: color-mix(in srgb, var(--state-icon-color) 14%, transparent);
          flex: 0 0 auto;
          --mdc-icon-size: 24px;
          border-radius: 50%;
          cursor: pointer;
          font: inherit;
          transition: background-color 140ms ease, color 140ms ease, transform 140ms ease;
        }
        .row-action.active {
          color: var(--primary-color);
          background: color-mix(in srgb, var(--primary-color) 18%, transparent);
        }
        .home-action.hidden {
          display: none;
        }
        .home-action.active {
          color: var(--primary-color);
          background: color-mix(in srgb, var(--primary-color) 18%, transparent);
        }
        .home-action.dialing {
          color: var(--warning-color, var(--primary-color));
          background: color-mix(in srgb, var(--warning-color, var(--primary-color)) 20%, transparent);
          animation: c300x-ring 900ms ease-in-out infinite;
        }
        .home-action.blocked {
          color: var(--disabled-text-color);
          background: color-mix(in srgb, var(--disabled-text-color) 14%, transparent);
          cursor: default;
        }
        .row-action.dialing,
        .row-action.answerable {
          color: var(--warning-color, var(--primary-color));
          background: color-mix(in srgb, var(--warning-color, var(--primary-color)) 20%, transparent);
          animation: c300x-ring 900ms ease-in-out infinite, c300x-answer-glow 1400ms ease-in-out infinite;
        }
        .row-action.recording {
          position: relative;
          color: var(--error-color);
          background: color-mix(in srgb, var(--error-color) 18%, transparent);
          animation: c300x-record-breathe 1300ms ease-in-out infinite;
        }
        .row-action.blocked {
          color: var(--disabled-text-color);
          background: color-mix(in srgb, var(--disabled-text-color) 14%, transparent);
          cursor: default;
        }
        .row-action.recording::after {
          content: "";
          position: absolute;
          top: 7px;
          right: 7px;
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: var(--error-color);
          box-shadow: 0 0 0 0 color-mix(in srgb, var(--error-color) 45%, transparent);
          animation: c300x-record-dot 1100ms ease-out infinite;
        }
        @keyframes c300x-ring {
          0%, 100% { transform: rotate(0deg) scale(1); }
          18% { transform: rotate(-12deg) scale(1.03); }
          36% { transform: rotate(10deg) scale(1.03); }
          54% { transform: rotate(-7deg) scale(1.02); }
          72% { transform: rotate(5deg) scale(1.01); }
        }
        @keyframes c300x-answer-glow {
          0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--warning-color, var(--primary-color)) 0%, transparent); }
          45% { box-shadow: 0 0 0 8px color-mix(in srgb, var(--warning-color, var(--primary-color)) 18%, transparent); }
        }
        @keyframes c300x-record-breathe {
          0%, 100% { transform: scale(1); }
          50% { transform: scale(1.05); }
        }
        @keyframes c300x-record-dot {
          0% { opacity: 1; box-shadow: 0 0 0 0 color-mix(in srgb, var(--error-color) 45%, transparent); }
          100% { opacity: .35; box-shadow: 0 0 0 8px color-mix(in srgb, var(--error-color) 0%, transparent); }
        }
        .row-action:focus-visible {
          outline: 2px solid var(--primary-color);
          outline-offset: 2px;
        }
        .mic-action {
          width: 36px;
          height: 36px;
          --mdc-icon-size: 22px;
        }
        .mic-action.muted {
          color: var(--warning-color, var(--primary-color));
          background: color-mix(in srgb, var(--warning-color, var(--primary-color)) 18%, transparent);
        }
        .mic-action.hidden {
          display: none;
        }
        .mic-action:focus-visible {
          outline: 2px solid var(--primary-color);
          outline-offset: 2px;
        }
        .action-icon {
          display: flex;
        }
        .entity-text {
          min-width: 0;
        }
        .title {
          font-size: 14px;
          font-weight: 400;
          line-height: 20px;
          color: var(--primary-text-color);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .secondary {
          color: var(--secondary-text-color);
          font-size: 13px;
          line-height: 18px;
        }
        .secondary.error {
          color: var(--error-color);
        }
        .secondary.notice {
          color: var(--warning-color, var(--secondary-text-color));
        }
        .readiness {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          margin-top: 2px;
          min-height: 18px;
          color: var(--secondary-text-color);
          font-size: 12px;
          line-height: 16px;
          cursor: pointer;
        }
        .readiness.hidden {
          display: none;
        }
        .readiness.ready {
          color: var(--success-color, #43a047);
        }
        .readiness.warning {
          color: var(--warning-color, #f9a825);
        }
        .readiness.blocked,
        .readiness.unavailable {
          color: var(--error-color);
        }
        .readiness-icon {
          --mdc-icon-size: 16px;
        }
      </style>
      <ha-card>
        <audio class="remote-audio" autoplay playsinline></audio>
        <div class="media">
          <video playsinline autoplay></video>
          <video class="transition-video" playsinline autoplay></video>
          <div class="empty"></div>
        </div>
        <div class="body">
          <div class="entity-main">
            <div class="row-actions">
              <button class="row-action" type="button">
                <ha-icon class="action-icon" icon="mdi:phone"></ha-icon>
              </button>
              <button class="home-action hidden" type="button">
                <ha-icon class="home-action-icon" icon="mdi:phone"></ha-icon>
              </button>
              <button class="mic-action hidden" type="button">
                <ha-icon class="mic-icon" icon="mdi:microphone"></ha-icon>
              </button>
            </div>
            <div class="entity-text">
              <div class="title"></div>
              <div class="secondary"></div>
              <div class="readiness hidden">
                <ha-icon class="readiness-icon" icon="mdi:check-circle"></ha-icon>
                <span class="readiness-text"></span>
              </div>
            </div>
          </div>
        </div>
      </ha-card>
    `;
