#!/usr/bin/env python3
"""Compare game rollover output to Python reference byte-for-byte.

Runs rollover reference on PRE_DIR, compares each .V20 to POST_DIR.
Prints first 20 mismatching offsets per file, exits nonzero on any difference.

Usage: check_roll.py PRE_DIR POST_DIR [--seed N]
"""
import sys
import os
import glob
sys.path.insert(0, '/home/will/tlrb2/tools')

from m4.rollover import rollover


def compare_dirs(pre_dir, post_dir, seed=1):
    """Run reference on pre, compare V20s to post. Return mismatches dict."""
    ref_out = '/tmp/check_roll_ref'
    os.makedirs(ref_out, exist_ok=True)

    # Run reference
    print(f'Running rollover reference on {pre_dir} with seed={seed}')
    rollover(pre_dir, ref_out, seed=seed, cfg={'progress': True, 'retire': True})

    # Compare files
    mismatches = {}
    for ref_v20 in sorted(glob.glob(os.path.join(ref_out, '*.V20'))):
        name = os.path.basename(ref_v20)
        post_v20 = os.path.join(post_dir, name)

        if not os.path.exists(post_v20):
            print(f'ERROR: {name} missing in POST_DIR')
            mismatches[name] = ['missing']
            continue

        with open(ref_v20, 'rb') as f:
            ref = f.read()
        with open(post_v20, 'rb') as f:
            post = f.read()

        if ref == post:
            print(f'{name}: OK')
            continue

        # Find mismatches
        diffs = []
        for off in range(min(len(ref), len(post))):
            if ref[off] != post[off]:
                diffs.append(off)

        if len(diffs) == 0 and len(ref) != len(post):
            diffs.append(f'SIZE: {len(ref)} vs {len(post)}')
        else:
            diffs = diffs[:20]

        mismatches[name] = diffs
        print(f'{name}: MISMATCH at offsets {diffs[:5]} ... ({len(diffs)} total)')

    return mismatches


def main(args):
    if len(args) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    pre_dir = args[0]
    post_dir = args[1]
    seed = int(args[args.index('--seed') + 1]) if '--seed' in args else 1

    mismatches = compare_dirs(pre_dir, post_dir, seed)

    if any(mismatches.values()):
        print(f'\nFAIL: {len(mismatches)} files with mismatches')
        sys.exit(1)
    else:
        print('\nPASS: all files match reference')
        sys.exit(0)


if __name__ == '__main__':
    main(sys.argv[1:])
