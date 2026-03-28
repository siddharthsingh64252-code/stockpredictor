def calculate_points(predicted: float, actual: float) -> int:
    if actual == 0:
        return 0
    diff_pct = abs(predicted - actual) / actual * 100
    if diff_pct == 0:      return 1000
    elif diff_pct <= 0.1:  return 950
    elif diff_pct <= 0.25: return 900
    elif diff_pct <= 0.5:  return 800
    elif diff_pct <= 1.0:  return 700
    elif diff_pct <= 2.0:  return 500
    elif diff_pct <= 3.0:  return 350
    elif diff_pct <= 5.0:  return 200
    elif diff_pct <= 7.0:  return 100
    elif diff_pct <= 10.0: return 50
    else:                  return 0


def points_breakdown_text() -> str:
    return (
        "📊 *Points Breakdown:*\n\n"
        "🎯 Exact match  → *1000 pts*\n"
        "✅ Within 0.1%  → *950 pts*\n"
        "✅ Within 0.25% → *900 pts*\n"
        "✅ Within 0.5%  → *800 pts*\n"
        "✅ Within 1%    → *700 pts*\n"
        "✅ Within 2%    → *500 pts*\n"
        "✅ Within 3%    → *350 pts*\n"
        "✅ Within 5%    → *200 pts*\n"
        "✅ Within 7%    → *100 pts*\n"
        "✅ Within 10%   → *50 pts*\n"
        "❌ Beyond 10%   → *0 pts*"
    )