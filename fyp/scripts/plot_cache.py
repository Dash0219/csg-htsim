"""
Plot cache simulation results from results.csv.

Generates two figures:
  1. Suppression rate vs cache capacity (one line per policy)
  2. Redundancy rate vs cache capacity (overhead fraction)

Usage:
  python plot_cache.py results.csv
  python plot_cache.py results.csv --out figures/
  python plot_cache.py results.csv --show
"""

import csv
import sys
import argparse
import os
from collections import defaultdict

# ---------------------------------------------------------------------------
# Load CSV
# ---------------------------------------------------------------------------

def load(path):
    rows = []
    required = {
        'cache',
        'capacity',
        'total',
        'suppression_rate',
        'forward_rate',
        'redundancy_rate',
        'necessary_forwards',
        'redundant_forwards',
        'evictions',
    }

    with open(path, newline='') as f:
        reader = csv.DictReader(f)
        cols = set(reader.fieldnames or [])
        missing = sorted(required - cols)
        if missing:
            raise ValueError(
                f"Input file '{path}' is not a valid cache results CSV. "
                f"Missing required columns: {', '.join(missing)}. "
                "Hint: pass the results CSV (e.g., .../results_*.csv), not a run log (.out)."
            )

        for row in reader:
            cache_name = row['cache']
            cache_name = NAME_ALIASES.get(cache_name, cache_name)
            rows.append({
                'cache':           cache_name,
                'capacity':        float(row['capacity']),   # -1 = infinite
                'total':           int(row['total']),
                'suppression':     float(row['suppression_rate']),
                'forward':         float(row['forward_rate']),
                'redundancy':      float(row['redundancy_rate']),
                'necessary':       int(row['necessary_forwards']),
                'redundant':       int(row['redundant_forwards']),
                'evictions':       int(row['evictions']),
            })
    return rows


def group_by_policy(rows):
    """Split rows into: baselines (capacity=-1) and bounded (capacity>0)."""
    baselines = [r for r in rows if r['capacity'] < 0]
    bounded   = [r for r in rows if r['capacity'] > 0]

    # Group bounded rows by cache name
    policies = defaultdict(list)
    for r in bounded:
        policies[r['cache']].append(r)
    # Sort each policy by capacity
    for name in policies:
        policies[name].sort(key=lambda r: r['capacity'])

    return baselines, dict(policies)


def parse_policy_list(raw):
    if not raw:
        return []
    items = []
    for part in raw.split(','):
        name = part.strip()
        if name:
            items.append(name)
    return items


def parse_markers(raw_markers):
    markers = []
    for raw in raw_markers or []:
        text = raw.strip()
        if not text:
            continue
        if '=' not in text:
            raise ValueError(f"Invalid --marker '{raw}': expected LABEL=VALUE")
        label, value_text = text.rsplit('=', 1)
        label = label.strip()
        value_text = value_text.strip()
        if not label:
            raise ValueError(f"Invalid --marker '{raw}': empty label")
        try:
            value = int(value_text)
        except ValueError as exc:
            raise ValueError(f"Invalid --marker '{raw}': VALUE must be an integer") from exc
        if value <= 0:
            raise ValueError(f"Invalid --marker '{raw}': VALUE must be > 0")
        markers.append((label, value))
    return markers


def filter_rows(rows, include_policies=None, exclude_policies=None):
    include = set(include_policies or [])
    exclude = set(exclude_policies or [])

    out = []
    for row in rows:
        name = row['cache']
        if include and name not in include:
            continue
        if name in exclude:
            continue
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

NAME_ALIASES = {
    'InfiniteLastPath': 'Infinite',
    'LRULastPath': 'LRU',
    'LRULastPathTTL': 'LRUTTL',
    'AdmissionFilterLRU': 'OneHitWonderLRU',
    'PITCollapsedLRU': 'PITCache',
    'TimingBloomLRU': 'TimeLimitedBloomLRU',
}

POLICY_GROUPS = {
    # Eviction-policy family.
    'LRU': 'Eviction-policy family',

    # Admission and filtering family.
    'OneHitWonderLRU': 'Admission and filtering family',
    'PendingAdmissionLRU': 'Admission and filtering family',
    'PITCache': 'Admission and filtering family',
    'AdaptiveAdmissionLRU': 'Admission and filtering family',
    'TimeLimitedBloomLRU': 'Admission and filtering family',
    'TinyLFULRU': 'Admission and filtering family',
    'TinyCacheLRU': 'Admission and filtering family',

    # Freshness and TTL family.
    'LRUTTL': 'Freshness and TTL family',
    'FreshnessInvalidationLRU': 'Freshness and TTL family',
    'CacheINTFreshnessLRU': 'Freshness and TTL family',
    'FlowLifetimeAdaptiveTTL': 'Freshness and TTL family',
}

GROUP_ORDER = [
    'Eviction-policy family',
    'Admission and filtering family',
    'Freshness and TTL family',
    'Other',
]

GROUP_COLORS = {
    # More separated hues for group-level readability.
    'Eviction-policy family': '#ff7f0e',
    'Admission and filtering family': '#2ca02c',
    'Freshness and TTL family': '#e31a1c',
    'Other': '#7f7f7f',
}

POLICY_MARKERS = {
    'Infinite': 'o',
    'LRU': 's',
    'OneHitWonderLRU': 'P',
    'PendingAdmissionLRU': 'o',
    'PITCache': '|',
    'AdaptiveAdmissionLRU': 'X',
    'TimeLimitedBloomLRU': '*',
    'TinyLFULRU': '1',
    'TinyCacheLRU': '3',
    'LRUTTL': '>',
    'FreshnessInvalidationLRU': 'd',
    'CacheINTFreshnessLRU': '2',
    'FlowLifetimeAdaptiveTTL': 'x',
}


def policy_group(name):
    # Sweep output names include forms like LRUTtl(0.5ms).
    if name.startswith('LRUTtl('):
        return 'Freshness and TTL family'
    canonical = NAME_ALIASES.get(name) or name
    return POLICY_GROUPS.get(canonical, 'Other')


def _group_rank(name):
    g = policy_group(name)
    try:
        return GROUP_ORDER.index(g)
    except ValueError:
        return len(GROUP_ORDER)


def build_policy_styles(policy_names):
    """Assign styles where color encodes group and marker encodes policy."""
    auto_markers = ['o', 's', '^', 'v', 'D', 'P', 'X', '*', 'h', '<', '>', '8']
    linestyles = ['-', '--', '-.', ':']
    per_group_auto_idx = defaultdict(int)

    ordered = sorted(policy_names, key=lambda n: (_group_rank(n), n))
    styles = {}
    present_groups = []

    for name in ordered:
        group = policy_group(name)
        if group not in present_groups:
            present_groups.append(group)

        auto_idx = per_group_auto_idx[group]
        marker = POLICY_MARKERS.get(name, auto_markers[auto_idx % len(auto_markers)])
        linestyle = linestyles[(auto_idx // len(auto_markers)) % len(linestyles)]
        per_group_auto_idx[group] += 1

        styles[name] = dict(
            color=GROUP_COLORS.get(group, GROUP_COLORS['Other']),
            marker=marker,
            linestyle=linestyle,
            group=group,
        )

    return styles, ordered, present_groups


def make_plots(
    rows,
    out_dir='.',
    show=False,
    prefix='',
    scale_to_infinite=False,
    scale_factor=1.25,
    max_concurrency=0,
    unique_flows=0,
    switch_budget=0,
    markers=None,
    show_limit_labels=True,
):
    try:
        import matplotlib
        if not show:
            matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.lines import Line2D
    except ImportError:
        print("matplotlib not installed.  Run: pip install matplotlib", file=sys.stderr)
        sys.exit(1)

    baselines, policies = group_by_policy(rows)
    policy_styles, ordered_policies, present_groups = build_policy_styles(policies.keys())

    limits = []
    if max_concurrency and max_concurrency > 0:
        limits.append((max_concurrency, 'max concurrency', 'black', '--'))
    if unique_flows and unique_flows > 0:
        limits.append((unique_flows, 'unique flows', 'tab:gray', '-.'))
    if switch_budget and switch_budget > 0:
        limits.append((switch_budget, 'switch budget', 'tab:orange', ':'))
    if markers:
        marker_styles = [
            ('tab:blue', '--'),
            ('tab:green', '-.'),
            ('tab:red', ':'),
            ('tab:purple', '--'),
            ('tab:brown', '-.'),
            ('tab:pink', ':'),
        ]
        for idx, (label, value) in enumerate(markers):
            color, linestyle = marker_styles[idx % len(marker_styles)]
            limits.append((value, label, color, linestyle))

    def draw_limits(ax):
        for x, label, color, linestyle in limits:
            ax.axvline(x, linestyle=linestyle, color=color, linewidth=1.2, alpha=0.85)
            if show_limit_labels:
                ax.text(
                    x,
                    ax.get_ylim()[1] * 0.98,
                    f"{label}={x}",
                    rotation=90,
                    va='top',
                    ha='right',
                    fontsize=8,
                    color=color,
                    alpha=0.9,
                )

    # ---- Figure 1: suppression rate --------------------------------------
    fig1, ax1 = plt.subplots(figsize=(9.8, 5.4))
    for name in ordered_policies:
        group = policies[name]
        xs = [r['capacity'] for r in group]
        ys = [100 * r['suppression'] for r in group]
        style = dict(policy_styles[name])
        style.pop('group', None)
        ax1.plot(
            xs,
            ys,
            label=name,
            linewidth=2.0,
            markersize=6,
            markerfacecolor='white',
            markeredgewidth=1.2,
            **style,
        )

    ax1.set_xscale('log', base=2)
    ax1.set_xlabel('Cache capacity (flow slots)', fontsize=12)
    ax1.set_ylabel('Suppression rate (%)', fontsize=12)
    ax1.set_title('Sink cache: suppression rate vs capacity', fontsize=13)
    if scale_to_infinite:
        max_sup = max(([100 * r['suppression'] for g in policies.values() for r in g] + [1.0]))
        inf_sup = None
        for b in baselines:
            if b['cache'] == 'Infinite':
                inf_sup = 100 * b['suppression']
                break
        if inf_sup is None and baselines:
            inf_sup = 100 * max(b['suppression'] for b in baselines)
        if inf_sup is None:
            inf_sup = max_sup
        y_hi = max(1.0, max_sup * 1.05, inf_sup * scale_factor)
        ax1.set_ylim(0, y_hi)
    else:
        ax1.set_ylim(0, 105)
    ax1.grid(True, which='both', alpha=0.3)
    draw_limits(ax1)
    main_leg1 = ax1.legend(fontsize=8, ncol=2, title='Policy (marker)')
    group_handles_1 = []
    for group_name in present_groups:
        group_handles_1.append(
            Line2D([0], [0], color=GROUP_COLORS.get(group_name, GROUP_COLORS['Other']), linewidth=2.8, label=group_name)
        )
    group_leg1 = ax1.legend(
        handles=group_handles_1,
        title='Policy group (color)',
        loc='lower right',
        fontsize=8,
    )
    ax1.add_artist(main_leg1)
    ax1.add_artist(group_leg1)

    # Draw infinite baselines after plot to get correct xlim
    for b in baselines:
        val = 100 * b['suppression']
        ax1.axhline(val, linestyle='dotted', color='grey', linewidth=1)
        ax1.text(ax1.get_xlim()[1] * 0.98, val - 3,
                 f"{b['cache']} ({val:.1f}%)", fontsize=7, color='grey', ha='right')

    fig1.tight_layout()
    p1_name = f"{prefix}_suppression_vs_capacity.png" if prefix else 'suppression_vs_capacity.png'
    p1 = os.path.join(out_dir, p1_name)
    fig1.savefig(p1, dpi=150)
    print(f"Saved {p1}")

    # ---- Figure 2: redundancy rate ---------------------------------------
    fig2, ax2 = plt.subplots(figsize=(9.8, 5.4))
    for name in ordered_policies:
        group = policies[name]
        xs = [r['capacity'] for r in group]
        ys = [100 * r['redundancy'] for r in group]
        style = dict(policy_styles[name])
        style.pop('group', None)
        ax2.plot(
            xs,
            ys,
            label=name,
            linewidth=2.0,
            markersize=6,
            markerfacecolor='white',
            markeredgewidth=1.2,
            **style,
        )

    ax2.set_xscale('log', base=2)
    ax2.set_xlabel('Cache capacity (flow slots)', fontsize=12)
    ax2.set_ylabel('Redundancy rate (% of forwards that are wasted)', fontsize=12)
    ax2.set_title('Sink cache: redundancy overhead vs capacity', fontsize=13)
    if scale_to_infinite:
        all_red = [100 * r['redundancy'] for g in policies.values() for r in g]
        if all_red:
            y_min = min(0.0, min(all_red) * 1.1)
            y_max = max(1.0, max(all_red) * scale_factor)
            # Keep a small band around zero to make near-zero regimes visible.
            if y_max < 10:
                y_max = max(10.0, y_max)
            ax2.set_ylim(y_min, y_max)
        else:
            ax2.set_ylim(-5, 105)
    else:
        ax2.set_ylim(-5, 105)
    ax2.axhline(0, linestyle='dotted', color='grey', linewidth=1)
    draw_limits(ax2)
    ax2.grid(True, which='both', alpha=0.3)
    main_leg2 = ax2.legend(fontsize=8, ncol=2, title='Policy (marker)')
    group_handles_2 = []
    for group_name in present_groups:
        group_handles_2.append(
            Line2D([0], [0], color=GROUP_COLORS.get(group_name, GROUP_COLORS['Other']), linewidth=2.8, label=group_name)
        )
    group_leg2 = ax2.legend(
        handles=group_handles_2,
        title='Policy group (color)',
        loc='upper right',
        fontsize=8,
    )
    ax2.add_artist(main_leg2)
    ax2.add_artist(group_leg2)
    fig2.tight_layout()
    p2_name = f"{prefix}_redundancy_vs_capacity.png" if prefix else 'redundancy_vs_capacity.png'
    p2 = os.path.join(out_dir, p2_name)
    fig2.savefig(p2, dpi=150)
    print(f"Saved {p2}")

    if show:
        plt.show()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('csv', nargs='?', default='results.csv')
    ap.add_argument('--out', default='.', help='Output directory for PNG files')
    ap.add_argument('--prefix', default='', help='Prefix for output PNG filenames (default: inferred from CSV basename)')
    ap.add_argument('--show', action='store_true', help='Display plots interactively')
    ap.add_argument('--scale-to-infinite', action='store_true',
                    help='Scale y-axes relative to observed infinite/data ranges instead of fixed 0-100')
    ap.add_argument('--scale-factor', type=float, default=1.25,
                    help='Headroom multiplier used when --scale-to-infinite is set (default: 1.25)')
    ap.add_argument('--max-concurrency', type=int, default=0,
                    help='Optional vertical marker at this cache capacity (for max concurrent flows)')
    ap.add_argument('--unique-flows', type=int, default=0,
                    help='Optional vertical marker at this cache capacity (total unique flows)')
    ap.add_argument('--switch-budget', type=int, default=0,
                    help='Optional vertical marker for practical switch cache budget')
    ap.add_argument('--marker', action='append', default=[],
                    help='Optional marker in form LABEL=VALUE (repeatable)')
    ap.add_argument('--hide-limit-labels', action='store_true',
                    help='Draw limit marker lines without text labels')
    ap.add_argument('--include-policies', default='',
                    help='Comma-separated policy names to keep (default: keep all)')
    ap.add_argument('--exclude-policies', default='',
                    help='Comma-separated policy names to hide')
    ap.add_argument('--hide-redundant-pairs', action='store_true',
                    help='Hide near-duplicate policies (AdaptiveAdmissionLRU, OnlineAdaptiveAdmissionLRU)')
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    try:
        rows = load(args.csv)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    include_policies = parse_policy_list(args.include_policies)
    exclude_policies = parse_policy_list(args.exclude_policies)
    try:
        markers = parse_markers(args.marker)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    if args.hide_redundant_pairs:
        exclude_policies.extend([
            'AdaptiveAdmissionLRU',
        ])

    rows = filter_rows(rows, include_policies=include_policies, exclude_policies=exclude_policies)
    print(f"Loaded {len(rows)} rows from {args.csv} after policy filtering")
    if not rows:
        print("Error: no rows remain after policy include/exclude filtering", file=sys.stderr)
        sys.exit(2)
    prefix = args.prefix
    if not prefix:
        stem = os.path.splitext(os.path.basename(args.csv))[0]
        prefix = stem
    make_plots(
        rows,
        out_dir=args.out,
        show=args.show,
        prefix=prefix,
        scale_to_infinite=args.scale_to_infinite,
        scale_factor=args.scale_factor,
        max_concurrency=args.max_concurrency,
        unique_flows=args.unique_flows,
        switch_budget=args.switch_budget,
        markers=markers,
        show_limit_labels=(not args.hide_limit_labels),
    )
