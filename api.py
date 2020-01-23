#!/usr/bin/env python3

import os
import sys
import requests
from pathlib import Path
from configparser import ConfigParser

from github import Github

if len(sys.argv) < 2:
    print('Usage: {} <milestone number>'.format(sys.argv[0]))
    sys.exit(1)

if not os.path.isfile('config.cfg'):
    print('Copy config-example.cfg to config.cfg and set the values in it')
    sys.exit(1)

parser = ConfigParser()
parser.read('config.cfg')
config = parser['default']

# Instance!
g = Github(config['api-token'])
# Repository!
repo = g.get_repo(config['repo'])

# Milestone number for stable release
m = repo.get_milestone(int(sys.argv[1]))

print("Fetching issue list for milestone {} ...".format(m.title), end="", flush=True)

issues = {}
pulls = {}
for issue in repo.get_issues(milestone=m, state="closed"):
    if issue.pull_request:
        pulls[issue.closed_at] = issue
    else:
        issues[issue.closed_at] = issue

print("found {} closed issues and {} merged pull-requests".format(len(issues), len(pulls)))
os.makedirs('patches', exist_ok=True)

# Get all closed issues (PRs) starting from oldest to newest
for d, issuepr in pulls.items():
    # Name the patch
    url = issuepr.pull_request.patch_url
    fname = Path('{}--PR{}'.format(d.strftime('%Y-%m-%dT%H%M%S'), os.path.basename(url)))
    fdir = Path('patches')
    foname = fdir / fname
    if foname.exists() or (fdir / 'done' / fname).exists():
        print("{} already exists, skipping".format(fname))
        continue
    # Fetch the patch if required
    print("Fetching patch for PR #{} ...".format(issuepr.number), end="", flush=True)
    r = requests.get(url)
    if r.status_code != 200:
        # Print url for manual checking
        print(" failed: {} ({})".format(r.status_code, url))
        continue
    print(" ok")
    print("Writing to {}".format(foname))
    with open(foname, 'w') as f:
        f.write(r.text)
