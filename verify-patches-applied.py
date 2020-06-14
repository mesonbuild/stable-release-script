#!/usr/bin/env python3

import re
import os
import sys
import glob
import subprocess

mesondir = sys.argv[1]
branch = sys.argv[2]

out = subprocess.check_output(['git', '-C', mesondir, 'tag', '--list', branch + '.*'],
                              universal_newlines=True)
tags = sorted(out.split())
last_tag = tags[-1]

out = subprocess.check_output(['git', '-C', mesondir, 'log', '--oneline', '{}..{}'.format(last_tag, branch)],
                              universal_newlines=True)
# Get the list of commit message subjects (untruncated)
commits = set()
for line in out.split('\n'):
    if not line:
        continue
    commits.add(line.split(' ', maxsplit=1)[1])

patches = glob.glob('patches/done/*.patch')
if not patches:
    print('No patches found?')
    exit(1)

# Get the list of commit message subjects from patches (truncated to 71 cols)
patch_infos = {}
for patch in patches:
    with open(patch, 'r') as f:
        for line in f.readlines():
            if not line.startswith('Subject: [PATCH'):
                continue
            msg = re.split('^Subject: \[PATCH[0-9/ ]*\] ', line, maxsplit=1)[1][:-1]
            patch_infos[msg] = patch

for msg, patch in patch_infos.items():
    if msg in commits:
        continue
    for commit in commits:
        # msg is truncated, so maybe it won't match exactly
        if msg in commit:
            break
    else:
        print('{} in {}'.format(msg, patch))
print('All checked!')
