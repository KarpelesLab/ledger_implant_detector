"""Minimal S-expression reader/writer for KiCad files."""
import re

_tok = re.compile(r'\s*(\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+)', re.S)


class Sym(str):
    """Unquoted atom."""


def parse(text):
    stack, cur = [], []
    for m in _tok.finditer(text):
        t = m.group(1)
        if t == '(':
            stack.append(cur)
            cur = []
        elif t == ')':
            done = cur
            cur = stack.pop()
            cur.append(done)
        elif t.startswith('"'):
            cur.append(t[1:-1].replace('\\"', '"').replace('\\\\', '\\'))
        else:
            cur.append(Sym(t))
    return cur[0]


def q(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def dump(node, ind=0):
    if not isinstance(node, list):
        if isinstance(node, Sym):
            return str(node)
        if isinstance(node, (int, float)):
            return fmt(node)
        return q(node)
    pad = '\t' * ind
    if all(not isinstance(x, list) for x in node):
        return pad + '(' + ' '.join(dump(x) for x in node) + ')'
    head = []
    rest = []
    for i, x in enumerate(node):
        if isinstance(x, list):
            rest = node[i:]
            break
        head.append(dump(x))
    out = pad + '(' + ' '.join(head)
    for x in rest:
        out += '\n' + (dump(x, ind + 1) if isinstance(x, list) else '\t' * (ind + 1) + dump(x))
    return out + '\n' + pad + ')'


def fmt(v):
    if isinstance(v, int):
        return str(v)
    s = ('%.4f' % v).rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s


def find(node, key):
    return [x for x in node if isinstance(x, list) and x and x[0] == key]


def find1(node, key):
    r = find(node, key)
    return r[0] if r else None
