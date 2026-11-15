import collections, sys
from pathlib import Path
sys.path.insert(0, ".")
from constructor.batch import FIELDS, load_questions, tier_of
from constructor.ingest import load_cached, best_source
from constructor.answer import answer
from constructor.scoring import is_correct
from constructor.split import split_of
Q = Path(sys.argv[1])
res = collections.defaultdict(lambda: [0, 0, 0])  # questions, answered, right
cache = {}
for r in load_questions(Q):
    p = r[FIELDS["drawing"]]
    if p not in cache:
        cache[p] = load_cached(best_source(Q.parent / p))
    d = cache[p]
    if d is None:
        continue  # not read yet: scored only on what has been read
    a = answer(d, r[FIELDS["question"]])
    key = (split_of(p), tier_of(p))
    res[key][0] += 1
    if a.value is not None:
        res[key][1] += 1
        res[key][2] += is_correct(a.value, r[FIELDS["answer"]], r[FIELDS["unit"]], a.unit)
drawings = collections.Counter((split_of(p), tier_of(p)) for p, d in cache.items() if d is not None)
for k in sorted(res):
    n, ans, ok = res[k]
    print(f"{k[0]:<8} {k[1]:<38} drawings {drawings[k]:>5}  questions {n:>6}  right {ok/n:6.1%}  answered {ans/n:6.1%}")
