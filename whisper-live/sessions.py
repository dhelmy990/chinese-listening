"""Completed listening sessions, word identities, and cumulative save counts."""
from contextlib import closing
from datetime import datetime
import sqlite3
from uuid import UUID


def validate_session(body):
    try:
        if not isinstance(body, dict) or str(UUID(body['id'])) != body['id']:
            raise ValueError()
        start, end = (datetime.fromisoformat(body[key].replace('Z', '+00:00'))
                      for key in ('started_at', 'ended_at'))
        if start.tzinfo is None or end.tzinfo is None or end < start:
            raise ValueError()
        if not isinstance(body['words'], list) or len(body['words']) > 5000:
            raise ValueError()
        words = {}
        for entry in body['words']:
            if not isinstance(entry, dict):
                raise ValueError()
            clean = {}
            for key, limit in [('word', 100), ('pinyin', 500), ('meaning', 4000),
                               ('sentence', 4000), ('translation', 8000)]:
                value = entry.get(key, '')
                if not isinstance(value, str) or len(value) > limit:
                    raise ValueError()
                clean[key] = value.strip()
            level = entry.get('level', 0)
            if not clean['word'] or type(level) is not int or not 0 <= level <= 7:
                raise ValueError()
            clean['level'] = level
            words.setdefault(clean['word'], clean)
        return dict(id=body['id'], started_at=body['started_at'], ended_at=body['ended_at'],
                    words=list(words.values()))
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValueError('Expected a session ID, ordered timestamps, and valid word entries.') from None


def save_session(path, session):
    with closing(sqlite3.connect(path)) as db:
        db.execute('PRAGMA foreign_keys = ON')
        db.executescript('''
            CREATE TABLE IF NOT EXISTS words (
                id INTEGER PRIMARY KEY, word TEXT NOT NULL UNIQUE,
                pinyin TEXT NOT NULL, level INTEGER NOT NULL, meaning TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, started_at TEXT NOT NULL, ended_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS session_words (
                session_id TEXT NOT NULL REFERENCES sessions(id),
                word_id INTEGER NOT NULL REFERENCES words(id),
                sentence TEXT NOT NULL, translation TEXT NOT NULL,
                PRIMARY KEY (session_id, word_id));
            CREATE TABLE IF NOT EXISTS word_save_counts (
                word_id INTEGER PRIMARY KEY REFERENCES words(id),
                save_count INTEGER NOT NULL CHECK (save_count > 0));
        ''')
        with db:
            inserted = db.execute('INSERT OR IGNORE INTO sessions VALUES (?, ?, ?)',
                (session['id'], session['started_at'], session['ended_at'])).rowcount
            if not inserted:
                return  # A retry must never increment counts twice.
            for word in session['words']:
                db.execute('''INSERT INTO words (word, pinyin, level, meaning) VALUES (?, ?, ?, ?)
                    ON CONFLICT(word) DO UPDATE SET
                    pinyin = CASE WHEN excluded.pinyin != '' THEN excluded.pinyin ELSE words.pinyin END,
                    meaning = CASE WHEN excluded.meaning != '' THEN excluded.meaning ELSE words.meaning END''',
                    (word['word'], word['pinyin'], word['level'], word['meaning']))
                word_id = db.execute('SELECT id FROM words WHERE word = ?', (word['word'],)).fetchone()[0]
                db.execute('INSERT INTO session_words VALUES (?, ?, ?, ?)',
                    (session['id'], word_id, word['sentence'], word['translation']))
                db.execute('''INSERT INTO word_save_counts VALUES (?, 1)
                    ON CONFLICT(word_id) DO UPDATE SET save_count = save_count + 1''', (word_id,))


def read_history(path):
    if not path.exists():
        return dict(entries=[], sessions=[])
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        # A read transaction keeps counts and membership in the same snapshot.
        db.execute('BEGIN')
        entries = [dict(row) for row in db.execute('''SELECT words.*, save_count
            FROM words JOIN word_save_counts ON words.id = word_id ORDER BY words.id''')]
        sessions = {row['id']: dict(row, words=[]) for row in db.execute(
            'SELECT * FROM sessions ORDER BY ended_at DESC, id')}
        for row in db.execute('''SELECT session_id, word_id, word, sentence, translation
            FROM session_words JOIN words ON words.id = word_id ORDER BY word_id'''):
            item = dict(row)
            sessions[item.pop('session_id')]['words'].append(item)
        return dict(entries=entries, sessions=list(sessions.values()))
