"""High-tier signal diagnostic over a backtest result JSON."""
import json
from collections import Counter

d = json.load(open('_bt_result.json', 'r', encoding='utf-8'))

issues = d['issues']
n = len(issues)
print(f"=== Diagnostic over {n} issues ({d.get('ticket_mode')} / scheme_count={d.get('scheme_count')}) ===")
print(f"overall_win_rate={d['overall_win_rate']}  issue_hit_rate={d['issue_hit_rate']}  net_profit={d['net_profit']}")
print()

# 1) High-tier hit-signal frequencies (per issue).
signal_keys = [
    'top3_hit', 'top4_hit',
    'front_4plus_hit', 'front_5_hit',
    'five_plus_zero_hit', 'five_plus_one_hit', 'five_plus_two_hit',
    'four_plus_two_hit', 'back_2plus_hit',
]
print('--- High-tier signal frequency (per issue) ---')
for k in signal_keys:
    c = sum(1 for it in issues if it.get(k))
    print(f"  {k:22s}: {c:3d} / {n}  ({c/n*100:5.1f}%)")
print()

# 2) Best front/back match-count distribution.
front_dist = Counter(int(it.get('front_best_match_count') or 0) for it in issues)
back_dist = Counter(int(it.get('back_best_match_count') or 0) for it in issues)
print('--- Best front match count distribution ---')
for k in sorted(front_dist):
    print(f"  front_best={k}: {front_dist[k]}")
print('--- Best back match count distribution ---')
for k in sorted(back_dist):
    print(f"  back_best={k}: {back_dist[k]}")
print()

# 3) Joint (front_best, back_best) distribution for issues with any signal.
joint = Counter(
    (int(it.get('front_best_match_count') or 0), int(it.get('back_best_match_count') or 0))
    for it in issues
)
print('--- Joint (front_best, back_best) distribution ---')
for key in sorted(joint, key=lambda x: (-x[0], -x[1])):
    fb, bb = key
    print(f"  ({fb}+{bb}): {joint[key]}")
print()

# 4) tuning_profile usage and how often it produced any prize.
profile_runs = Counter()
profile_wins = Counter()
profile_top4 = Counter()
profile_top3 = Counter()
for it in issues:
    p = it.get('tuning_profile') or '<none>'
    profile_runs[p] += 1
    if (it.get('won_count') or 0) > 0:
        profile_wins[p] += 1
    if it.get('top4_hit'):
        profile_top4[p] += 1
    if it.get('top3_hit'):
        profile_top3[p] += 1
print('--- tuning_profile usage ---')
for p, runs in profile_runs.most_common():
    w = profile_wins[p]
    t4 = profile_top4[p]
    t3 = profile_top3[p]
    print(f"  {p:55s} runs={runs:3d}  wins={w:3d}  top4={t4}  top3={t3}")
print()

# 5) issue_power_score distribution (rough top-tier proxy).
buckets = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.01]
labels = [f"[{buckets[i]:.1f},{buckets[i+1]:.1f})" for i in range(len(buckets) - 1)]
counts = [0] * (len(buckets) - 1)
for it in issues:
    s = float(it.get('issue_power_score') or 0.0)
    for i in range(len(buckets) - 1):
        if buckets[i] <= s < buckets[i + 1]:
            counts[i] += 1
            break
print('--- issue_power_score distribution ---')
for lbl, c in zip(labels, counts):
    print(f"  {lbl}: {c}")
print()

# 6) Cost/prize per issue summary (low-tier reliance).
print('--- Issue-level prize summary ---')
print(f"  issues with any win    : {sum(1 for it in issues if (it.get('won_count') or 0) > 0)}")
print(f"  issues with top4 prize : {sum(1 for it in issues if it.get('top4_hit'))}")
print(f"  issues with top3 prize : {sum(1 for it in issues if it.get('top3_hit'))}")
print(f"  issues with front>=4   : {sum(1 for it in issues if (it.get('front_best_match_count') or 0) >= 4)}")
print(f"  issues with front==5   : {sum(1 for it in issues if (it.get('front_best_match_count') or 0) >= 5)}")
print(f"  issues with back==2    : {sum(1 for it in issues if (it.get('back_best_match_count') or 0) >= 2)}")
