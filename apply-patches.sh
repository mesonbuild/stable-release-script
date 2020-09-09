#!/bin/bash
# vim: set sts=4 sw=4 et :

set -e

PATCHDIR=$1

[[ -d $PATCHDIR ]] || { echo "Usage: $0 <patchdir>"; exit 1; }

[[ -d $PATCHDIR/done ]] || mkdir "$PATCHDIR/done"

ls -1 "$PATCHDIR"/*.patch | while read i; do
    echo "$i"
    git am "$i" || { git am --abort && break; }
    mv "$i" "$PATCHDIR/done/"
done
