"""Input-only JavaScript runtime helpers; no expected values or checkers."""
import re

SERIALIZER = r'''
function _mci_json(value) {
    if (typeof value === 'bigint') return value.toString();
    if (Array.isArray(value)) return '[' + value.map(_mci_json).join(',') + ']';
    if (value !== null && typeof value === 'object') {
        return '{' + Object.keys(value).map(k => JSON.stringify(k) + ':' + _mci_json(value[k])).join(',') + '}';
    }
    if (typeof value === 'number' && !Number.isFinite(value)) throw new Error('nonfinite output');
    const encoded = JSON.stringify(value);
    if (encoded === undefined) throw new Error('undefined output');
    return encoded;
}
'''

DEQUE = r'''
class Deque {
    constructor(values = []) { this.clear(); for (const value of values) this.pushBack(value); }
    pushBack(value) { this.data.set(this.end++, value); }
    pushFront(value) { this.data.set(--this.start, value); }
    popBack() { if (this.isEmpty()) return undefined; const i = --this.end; const value = this.data.get(i); this.data.delete(i); return value; }
    popFront() { if (this.isEmpty()) return undefined; const i = this.start++; const value = this.data.get(i); this.data.delete(i); return value; }
    front() { return this.data.get(this.start); }
    back() { return this.data.get(this.end - 1); }
    size() { return this.end - this.start; }
    isEmpty() { return this.start === this.end; }
    at(i) { return i >= 0 && i < this.size() ? this.data.get(this.start + i) : undefined; }
    clear() { this.data = new Map(); this.start = 0; this.end = 0; }
}
'''


def helpers(user_code):
    owns_deque = re.search(r'\b(?:class|function|const|let|var)\s+Deque\b', user_code)
    return SERIALIZER + ('' if owns_deque else DEQUE)
