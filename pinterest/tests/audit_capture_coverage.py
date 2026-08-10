"""Exhaustive inventory of every request + response handler across ALL pinterest capture files,
cross-checked against what README.md / overviews.md actually document.

Answers "did we actually cover every link, payload, option and functionality in the captures?"
without anyone having to read 900 KB of transcript. Run from the repo root:

    .venv/Scripts/python.exe pinterest/tests/audit_capture_coverage.py

Anything printed under COVERAGE GAPS is either undocumented or documented under a placeholder
name (e.g. `<userId>`) — check before assuming it's a real gap. Re-run whenever a capture is
added, so new endpoints can't sit unnoticed in a transcript nobody re-reads.
"""
import re, json, glob, os, urllib.parse, collections

OURS = {'overviews.md', 'README.md'}          # our own docs are not capture sources
SRC = [f for f in glob.glob('pinterest/endpoints/**/*.md', recursive=True)
       + glob.glob('pinterest/endpoints/**/*.bash', recursive=True)
       + glob.glob('pinterest/endpoints/**/*.json', recursive=True)
       if os.path.basename(f) not in OURS]

docs = ''
for d in ['pinterest/README.md', 'pinterest/endpoints/overviews.md']:
    docs += open(d, encoding='utf-8').read()

print(f'source files: {len(SRC)}')
for f in SRC:
    print(f'  {os.path.getsize(f):>8}  {f}')

req_urls = []            # every literal "Request URL:" in the transcripts
inner_calls = []         # (inner_path, frozenset(payload keys), file)
flat_calls = []          # (path, frozenset(query keys), file)
handlers = collections.Counter()   # endpoint_name from response bodies
handler_src = {}

for f in SRC:
    t = open(f, encoding='utf-8', errors='ignore').read()

    urls = re.findall(r'Request URL:\s*(\S+)', t)
    if f.endswith('.bash'):
        urls += re.findall(r"curl (?:--url )?'([^']+)'", t)
    if f.endswith('.json'):          # scrapfly history export
        try:
            blob = json.loads(t)
            def walk(o):
                if isinstance(o, dict):
                    for k, v in o.items():
                        if k in ('url', 'request_url') and isinstance(v, str) and v.startswith('http'):
                            urls.append(v)
                        walk(v)
                elif isinstance(o, list):
                    for v in o:
                        walk(v)
            walk(blob)
        except Exception as e:
            print(f'  ! could not parse {f}: {e}')

    for u in urls:
        p = urllib.parse.urlparse(u)
        if 'pinterest' not in p.netloc:
            continue
        req_urls.append((f, u))
        qs = urllib.parse.parse_qs(p.query)
        if 'data' in qs:
            try:
                d = json.loads(qs['data'][0])
                opt = d.get('options', {})
                inner_calls.append((opt.get('url'), frozenset((opt.get('data') or {}).keys()), f))
            except Exception:
                pass
        else:
            flat_calls.append((p.path, frozenset(qs.keys()), f))

    for m in re.finditer(r'"endpoint_name"\s*:\s*"([^"]+)"', t):
        handlers[m.group(1)] += 1
        handler_src.setdefault(m.group(1), os.path.basename(f))

print(f'\ntotal pinterest request URLs found: {len(req_urls)}')

print('\n=== FLAT REST: every path x param-set combination ===')
by_path = collections.defaultdict(set)
for path, keys, f in flat_calls:
    by_path[path].add(keys)
for path in sorted(by_path):
    allk = set().union(*by_path[path])
    print(f'\n  {path}   ({len(by_path[path])} distinct param sets)')
    print(f'    union of params: {sorted(allk)}')
    for ks in sorted(by_path[path], key=len):
        opt = sorted(allk - ks)
        print(f'      · {sorted(ks)}' + (f'   [absent: {opt}]' if opt else ''))

print('\n=== ApiResource: every inner url x payload-key-set ===')
by_inner = collections.defaultdict(set)
for inner, keys, f in inner_calls:
    by_inner[inner].add(keys)
for inner in sorted(by_inner, key=lambda x: (x or '')):
    print(f'\n  {inner}   ({len(by_inner[inner])} distinct payload shapes)')
    for ks in sorted(by_inner[inner], key=len):
        print(f'      · {sorted(ks)}')

print('\n=== RESPONSE HANDLERS (endpoint_name) — the server-side truth ===')
for h, n in handlers.most_common():
    documented = h in docs
    print(f'  {"OK " if documented else "GAP"}  {h:42} x{n:<3} first seen in {handler_src[h]}')

print('\n=== COVERAGE GAPS vs the docs ===')


def documented(item):
    """The docs use placeholders (<userId>, <CC>/<EVENT>) where captures carry literals.
    Match on the ID-stripped skeleton so those don't read as gaps."""
    if item in docs or item.rstrip('/') in docs:
        return True
    skeleton = re.sub(r'/\d{6,}', '/<id>', item)
    skeleton = re.sub(r'/(US|GB|CA|DE)(/|$)', r'/<cc>\2', skeleton)
    skeleton = re.sub(r'/(SAVE|OUTBOUND_CLICK|ENGAGEMENT)(/|$)', r'/<event>\2', skeleton)
    for line in docs.splitlines():
        norm = re.sub(r'<[A-Za-z]+>', '<id>', line)
        norm = re.sub(r'/<id>(/|\b)', '/<id>\\1', norm)
        if skeleton.replace('<cc>', '<id>').replace('<event>', '<id>') in norm.replace(
                '<CC>', '<id>').replace('<EVENT>', '<id>').replace('<id>', '<id>'):
            return True
    return False


gaps = []
for path in sorted(by_path):
    if not documented(path):
        gaps.append(('flat path', path))
for inner in by_inner:
    if inner and not documented(inner):
        gaps.append(('ApiResource url', inner))
allparams = set()
for path, keys, f in flat_calls:
    allparams |= keys
for k in sorted(allparams):
    if k not in docs:
        gaps.append(('query param', k))
for inner, keys, f in inner_calls:
    for k in keys:
        if k not in docs:
            gaps.append(('payload key', k))
for h in handlers:
    if h not in docs:
        gaps.append(('handler', h))
seen = set()
for kind, item in gaps:
    if (kind, item) in seen:
        continue
    seen.add((kind, item))
    print(f'  MISSING [{kind}] {item}')
if not seen:
    print('  none — every path, param, payload key and handler appears in the docs')
