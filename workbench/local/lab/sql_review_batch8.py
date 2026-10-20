"""Reviewed finite SQL controllers for exact rates and current text contracts."""
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

from local.lab import source_guard

REFERENCE_FILE = Path(__file__).with_name('data') / 'reviewed_sql_batch8_references.json'
QIDS = {1934, 3374, 3436, 3451}
CONFIRM_PROFILE = 'exact-rational-confirmation-half-up2-v1'
WORD_PROFILE = 'official-space-words-nonletter-hyphen-20261017-v1'
IP_PROFILE = 'official-one-to-three-digit-octets-20261017-v1'
MAX_ROWS = 2000
MAX_TEXT = 1000
MAX_TOTAL_TEXT = 20000
LETTERS = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ')
source_guard.register(__file__)
source_guard.register(REFERENCE_FILE)


def fingerprint():
    source_guard.check()
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__), REFERENCE_FILE)}


def valid(qid, args):
    if qid not in QIDS:
        return None
    if type(args) is not dict or set(args) != {'tables'} or type(args['tables']) is not dict:
        return False
    schemas = {1934: {'Signups': ['user_id', 'time_stamp'], 'Confirmations': ['user_id', 'time_stamp', 'action']},
               3374: {'user_content': ['content_id', 'content_text']},
               3436: {'Users': ['user_id', 'email']}, 3451: {'logs': ['log_id', 'ip', 'status_code']}}[qid]
    if set(args['tables']) != set(schemas):
        return False
    for name, columns in schemas.items():
        table = args['tables'][name]
        if type(table) is not dict or table.get('columns') != columns or type(table.get('rows')) is not list:
            return False
        if len(table['rows']) > MAX_ROWS:
            raise ValueError('reviewed SQL scope is at most 2000 rows per table; larger legal inputs remain unverified')
        if any(type(row) is not list or len(row) != len(columns) for row in table['rows']):
            return False
    integer = lambda v: type(v) is int and -(2**31) <= v < 2**31
    if qid == 1934:
        def stamp(value):
            if type(value) is not str or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}', value):
                raise ValueError('DATETIME representation outside reviewed canonical-second scope; other valid forms remain unverified')
            parsed = datetime.fromisoformat(value)
            if parsed.year < 1000:
                raise ValueError('DATETIME year outside reviewed native scope; remains unverified')
            return parsed
        users, requests = set(), set()
        for user, timestamp in args['tables']['Signups']['rows']:
            if not integer(user) or user in users:
                return False
            stamp(timestamp)
            users.add(user)
        for user, timestamp, action in args['tables']['Confirmations']['rows']:
            if not integer(user) or user not in users or action not in ('confirmed', 'timeout'):
                return False
            key = (user, stamp(timestamp))
            if key in requests:
                return False
            requests.add(key)
        return True
    seen, total = set(), 0
    table = args['tables'][next(iter(schemas))]
    for row in table['rows']:
        ident, text = row[:2]
        if not integer(ident) or ident in seen:
            return False
        seen.add(ident)
        if type(text) is not str:
            raise ValueError('NULL/nonstring text family outside reviewed scope; remains unverified')
        total += len(text)
        if len(text) > MAX_TEXT or total > MAX_TOTAL_TEXT:
            raise ValueError('reviewed text scope: 1000 characters per row and 20000 per input; longer legal inputs remain unverified')
        if qid == 3374 and not set(text) <= LETTERS | set(' \\@-/^,'):
            return False
        if qid == 3436:
            if not text.isascii():
                raise ValueError('non-ASCII email families outside reviewed character scope; remain unverified, not claimed forbidden by the statement')
            if text.count('@') == 1 and text.endswith('.com'):
                local, domain = text[:-4].split('@')
                if not local or not domain:
                    raise ValueError('empty email segments require explicit contract review; remain unverified')
        if qid == 3451:
            if not integer(row[2]):
                return False
            if not re.fullmatch(r'[0-9]{1,3}(?:\.[0-9]{1,3})*', text):
                return False  # Explicit current official octet guarantee, not an inferred IPv4 validity test.
    return True


def convert_word(word):
    if not word or word[0] not in LETTERS:
        return word
    pieces = word.split('-')
    if len(pieces) > 1 and all(piece and set(piece) <= LETTERS for piece in pieces):
        return '-'.join(piece[0].upper() + piece[1:].lower() for piece in pieces)
    return word[0].upper() + word[1:].lower()


def answer(qid, args):
    if valid(qid, args) is not True:
        raise ValueError('reviewed SQL input rules rejected input')
    if qid == 1934:
        counts = defaultdict(lambda: [0, 0])
        for user, timestamp, action in args['tables']['Confirmations']['rows']:
            counts[user][0] += action == 'confirmed'
            counts[user][1] += 1
        rows = []
        for user, timestamp in args['tables']['Signups']['rows']:
            confirmed, total = counts[user]
            quotient, remainder = divmod(confirmed * 100, total) if total else (0, 0)
            cents = quotient + (bool(total) and 2 * remainder >= total)
            rows.append([user, cents / 100])
        return {'columns': ['user_id', 'confirmation_rate'], 'rows': rows}
    if qid == 3374:
        rows = [[ident, text, ' '.join(convert_word(word) for word in text.split(' '))]
                for ident, text in args['tables']['user_content']['rows']]
        return {'columns': ['content_id', 'original_text', 'converted_text'], 'rows': rows}
    if qid == 3436:
        rows = []
        for ident, email in args['tables']['Users']['rows']:
            if email.count('@') != 1 or not email.endswith('.com'):
                continue
            local, domain = email[:-4].split('@')
            if local and domain and set(local) <= LETTERS | set('0123456789_') and set(domain) <= LETTERS:
                rows.append([ident, email])
        return {'columns': ['user_id', 'email'], 'rows': sorted(rows)}
    counts = Counter()
    for ident, ip, status in args['tables']['logs']['rows']:
        pieces = ip.split('.')
        if len(pieces) != 4 or any(int(p) > 255 or len(p) > 1 and p[0] == '0' for p in pieces):
            counts[ip] += 1
    return {'columns': ['ip', 'invalid_count'],
            'rows': [[ip, n] for ip, n in sorted(counts.items(), key=lambda x: (x[1], x[0]), reverse=True)]}


def reference(qid, language):
    if qid not in QIDS:
        return None
    source_guard.check()
    record = json.loads(REFERENCE_FILE.read_text(encoding='utf8'))
    return record['programs'].get(str(qid), {}).get(language)


def note(qid):
    scope = ' Scope: at most 2000 rows per table; text inputs at most 1000 characters per row and 20000 characters total. Larger legal inputs remain unverified.'
    return {1934: 'q1934 profile ' + CONFIRM_PROFILE + ': count confirmed/total exactly and round nonnegative rationals half-up to two places; no requests means zero. Binary Python round is not equivalent. Canonical second-resolution DATETIME and native years 1000..9999 are the reviewed transport scope.',
            3374: 'q3374 profile ' + WORD_PROFILE + ': current official words are space-delimited. A word starting with a non-English letter is wholly unchanged. Only nonempty letter-only parts joined by single hyphens are capitalized partwise; otherwise capitalize the first letter and lowercase remaining letters. Preserve spaces and special characters. Older statement contracts require explicit migration.',
            3436: 'q3436: exactly one @, ASCII letters/digits/underscore before it, nonempty ASCII letter-only domain, and exact lowercase .com suffix. No trailing whitespace/newline. Non-ASCII and empty-segment families remain unverified, not asserted forbidden by the statement.',
            3451: 'q3451 profile ' + IP_PROFILE + ': current official guarantee permits only 1..3 digits per octet. Inspect EVERY octet for >255 or leading zero, or a segment count other than four. Single 0 is allowed. Nonnumeric, empty and >3-digit octets are excluded by that explicit guarantee.'}.get(qid, '') + (scope if qid in QIDS else '')


def scope(qid):
    return {'max_text_length': MAX_TEXT, 'max_total_text_length': MAX_TOTAL_TEXT,
            'datetime_transport': 'canonical_seconds_year_1000_to_9999' if qid == 1934 else None,
            'character_scope': 'ascii_nonempty_email_segments' if qid == 3436 else
                               'official_allowed_characters' if qid == 3374 else
                               'official_one_to_three_digit_octets' if qid == 3451 else None}
