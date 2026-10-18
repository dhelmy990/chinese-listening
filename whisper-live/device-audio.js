// Native capture stores snippets until their vocabulary session has been saved.
// Imports use the same authenticated WebSocket and transcription queue as the mic.
function initDeviceAudio() {
  if (!window.AndroidAudio || window.deviceAudio) return;
  const native = window.AndroidAudio;
  const button = document.querySelector('#device-audio');
  const review = document.querySelector('#review-captures');
  const message = document.querySelector('#device-status');
  const floating = document.querySelector('#floating-capture');
  const attempted = new Set(), completed = new Set(), nativeIds = new Map();
  let starting = false, draining = false, localError = '';
  let lastState = {supported: false, running: false, requesting: false, clips: []};
  document.querySelector('#device-tools').hidden = false;
  document.querySelector('#floating-setting').hidden = false;
  message.hidden = false;
  const delay = () => new Promise(resolve => setTimeout(resolve, 100));

  function state() {
    const value = JSON.parse(native.state());
    if (!Array.isArray(value.clips)) throw new Error('Could not read captured audio.');
    lastState = value;
    return value;
  }

  function render(value) {
    const waiting = value.clips.filter(clip => !attempted.has(clip.id)).length;
    button.textContent = value.running ? 'Stop app audio' : value.requesting ? 'Cancel audio setup' : 'Capture app audio';
    button.disabled = !value.supported || starting || endingSession || savingSession || (!sessionOpen && start.disabled);
    review.hidden = waiting === 0;
    review.textContent = `Review audio (${waiting})`;
    review.disabled = starting || endingSession || savingSession || (!sessionOpen && start.disabled);
    floating.disabled = scaleInput.disabled = value.running || value.requesting;
    if (audioInput === 'playback') {
      hasAudio = value.running;
      recall.disabled = !active || !hasAudio || endingSession;
    }
    message.textContent = localError || value.error || (!value.supported
      ? 'App audio capture requires Android 10 or newer. Microphone recording is available.'
      : value.requesting ? 'Approve Android’s audio sharing prompt. No screen video is recorded.'
      : value.running ? 'App audio is on. Open your video and hold the floating capture button.'
      : waiting ? `${waiting} audio snippet(s) are saved on this device. Review them in this session or a new one.`
      : audioInput === 'playback' && sessionOpen ? 'App audio is stopped. Stop & save to finish this session, or capture again.'
      : 'Capture audio from other apps into a new or current session. Some apps block capture.');
  }

  function importAvailable(value) {
    if (!sessionOpen || socket?.readyState !== WebSocket.OPEN) return;
    for (const clip of value.clips) {
      if (attempted.has(clip.id)) continue;
      // Keep the server's eight-slot queue bounded, including microphone jobs.
      if (pendingClips.size >= 8 || socket.bufferedAmount > 1024 * 1024) break;
      attempted.add(clip.id);
      try {
        const raw = atob(native.readClip(clip.id));
        if (!raw.length || raw.length % 2 || raw.length > 16000 * 15 * 2) throw new Error('Invalid or unreadable audio snippet.');
        const bytes = Uint8Array.from(raw, c => c.charCodeAt(0));
        const pcm16 = new DataView(bytes.buffer);
        const pcm = new Float32Array(bytes.length / 2);
        for (let i = 0; i < pcm.length; i++) pcm[i] = pcm16.getInt16(i * 2, true) / 32768;
        const seconds = pcm.length / 16000;
        const id = nextClipId++;
        nativeIds.set(id, clip.id);
        addClip(id, Math.round(seconds * 100) / 100);
        const label = pendingClips.get(id).row.querySelector('.clip-label');
        label.textContent = `App audio · ${seconds.toFixed(1)}s · ${new Date(clip.createdAt).toLocaleTimeString()}`;
        for (let offset = 0; offset < pcm.length; offset += 16000) socket.send(pcm.slice(offset, offset + 16000).buffer);
        socket.send(JSON.stringify({type: 'parseLastNSeconds', id, seconds}));
      } catch (error) {
        localError = `${error.message} The original audio is kept for another attempt after this session.`;
      }
    }
  }

  function poll() {
    try {
      const value = state();
      if (audioInput === 'playback' && active && androidForeground && !endingSession && !starting) importAvailable(value);
      render(value);
    } catch (error) { message.textContent = error.message; }
  }

  async function begin(capture) {
    if (starting || endingSession || savingSession) return;
    starting = true;
    localError = '';
    start.disabled = modelSelect.disabled = computeSelect.disabled = true;
    audioInput = 'playback';
    microphoneGeneration++;
    hasAudio = false;
    recall.disabled = true;
    try {
      await flushMicrophone();
      await releaseMicrophone();
      await openSessionConnection();
      active = true;
      if (capture) native.requestStart(floating.checked, scaleInput.valueAsNumber);
      start.textContent = 'Stop & save';
    } catch (error) {
      localError = error.message;
      if (!sessionOpen) {
        audioInput = 'microphone';
        active = false;
        socket?.close();
        modelSelect.disabled = computeSelect.disabled = fixedModel;
      }
    } finally {
      starting = false;
      start.disabled = false;
      poll();
    }
  }

  button.onclick = () => {
    if (lastState.running || lastState.requesting) { native.stop(); poll(); }
    else begin(true);
  };
  review.onclick = () => begin(false);
  window.deviceAudio = {
    poll,
    capture(seconds) { native.capture(seconds); },
    result(result) {
      const id = nativeIds.get(result.id);
      if (id && !result.error) completed.add(id);
    },
    async finish() {
      draining = true;
      native.stop();
      try {
        // stop invalidates consent immediately; queued native disk writes still drain.
        let value;
        do { await delay(); value = state(); } while (value.requesting || value.running || value.pendingSaves > 0);
        while (socket?.readyState === WebSocket.OPEN) {
          value = state();
          importAvailable(value);
          if (!value.clips.some(clip => !attempted.has(clip.id))) break;
          await delay();
        }
      } finally { draining = false; poll(); }
    },
    saved() {
      native.ackClips(JSON.stringify([...completed]));
      attempted.clear(); completed.clear(); nativeIds.clear();
    },
  };
  setInterval(() => { if (!draining) poll(); }, 700);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
  poll();
}
initDeviceAudio();
