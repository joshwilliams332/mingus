"""Build backtest features for 2021-2026 and score the current settings per season."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pickle, time, engine as E
t=time.time(); data={}
for s in (2021,2022,2023,2024,2025,2026):
    data[s]=E.features(s); print(s, len(data[s]), round(time.time()-t,1))
pickle.dump(data, open(E.H + 'features.pkl','wb'))
for s in data:
    r=E.evaluate(data[s], E.CURRENT); print(s, 'current model brier %.4f logloss %.4f'%(r['brier'],r['logloss']), {k:round(v['brier']-v['coin'],4) for k,v in r['by_stat'].items()})
