"""Coordinate search over the model settings on 2021-2025 (Brier score); writes tuned.json."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pickle, copy, json, time, engine as E
data = pickle.load(open(E.H + 'features.pkl','rb'))
train = [r for s in (2021,2022,2023,2024,2025) for r in data[s]]
P = copy.deepcopy(E.CURRENT)
score = lambda P: E.evaluate(train, P)['brier']
best = score(P); print('start', round(best,5))
grid = {
 'vol': [('half3',None)] + [('exp',h) for h in (1.5,2,3,4,6,8,12)],
 'rate_hl': [None,3,6,10,16],
 'K': [10,20,40,80,150],
 'ds': [0,0.25,0.5,0.75,1.0], 'de': [0,0.25,0.5,0.75,1.0], 'cap': [0.1,0.15,0.25,0.4],
 'is': [0,0.25,0.5,1.0], 'sc': [0,0.005,0.01,0.02],
 'c': [0.88,0.91,0.94,0.97,1.0,1.03], 'k': [1.0,1.15,1.3,1.45,1.6], 'pw': [2,4,8],
}
for rnd in range(3):
    changed = False
    for name, opts in grid.items():
        for v in opts:
            Q = copy.deepcopy(P)
            if name == 'vol': Q['vol'], Q['hl'] = v
            else: Q[name] = v
            s = score(Q)
            if s < best - 1e-6: best, P, changed = s, Q, True
        print(rnd, name, 'best', round(best,5), {k: P[k] for k in ('vol','hl','rate_hl','K','ds','de','cap','is','sc','c','k','pw')})
    # per-stat spread and mean
    for st in E.STATS:
        for cv in (0.2,0.3,0.4,0.5,0.6,0.7,0.8):
            Q = copy.deepcopy(P); Q['cv'][st] = cv; s = score(Q)
            if s < best - 1e-6: best, P, changed = s, Q, True
        for cs in (0.9,0.95,1.0,1.05,1.1):
            Q = copy.deepcopy(P); Q['cs'][st] = cs; s = score(Q)
            if s < best - 1e-6: best, P, changed = s, Q, True
    for skew in ({'rush_yds','rec_yds','rec'}, {'rush_yds','rec_yds','rec','pass_yds'}, {'rec_yds','rec'}):
        Q = copy.deepcopy(P); Q['skew'] = skew; s = score(Q)
        if s < best - 1e-6: best, P, changed = s, Q, True
    print(rnd, 'per-stat', round(best,5), P['cv'], P['cs'], P['skew'])
    if not changed: break
P['skew'] = sorted(P['skew'])
json.dump(P, open(E.H + 'tuned.json','w'), indent=1); print('final', round(best,5))
