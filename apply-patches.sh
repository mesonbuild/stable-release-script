#!/bin/bash
# vim: set sts=4 sw=4 et :

set -e

PATCHDIR=$1

[[ -d $PATCHDIR ]]

[[ -d $PATCHDIR/done ]] || mkdir "$PATCHDIR/done"

ls -1 "$PATCHDIR"/*.patch | while read i; do
    echo "$i"
    git am "$PATCHDIR/$i" || { git am --abort && break; }
    mv "$PATCHDIR/$i" "$PATCHDIR/done"
done
