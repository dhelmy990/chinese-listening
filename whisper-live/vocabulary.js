// Selection stays in memory until the user ends the recording session.
const vocabulary = (() => {
  const storageKey = 'chinese-listening-vocabulary-v1';
  const threshold = document.querySelector('#hsk-threshold');
  const message = document.querySelector('#vocabulary-status');
  const dialog = document.querySelector('#vocabulary-dialog');
  const list = document.querySelector('#vocabulary-list');
  const rows = new Map();
  const candidates = new Map();
  const dismissed = new Set();
  const meanings = new Map();
  const wordList = document.querySelector('#word-list');
  const sessionStatus = document.querySelector('#session-status');
  const manual = new Set();
  let session = null, editing = false, pendingSave = null;
  let restoringFocus = false;
  let history = {entries: [], sessions: []};
  const segmenter = new Intl.Segmenter('zh', {granularity: 'word'});
  let hsk = null;
  let maxWordLength = 0;
  let saved = {threshold: 4, entries: []};
  const levelLabel = level => level === 7 ? '7–9' : String(level);

  function readSaved() {
    const raw = localStorage.getItem(storageKey);
    if (raw === null) return {threshold: 4, entries: []};
    const data = JSON.parse(raw);
    if (!Number.isInteger(data.threshold) || data.threshold < 1 || data.threshold > 8 ||
        !Array.isArray(data.entries) || data.entries.some(entry => !entry ||
          !['word', 'pinyin', 'sentence', 'translation'].every(key => typeof entry[key] === 'string') ||
          !Number.isInteger(entry.level) || entry.level < 1 || entry.level > 7 ||
          (entry.meaning !== undefined && typeof entry.meaning !== 'string'))) {
      throw new Error('Invalid vocabulary data');
    }
    return data;
  }

  try {
    saved = readSaved();
  } catch (error) {
    message.textContent = 'Cannot read the saved vocabulary bank. Existing browser data has been left untouched.';
  }
  try {
    threshold.value = localStorage.getItem('chinese-listening-threshold') || saved.threshold;
  } catch { threshold.value = saved.threshold; }
  const band = level => level ? `HSK ${levelLabel(level)}` : 'Unclassified';

  async function loadHistory() {
    try {
      const response = await fetch('/vocabulary', {signal: AbortSignal.timeout(15000)});
      if (!response.ok) throw new Error(await response.text());
      history = await response.json();
      renderBank();
      renderMiddle();
    } catch (error) {
      message.textContent = `Saved vocabulary could not be loaded: ${error.message}`;
    }
  }

  function renderBank() {
    const entries = new Map(saved.entries.map(entry => [entry.word, {...entry, legacy: true}]));
    const contexts = new Map();
    for (const session of history.sessions) {
      for (const word of session.words) if (!contexts.has(word.word_id)) contexts.set(word.word_id, word);
    }
    for (const entry of history.entries) {
      const context = contexts.get(entry.id);
      entries.set(entry.word, {...entry, sentence: context?.sentence || '', translation: context?.translation || ''});
    }
    document.querySelector('#vocabulary-count').textContent = entries.size;
    list.replaceChildren();
    if (!entries.size) list.textContent = 'Selected words are saved when you stop recording.';
    for (const entry of entries.values()) {
      const item = document.createElement('article');
      item.className = 'vocabulary-entry';
      const heading = document.createElement('h3');
      heading.textContent = `${entry.word} · ${entry.pinyin} · ${band(entry.level)}`;
      const count = document.createElement('small');
      count.textContent = entry.legacy ? 'Previously saved in this browser' : `Saved ${entry.save_count} times · Word #${entry.id}`;
      const meaning = document.createElement('p');
      meaning.textContent = entry.meaning || '(Word translation not available)';
      const chinese = document.createElement('p');
      chinese.lang = 'zh-Hans';
      chinese.textContent = entry.sentence;
      const english = document.createElement('p');
      english.lang = 'en';
      english.textContent = entry.translation;
      english.hidden = !entry.translation;
      item.append(heading, count, meaning, chinese, english);
      list.append(item);
    }
    const sessions = document.querySelector('#session-list');
    sessions.replaceChildren();
    for (const session of history.sessions) {
      const details = document.createElement('details');
      const summary = document.createElement('summary');
      summary.textContent = `${new Date(session.ended_at).toLocaleString()} · ${session.words.length} words`;
      details.append(summary);
      for (const word of session.words) {
        const line = document.createElement('p');
        line.textContent = `${word.word} (#${word.word_id}) — ${word.sentence}${word.translation ? ' · ' + word.translation : ''}`;
        details.append(line);
      }
      sessions.append(details);
    }
  }

  function words(text) {
    const parts = [...segmenter.segment(text)];
    const result = [];
    for (let i = 0; i < parts.length; i++) {
      let match = parts[i], combined = match.segment, end = i;
      // Keep HSK compounds intact when Chrome splits them, e.g. 三 + 明治.
      if (match.isWordLike && /^[\p{Script=Han}]+$/u.test(combined)) {
        for (let j = i + 1; j < parts.length && combined.length < maxWordLength; j++) {
          if (!parts[j].isWordLike || !/^[\p{Script=Han}]+$/u.test(parts[j].segment)) break;
          combined += parts[j].segment;
          if (hsk && Object.hasOwn(hsk, combined)) { match = {segment: combined, isWordLike: true}; end = j; }
        }
      }
      result.push(match);
      i = end;
    }
    return result;
  }

  function renderMiddle() {
    const position = wordList.scrollTop;
    const focused = document.activeElement.closest?.('.word-card');
    const focusedWord = focused?.dataset.word;
    const focusedIndex = focused ? [...wordList.children].indexOf(focused) : -1;
    wordList.replaceChildren();
    const counts = new Map(history.entries.map(entry => [entry.word, entry.save_count]));
    for (const entry of candidates.values()) {
      const card = document.createElement('article');
      card.className = 'word-card';
      card.dataset.word = entry.word;
      const content = document.createElement('div');
      const word = document.createElement('strong');
      word.lang = 'zh-Hans';
      word.textContent = entry.word;
      const pinyin = document.createElement('p');
      pinyin.lang = 'zh-Latn';
      pinyin.textContent = entry.pinyin;
      const label = document.createElement('small');
      label.textContent = `${band(entry.level)} · Saved ${counts.get(entry.word) || 0} times`;
      const dismiss = document.createElement('button');
      dismiss.textContent = '×';
      dismiss.setAttribute('aria-label', `Dismiss ${entry.word}`);
      dismiss.disabled = !editing;
      dismiss.onclick = () => { manual.delete(entry.word); dismissed.add(entry.word); refresh(); };
      content.append(word, pinyin, label);
      card.append(content, dismiss);
      wordList.append(card);
    }
    if (!candidates.size) wordList.textContent = 'Highlighted words and pinyin will appear here.';
    wordList.scrollTop = position;
    document.querySelector('#word-count').textContent = candidates.size;
    sessionStatus.textContent = editing ? `${candidates.size} words will be saved when you stop recording.`
      : 'Words are saved at the end of each recording session.';
    if (focused) {
      const remaining = [...wordList.querySelectorAll('.word-card')];
      const target = remaining.find(card => card.dataset.word === focusedWord)
        || remaining[Math.min(focusedIndex, remaining.length - 1)];
      restoreFocus(target?.querySelector('button') || wordList);
    }
  }

  function restoreFocus(element) {
    // Rebuilding a word list is not a user focus change and must not cancel a hold.
    restoringFocus = true;
    try { element.focus({preventScroll: true}); }
    finally { restoringFocus = false; }
  }

  function refresh() {
    candidates.clear();
    for (const [row, data] of rows) {
      const focusedWord = row.contains(document.activeElement) ? document.activeElement : null;
      const fragment = document.createDocumentFragment();
      const selected = new Map();
      for (const {segment, isWordLike} of words(data.text)) {
        if (!isWordLike) {
          fragment.append(document.createTextNode(segment));
          continue;
        }
        const match = hsk && Object.hasOwn(hsk, segment) ? hsk[segment] : null;
        const highlighted = !dismissed.has(segment) && (manual.has(segment) || (match && match[0] >= Number(threshold.value)));
        const [level, pinyin] = match || [0, ''];
        const mark = document.createElement('span');
        mark.className = highlighted ? 'selectable-word hsk-word' : 'selectable-word';
        mark.dataset.word = segment;
        mark.textContent = segment;
        mark.title = `${band(level)}${pinyin ? ' · ' + pinyin : ''} · Click to ${highlighted ? 'unhighlight' : 'highlight'}`;
        mark.tabIndex = editing ? 0 : -1;
        mark.setAttribute('role', 'button');
        mark.setAttribute('aria-pressed', String(Boolean(highlighted)));
        mark.setAttribute('aria-disabled', String(!editing));
        const sessionId = session?.id;
        mark.onclick = () => {
          if (!editing || session?.id !== sessionId) return;
          if (highlighted) { manual.delete(segment); dismissed.add(segment); }
          else { manual.add(segment); dismissed.delete(segment); }
          refresh();
        };
        mark.onkeydown = event => {
          if (event.code === 'Enter' && !event.repeat) { event.preventDefault(); mark.click(); }
        };
        fragment.append(mark);
        if (!highlighted) continue;
        const entry = {word: segment, level, pinyin, sentence: data.text,
                       translation: data.translation, meaning: meanings.get(segment) || ''};
        selected.set(segment, entry);
        if (!candidates.has(segment)) candidates.set(segment, entry);
      }
      const content = row.querySelector('.pill .clip-text');
      const focusIndex = [...content.querySelectorAll('.selectable-word')].indexOf(focusedWord);
      content.replaceChildren(fragment);
      if (focusIndex >= 0 && editing) {
        const target = content.querySelectorAll('.selectable-word')[focusIndex];
        if (target) restoreFocus(target);
      }
      data.onWords([...selected.values()]);
    }
    renderMiddle();
  }

  threshold.onchange = () => {
    try { localStorage.setItem('chinese-listening-threshold', threshold.value); }
    catch { message.textContent = 'The HSK preference could not be saved in this browser.'; }
    if (editing) refresh();
  };
  document.querySelector('#open-vocabulary').onclick = () => { dialog.showModal(); loadHistory(); };
  document.querySelector('#close-vocabulary').onclick = () => dialog.close();
  renderBank();
  renderMiddle();
  loadHistory();

  const ready = fetch('/data/hsk.json', {signal: AbortSignal.timeout(15000)}).then(response => {
    if (!response.ok) throw new Error('HSK data unavailable');
    return response.json();
  }).then(data => {
    hsk = data;
    maxWordLength = Math.max(...Object.keys(hsk).map(word => word.length));
    refresh();
  }).catch(() => {
    message.textContent = 'HSK data could not load. Refresh to retry; transcription and translation still work.';
  });

  return {
    get restoringFocus() { return restoringFocus; },
    beginSession() {
      rows.clear();
      candidates.clear();
      dismissed.clear();
      manual.clear();
      session = {id: crypto.randomUUID(), started_at: new Date().toISOString()};
      editing = true;
      pendingSave = null;
      threshold.disabled = false;
      renderMiddle();
    },
    endSession() {
      session.ended_at = new Date().toISOString();
      editing = false;
      threshold.disabled = true;
      refresh();
    },
    async saveSession() {
      if (!pendingSave) {
        await ready;
        refresh();
        await translations.settled();
        pendingSave = {...session, words: [...candidates.values()].map(entry => ({...entry}))};
      }
      const response = await fetch('/sessions', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(pendingSave), signal: AbortSignal.timeout(15000),
      });
      if (!response.ok) throw new Error(await response.text());
      message.textContent = `Session saved: ${pendingSave.words.length} words.`;
      session = null;
      threshold.disabled = false;
      await loadHistory();
    },
    annotate(row, text, onWords) {
      rows.set(row, {text, translation: '', onWords});
      refresh();
    },
    defined(word, meaning) {
      meanings.set(word, meaning);
      if (candidates.has(word)) candidates.get(word).meaning = meaning;
    },
    translated(row, translation) {
      const data = rows.get(row);
      if (!data) return;
      data.translation = translation;
      for (const entry of candidates.values()) if (entry.sentence === data.text) entry.translation = translation;
    },
  };
})();
