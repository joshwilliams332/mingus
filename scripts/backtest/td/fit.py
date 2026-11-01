import pickle, sys, math, json, numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import brier_score_loss, log_loss
S = sys.argv[1]; rows = pickle.load(open(f"{S}/td/rows.pkl", "rb"))
POS = ("QB", "RB", "WR", "TE")
def X(r):
    sh = lambda a, b: r[a] / r[b] if r[b] > 0 else 0
    return [r["car"], r["tgt"], r["rz_car"], r["rz_tgt"], r["td"], sh("rz_car", "t_rz_car"), sh("rz_tgt", "t_rz_tgt"),
            math.log(r["imp"] / r["imp_avg"]), *[1.0 if r["pos"] == p else 0.0 for p in POS]]
NAMES = ["car", "tgt", "rz_car", "rz_tgt", "td_rate", "rz_car_share", "rz_tgt_share", "log_implied", *POS]
tr = [r for r in rows if r["season"] <= 2025]; te = [r for r in rows if r["season"] == 2026]
Xtr, ytr = np.array([X(r) for r in tr]), np.array([r["y"] for r in tr]); Xte, yte = np.array([X(r) for r in te]), np.array([r["y"] for r in te])
cvz = np.zeros(len(tr))
for s in range(2021, 2026):
    m = np.array([r["season"] == s for r in tr]); sc2 = StandardScaler().fit(Xtr[~m]); l2 = LogisticRegression(max_iter=3000).fit(sc2.transform(Xtr[~m]), ytr[~m])
    cvz[m] = l2.decision_function(sc2.transform(Xtr[m]))
cvp = 1 / (1 + np.exp(-cvz))
sc = StandardScaler().fit(Xtr); lr = LogisticRegression(max_iter=3000).fit(sc.transform(Xtr), ytr)
pl = LogisticRegression().fit(cvz.reshape(-1, 1), ytr); a, b = pl.coef_[0][0], pl.intercept_[0]
pte = 1 / (1 + np.exp(-(a * lr.decision_function(sc.transform(Xte)) + b)))
print("slim: 2021-25 out-of-season brier %.4f logloss %.4f | 2026 brier %.4f logloss %.4f" % (brier_score_loss(ytr, cvp), log_loss(ytr, cvp), brier_score_loss(yte, pte), log_loss(yte, pte)))
for lo in (0, .1, .2, .3, .4, .5, .6, .7):
    m = (cvp >= lo) & (cvp < lo + .1)
    if m.sum(): print(f"  {lo:.1f}: {m.sum():5d} {cvp[m].mean():.3f} {ytr[m].mean():.3f}")
# by position on 2026
for p in POS:
    m = np.array([r["pos"] == p for r in te])
    if m.sum(): print(p, m.sum(), "pred %.3f actual %.3f" % (pte[m].mean(), yte[m].mean()))
# fold standardization into raw-feature weights for pure-Python use: z = a*(w.(x-mu)/sd + c) + b
w = lr.coef_[0] / sc.scale_; c = lr.intercept_[0] - float(np.sum(lr.coef_[0] * sc.mean_ / sc.scale_))
coef = {"names": NAMES, "weights": [round(float(a * x), 6) for x in w], "intercept": round(float(a * c + b), 6),
        "half_life": 4, "trained": "2021-2025 nflverse, weeks 4+, >=3 prior games; Platt-scaled out of season",
        "test_2026": {"brier": round(float(brier_score_loss(yte, pte)), 4), "n": int(len(yte))}}
json.dump(coef, open(f"{S}/td/td_model.json", "w"), indent=1)
print(json.dumps(coef))
