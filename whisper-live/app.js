const start = document.querySelector('#start');
const stop = document.querySelector('#stop');
const status = document.querySelector('#status');
const clips = document.querySelector('#clips');
const timeline = document.querySelector('#timeline');
const pendingClips = new Map();
let nextClipId = 0;
let translationsPending = 0;
const level = document.querySelector('#level');
const modelSelect = document.querySelector('#model-select');
const computeSelect = document.querySelector('#compute-select');
const recall = document.querySelector('#recall');
const scaleInput = document.querySelector('#scale');
let context, stream, source, mic, socket, flush;
let active = false, failed = false;
let hasAudio = false;
let holdStartedAt = null, holdTimer, holdFactor, holdSource;

function heldSeconds() {
  return Math.round(Math.min(15, 1 + (performance.now() - holdStartedAt) / 1000 * holdFactor) * 100) / 100;
}

function cancelHold() {
  if (holdStartedAt === null) return;
  holdStartedAt = null;
  clearInterval(holdTimer);
  if (holdSource !== 'keyboard' && recall.hasPointerCapture(holdSource)) recall.releasePointerCapture(holdSource);
  holdSource = null;
  showListeningStatus();
}

function showListeningStatus() {
  document.querySelector('#pending-count').textContent = `${pendingClips.size} pending`;
  if (active && holdStartedAt === null) status.textContent = 'Listening. Hold Space whenever you miss something.';
}

function nearBottom() {
  return timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight < 64;
}

function addClip(id, seconds) {
  const follow = nearBottom();
  const row = document.createElement('div');
  row.className = 'clip-row';
  row.dataset.clipId = id;
  row.innerHTML = `<div class="panel-cell"><article class="pill" data-state="queued">
    <div class="pill-heading"><span class="clip-label"></span><span class="badge">Queued</span></div>
    <p class="clip-text" lang="zh-Hans">Waiting to transcribe…</p>
    <p class="pinyin" lang="zh-Latn" aria-label="Pinyin" hidden></p>
    <details hidden><summary>Timing &amp; model</summary><small class="timing"></small></details>
  </article></div><div class="panel-cell"><article class="pill translation" data-state="queued">
    <div class="pill-heading"><span>English</span><span class="badge">Waiting</span></div>
    <p class="clip-text" lang="en">Waiting for transcription…</p>
    <details hidden><summary>Timing &amp; model</summary><small class="timing"></small></details>
  </article></div>`;
  row.querySelector('.clip-label').textContent = `Clip ${id + 1} · last ${seconds}s`;
  pendingClips.set(id, {row, startedAt: performance.now()});
  document.querySelector('#empty-state').hidden = true;
  clips.append(row);
  document.querySelector('#clip-count').textContent = clips.children.length;
  if (follow) timeline.scrollTop = timeline.scrollHeight;
  showListeningStatus();
}

function updateClip(result) {
  const clip = pendingClips.get(result.id);
  if (!clip) return;
  const follow = nearBottom();
  const pill = clip.row.querySelector('.pill');
  const processing = result.status === 'processing';
  pill.dataset.state = processing ? 'processing' : result.error ? 'failed' : 'ready';
  pill.querySelector('.badge').textContent = processing ? 'Transcribing' : result.error ? 'Failed' : 'Ready';
  pill.querySelector('.clip-text').textContent = processing ? 'Transcribing…'
    : result.error || result.text || '(No speech recognized)';
  if (!processing) {
    if (!result.error) {
      pill.querySelector('.pinyin').textContent = result.pinyin || '';
      pill.querySelector('.pinyin').hidden = !result.pinyin;
      pill.querySelector('details').hidden = false;
      pill.querySelector('.timing').textContent = `${result.model} / ${result.compute_type} · Audio ${result.audio_seconds}s · Processing ${result.compute_seconds}s · Server delay ${result.delay_seconds}s · Release to result ${((performance.now() - clip.startedAt) / 1000).toFixed(2)}s`;
    }
    pendingClips.delete(result.id);
    if (!result.error && result.text?.trim()) {
      translateClip(clip.row, result.text);
    } else {
      const translation = clip.row.querySelector('.translation');
      translation.dataset.state = 'skipped';
      translation.querySelector('.badge').textContent = 'Skipped';
      translation.querySelector('.clip-text').textContent = result.error ? 'No transcription to translate.' : '(No speech recognized)';
    }
    showListeningStatus();
  }
  if (follow) timeline.scrollTop = timeline.scrollHeight;
}

async function translateClip(row, text) {
  const pill = row.querySelector('.translation');
  pill.dataset.state = 'processing';
  pill.querySelector('.badge').textContent = 'Translating';
  pill.querySelector('.clip-text').textContent = 'Translating…';
  document.querySelector('#translation-count').textContent = `${++translationsPending} pending`;
  const startedAt = performance.now();
  try {
    const response = await fetch('/translate', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text}),
    });
    if (!response.ok) throw new Error(await response.text());
    const result = await response.json();
    const follow = nearBottom();
    pill.dataset.state = 'ready';
    pill.querySelector('.badge').textContent = 'Ready';
    pill.querySelector('.clip-text').textContent = result.text || '(No translation returned)';
    pill.querySelector('details').hidden = false;
    pill.querySelector('.timing').textContent = `${result.model} · Processing ${result.compute_seconds}s · Translation wait ${((performance.now() - startedAt) / 1000).toFixed(2)}s`;
    if (follow) timeline.scrollTop = timeline.scrollHeight;
  } catch (error) {
    const follow = nearBottom();
    pill.dataset.state = 'failed';
    pill.querySelector('.badge').textContent = 'Failed';
    pill.querySelector('.clip-text').textContent = error.message;
    if (follow) timeline.scrollTop = timeline.scrollHeight;
  } finally {
    document.querySelector('#translation-count').textContent = `${--translationsPending} pending`;
  }
}

function failPending(message) {
  for (const id of [...pendingClips.keys()]) updateClip({id, error: message});
}

function parseLastNSeconds(seconds = 1) {
  if (!active || !hasAudio || socket?.readyState !== WebSocket.OPEN) return;
  if (typeof seconds !== 'number' || !(seconds >= 0.1 && seconds <= 15)) {
    status.textContent = 'Enter a duration between 0.1 and 15 seconds.';
    return;
  }
  cancelHold();
  const id = nextClipId++;
  addClip(id, seconds);
  // Flush the worklet's current batch before marking the clip boundary on the server.
  mic.port.postMessage({type: 'parseLastNSeconds', id, seconds});
}

function beginHold(source) {
  if (!active || !hasAudio || holdStartedAt !== null) return false;
  holdFactor = scaleInput.valueAsNumber;
  if (!Number.isFinite(holdFactor) || holdFactor < 0.1) {
    status.textContent = 'Enter a scaling factor of at least 0.1.';
    scaleInput.reportValidity();
    return false;
  }
  holdSource = source;
  holdStartedAt = performance.now();
  const showSelection = () => {
    status.textContent = `Release to transcribe the last ${heldSeconds()}s (maximum 15s).`;
  };
  showSelection();
  holdTimer = setInterval(showSelection, 100);
  return true;
}

function finishHold() {
  if (holdStartedAt === null) return;
  const seconds = heldSeconds();
  cancelHold();
  parseLastNSeconds(seconds);
}

recall.onpointerdown = event => {
  if (event.button !== 0) return;
  event.preventDefault();
  if (beginHold(event.pointerId)) recall.setPointerCapture(event.pointerId);
};
recall.onpointerup = event => { if (holdSource === event.pointerId) finishHold(); };
recall.onpointercancel = recall.onlostpointercapture = cancelHold;
// Enter and assistive-technology clicks retain a one-second quick action.
recall.onclick = event => { if (event.detail === 0) parseLastNSeconds(1); };
document.addEventListener('keydown', event => {
  if (event.code === 'Escape' || event.code === 'Tab') cancelHold();
  if (event.code !== 'Space' || !active ||
      event.ctrlKey || event.altKey || event.metaKey || event.shiftKey ||
      (event.target !== recall && event.target.closest('button, input, textarea, select, summary, [contenteditable]'))) return;
  event.preventDefault();
  if (!event.repeat) beginHold('keyboard');
});
document.addEventListener('keyup', event => {
  if (event.code !== 'Space' || holdSource !== 'keyboard' || holdStartedAt === null) return;
  event.preventDefault();
  finishHold();
});
window.addEventListener('blur', cancelHold);
document.addEventListener('focusin', cancelHold);
document.addEventListener('visibilitychange', () => { if (document.hidden) cancelHold(); });

async function releaseMicrophone() {
  cancelHold();
  stream?.getTracks().forEach(track => track.stop());
  source?.disconnect();
  mic?.disconnect();
  if (context && context.state !== 'closed') await context.close();
  context = stream = source = mic = null;
  level.value = 0;
}

async function checkModel() {
  try {
    const data = await fetch('/status').then(response => response.json());
    modelSelect.value = data.model;
    computeSelect.value = data.compute_type;
    for (const option of computeSelect.options) option.disabled = !data.compute_types.includes(option.value);
    document.querySelector('#model-detail').textContent = `· ${data.device} · 简体中文`;
    computeSelect.disabled = modelSelect.disabled = data.loading || data.busy;
    start.disabled = !data.ready || data.busy;
    if (data.error) {
      status.textContent = `Model failed: ${data.error}. Choose a model or representation to retry.`;
      return;
    }
    if (data.ready && !data.busy) {
      start.disabled = false;
      status.textContent = 'Ready. Allow microphone access when prompted.';
      return;
    }
    status.textContent = data.loading ? 'Loading model. First use downloads its weights…' : 'Microphone is busy in another tab.';
  } catch (error) {
    status.textContent = error.message;
  }
  setTimeout(checkModel, 1500);
}

modelSelect.onchange = computeSelect.onchange = async () => {
  computeSelect.disabled = modelSelect.disabled = start.disabled = true;
  status.textContent = 'Loading selected model and representation…';
  try {
    const response = await fetch('/model', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({model: modelSelect.value, compute_type: computeSelect.value}),
    });
    if (!response.ok) throw new Error(await response.text());
  } catch (error) {
    status.textContent = error.message;
    setTimeout(checkModel, 1500);
    return;
  }
  checkModel();
};

start.onclick = async () => {
  computeSelect.disabled = modelSelect.disabled = start.disabled = true;
  failed = false;
  hasAudio = false;
  status.textContent = 'Opening microphone…';
  try {
    stream = await navigator.mediaDevices.getUserMedia({audio: {channelCount: 1, echoCancellation: true, noiseSuppression: true}});
    context = new AudioContext({sampleRate: 16000});
    if (context.sampleRate !== 16000) throw new Error('This browser cannot capture at 16 kHz. Try Chrome.');
    await context.resume();
    await context.audioWorklet.addModule('/mic.js');
    socket = new WebSocket(`ws://${location.host}/listen`);
    await new Promise((resolve, reject) => {
      socket.onopen = resolve;
      socket.onerror = () => reject(new Error('Could not connect. Model may be busy in another tab.'));
    });
    let finished = false;
    active = true;
    socket.onmessage = event => {
      const result = JSON.parse(event.data);
      if (result.done) { finished = true; return; }
      if (result.error && result.id === undefined) {
        failed = true;
        active = false;
        recall.disabled = stop.disabled = true;
        status.textContent = result.error;
        failPending(result.error);
        socket.close();
        return;
      }
      updateClip(result);
    };
    socket.onclose = async () => {
      const unexpected = active || !finished;
      active = false;
      recall.disabled = stop.disabled = true;
      await releaseMicrophone();
      failPending('Connection closed before this clip finished.');
      computeSelect.disabled = modelSelect.disabled = start.disabled = false;
      if (!failed) status.textContent = unexpected ? 'Connection closed. Check the server and try again.' : 'Stopped. Transcriptions finished; any translations will continue.';
    };
    source = context.createMediaStreamSource(stream);
    mic = new AudioWorkletNode(context, 'microphone');
    mic.port.onmessage = event => {
      if (event.data === 'flushed') { flush?.(); return; }
      if (event.data?.type === 'parseLastNSeconds') {
        if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(event.data));
        return;
      }
      const samples = event.data;
      let energy = 0;
      for (const sample of samples) energy += sample * sample;
      level.value = Math.sqrt(energy / samples.length);
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(samples.buffer);
        hasAudio = true;
        if (active) recall.disabled = false;
      }
    };
    source.connect(mic);
    mic.connect(context.destination); // The worklet outputs silence, so there is no feedback.
    stop.disabled = false;
    start.blur();
    showListeningStatus();
  } catch (error) {
    failed = true;
    active = false;
    socket?.close();
    await releaseMicrophone();
    computeSelect.disabled = modelSelect.disabled = start.disabled = false;
    recall.disabled = stop.disabled = true;
    failPending(error.message);
    status.textContent = error.message;
  }
};

stop.onclick = async () => {
  active = false;
  cancelHold();
  recall.disabled = stop.disabled = true;
  status.textContent = 'Microphone stopped. Finishing queued clips…';
  source.disconnect();
  stream.getTracks().forEach(track => track.stop());
  await new Promise(resolve => {
    flush = resolve;
    mic.port.postMessage('flush');
    setTimeout(resolve, 500);
  });
  await releaseMicrophone();
  if (socket.readyState === WebSocket.OPEN) socket.send('stop');
};
checkModel();
