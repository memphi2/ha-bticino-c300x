import assert from "node:assert/strict";

export async function checkRingEndStart(page) {
  let cases = 0;
  for (const mode of ["answer_http", "answer_permission", "notification_permission"]) {
    for (const delivery of ["hass", "event"]) {
      for (const reject of [false, true]) {
        for (const nextRing of [false, true]) {
          await page.reload();
          await page.waitForFunction(() => !!window.lab);
          const result = await page.evaluate(async ({ mode, delivery, reject, nextRing }) => {
            const card = lab.card;
            card._ensureDoorbellPreview = async () => {};
            let grant, deny, answer, failAnswer, microphones = 0, offers = 0;
            const subscribe = lab.hass.connection.subscribeMessage;
            lab.hass.connection.subscribeMessage = (...args) => {
              offers++;
              return subscribe(...args);
            };
            const service = lab.hass.callService;
            lab.hass.callService = async (...args) => {
              await service(...args);
              if (mode === "answer_http") await new Promise((resolve, reject) => {
                answer = resolve; failAnswer = reject;
              });
            };
            navigator.mediaDevices.getUserMedia = () => {
              microphones++;
              return new Promise((resolve, reject) => { grant = resolve; deny = reject; });
            };
            const audio = new AudioContext();
            const stream = audio.createMediaStreamDestination().stream;
            const state = media_state => ({ state: "idle", attributes: {
              media_state, media_primary_action: media_state === "idle" ? "start_stream" : "answer_ring",
            } });
            lab.hass.states[lab.camera] = state(mode.startsWith("notification") ? "ring_active" : "ring_pending");
            card.hass = { ...lab.hass };
            if (mode.startsWith("notification")) card._ringAnswerLaunchPending = true;
            const generation = card._mediaGeneration;
            const start = mode.startsWith("notification") ? card._startNotificationAnsweredDoorbellStream()
              : card._actions.handlePrimaryAction();
            for (let i = 0; !(mode === "answer_http" ? answer : grant) && i < 20; i++) {
              await new Promise(resolve => setTimeout(resolve, 0));
            }
            if (!(mode === "answer_http" ? answer : grant)) throw new Error("Expected pending ring work");
            // Deliver both end and next-ring states before a render can coalesce them.
            const deliver = entity => {
              if (delivery === "event") card._handleStateChanged({ data: {
                entity_id: lab.camera, new_state: entity,
              } });
              else { lab.hass.states[lab.camera] = entity; card.hass = { ...lab.hass }; }
            };
            deliver(state("idle"));
            const invalidatedAtEnd = card._mediaGeneration > generation;
            if (nextRing) deliver(state("ring_pending"));
            if (mode === "answer_http") {
              if (reject) failAnswer(new Error("late answer failure"));
              else answer();
            } else if (reject) deny(new DOMException("Denied", "NotAllowedError"));
            else grant(stream);
            const settled = await Promise.race([
              start.then(() => true), new Promise(resolve => setTimeout(() => resolve(false), 1000)),
            ]);
            const result = { settled, invalidatedAtEnd, microphones, offers,
              peers: lab.peers.size, microphone: !!card._micStream,
              stopped: mode === "answer_http" || reject || stream.getTracks().every(track => track.readyState === "ended"),
              answered: card._lifecycle.doorbellAnswered,
              pending: card._lifecycle.answeringDoorbell || card._ringAnswerLaunchStarting,
              error: card._error, services: lab.calls.map(call => call.service) };
            card._closePeer(true);
            stream.getTracks().forEach(track => track.stop());
            await audio.close();
            return result;
          }, { mode, delivery, reject, nextRing });
          assert.deepEqual(result, {
            settled: true, invalidatedAtEnd: true,
            microphones: mode === "answer_http" ? 0 : 1,
            offers: 0, peers: 0, microphone: false, stopped: true,
            answered: false, pending: false, error: "",
            services: mode.startsWith("notification") ? [] : ["answer_doorbell_call"],
          }, JSON.stringify({ mode, delivery, reject, nextRing }));
          cases++;
        }
      }
    }
  }

  for (const mode of ["answer_http", "answer_permission", "notification_permission", "manual"]) {
    await page.reload();
    await page.waitForFunction(() => !!window.lab);
    const result = await page.evaluate(async mode => {
      const card = lab.card;
      card._ensureDoorbellPreview = async () => {};
      let grant, answer;
      navigator.mediaDevices.getUserMedia = () => new Promise(resolve => { grant = resolve; });
      if (mode === "answer_http") lab.hass.callService = () => new Promise(resolve => { answer = resolve; });
      const setState = media_state => {
        lab.hass.states[lab.camera] = { state: "idle", attributes: {
          media_state, media_primary_action: media_state === "idle" ? "start_stream" : "answer_ring",
        } };
        card.hass = { ...lab.hass };
      };
      setState(mode === "manual" ? "idle" : mode === "notification_permission" ? "ring_active" : "ring_pending");
      if (mode === "notification_permission") card._ringAnswerLaunchPending = true;
      const generation = card._mediaGeneration;
      const start = mode === "manual" ? card._startTalkback()
        : mode === "notification_permission" ? card._startNotificationAnsweredDoorbellStream()
          : card._actions.handlePrimaryAction();
      if (mode === "answer_http") {
        setState("ring_answering");
        answer();
      }
      for (let i = 0; !grant && i < 20; i++) await new Promise(resolve => setTimeout(resolve, 0));
      if (!grant) throw new Error("Expected microphone permission");
      if (mode !== "manual") setState("ring_active");
      else setState("idle");
      const audio = new AudioContext();
      const stream = audio.createMediaStreamDestination().stream;
      grant(stream);
      await start;
      const result = { unchanged: generation === card._mediaGeneration,
        peers: lab.peers.size, microphone: card._micStream === stream };
      card._closePeer(true);
      await audio.close();
      return result;
    }, mode);
    assert.deepEqual(result, { unchanged: true, peers: 1, microphone: true }, mode);
    cases++;
  }
  await page.reload();
  await page.waitForFunction(() => !!window.lab);
  console.log(`Ring end: ${cases} pending-answer/permission and live-call controls passed`);
}
