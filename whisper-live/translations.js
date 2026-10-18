// Two requests at a time keep word lists from flooding the local translation queue.
const translations = (() => {
  const cards = new Map();
  const cache = new Map();
  const queue = [];
  let running = 0;
  const pending = new Set();

  function track(promise) {
    pending.add(promise);
    promise.finally(() => pending.delete(promise));
  }

  function pump() {
    while (running < 2 && queue.length) {
      running++;
      queue.shift()();
    }
    document.querySelector('#translation-count').textContent = `${running + queue.length} pending`;
  }

  function request(text, full = false) {
    const key = `${full ? 'fragment' : 'word'}:${text}`;
    if (cache.has(key)) return cache.get(key);
    const result = new Promise((resolve, reject) => {
      const run = async () => {
        try {
          const response = await fetch('/translate', {
            method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text}),
            signal: AbortSignal.timeout(60000),
          });
          if (!response.ok) throw new Error(await response.text());
          const data = await response.json();
          resolve(data.text || '(No translation returned)');
        } catch (error) {
          cache.delete(key);
          reject(error);
        } finally {
          running--;
          pump();
        }
      };
      if (full) queue.unshift(run); else queue.push(run);
    });
    cache.set(key, result);
    pump();
    return result;
  }

  function render(card) {
    const follow = nearBottom();
    const pill = card.row.querySelector('.translation');
    pill.classList.toggle('revealed', card.revealed);
    pill.setAttribute('aria-pressed', String(card.revealed));
    const content = pill.querySelector('.clip-text');
    content.replaceChildren();
    let pending = false, failed = false;
    if (card.revealed) {
      pending = card.full === null && !card.error;
      failed = Boolean(card.error);
      content.textContent = card.error || card.full || 'Translating full fragment…';
    } else {
      for (const word of card.words) {
        const result = card.results.get(word.word);
        pending ||= !result;
        failed ||= Boolean(result?.error);
        const line = document.createElement('div');
        const label = document.createElement('strong');
        label.lang = 'zh-Hans';
        label.textContent = word.word;
        line.append(label, document.createTextNode(` — ${result?.error || result?.text || 'Translating…'}`));
        content.append(line);
      }
      if (!card.words.length) content.textContent = 'No highlighted words in this clip.';
    }
    pill.dataset.state = pending ? 'processing' : failed ? 'failed' : 'ready';
    pill.querySelector('.badge').textContent = pending ? 'Translating' : failed ? 'Failed' : card.revealed ? 'Full fragment' : 'Words';
    pill.querySelector('.flip-hint').textContent = card.revealed
      ? 'Click to return to words' : 'Click to reveal the full fragment';
    if (follow && !phoneLayout()) timeline.scrollTop = timeline.scrollHeight;
  }

  function update(row, text, words) {
    let card = cards.get(row);
    if (!card) {
      card = {row, text, words: [], results: new Map(), requested: new Set(), full: null, error: '', revealed: false, loadingFull: false};
      cards.set(row, card);
      const pill = row.querySelector('.translation');
      pill.tabIndex = 0;
      pill.setAttribute('role', 'button');
      pill.setAttribute('aria-label', 'Toggle word translations and full fragment');
      pill.onclick = () => {
        card.revealed = !card.revealed;
        if (card.revealed && card.full === null && !card.loadingFull) {
          card.loadingFull = true;
          card.error = '';
          track(request(text, true).then(result => {
            card.full = result;
            vocabulary.translated(row, result);
          }).catch(error => { card.error = error.message; }).finally(() => {
            card.loadingFull = false;
            render(card);
          }));
        }
        render(card);
      };
      pill.onkeydown = event => {
        if (event.code === 'Enter') {
          event.preventDefault();
          event.stopPropagation();
          if (!event.repeat) pill.click();
        }
      };
    }
    card.words = words;
    for (const word of words) {
      if (card.requested.has(word.word)) continue;
      card.requested.add(word.word);
      track(request(word.word).then(text => {
        card.results.set(word.word, {text});
        vocabulary.defined(word.word, text);
      }).catch(error => {
        card.results.set(word.word, {error: error.message});
      }).finally(() => render(card)));
    }
    render(card);
  }

  return {update, async settled() {
    while (pending.size) await Promise.allSettled([...pending]);
  }};
})();
