#!/bin/bash
# compare_matrix.sh OUTDIR BASE_LABEL FIX_LABEL [lenient]
#
# The fix must not make any case wrong that was right before, and (unless
# lenient) must fix at least one.  Prints the counts and the case ids that
# moved either way.
set -u
outdir=$1
base=$2
fix=$3
mode=${4:-strict}

nbase=$(wc -l < "$outdir/wrong-$base.txt" | tr -d ' ')
nfix=$(wc -l < "$outdir/wrong-$fix.txt" | tr -d ' ')
newly_wrong=$(comm -13 "$outdir/wrong-$base.txt" "$outdir/wrong-$fix.txt")
fixed=$(comm -23 "$outdir/wrong-$base.txt" "$outdir/wrong-$fix.txt")

echo "=== $base: $nbase wrong -> $fix: $nfix wrong"
echo "--- fixed by $fix ($(echo -n "$fixed" | grep -c .)):"
echo "${fixed:-(none)}"
echo "--- newly wrong with $fix ($(echo -n "$newly_wrong" | grep -c .)):"
echo "${newly_wrong:-(none)}"
echo "--- still wrong with $fix:"
cat "$outdir/wrong-$fix.txt"
[ -z "$newly_wrong" ] || { echo "FAIL: $fix makes cases wrong that $base got right"; exit 1; }
if [ "$mode" = strict ]; then
	[ "$nfix" -lt "$nbase" ] || { echo "FAIL: $fix does not fix anything"; exit 1; }
fi
echo "OK: no new wrong results"
