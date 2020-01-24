#!/usr/bin/env python3

import os
import sys
import argparse
import requests
from pathlib import Path
from configparser import ConfigParser

from github import Github

# Parse arguments
parser = argparse.ArgumentParser(prog="stable-release-tool")
parser.add_argument('milestone', type=int, nargs='?',
                    help='Github milestone number')
parser.add_argument('--verify', '-v', default=False, action='store_true',
                    help='Verify that all issues have their fixes milestoned')
parser.add_argument('--debug', '-d', default=False, action='store_true',
                    help='Print verbose debug output')
options = parser.parse_args()

if not os.path.isfile('config.cfg'):
    print('Copy config-example.cfg to config.cfg and set the values in it')
    sys.exit(1)

parser = ConfigParser()
parser.read('config.cfg')
config = parser['default']

def print_debug(*args, **kwargs):
    if options.debug:
        print(*args, **kwargs)

def issue_get_closing_sha(issue):
    '''
    Github's API does not give us a way to find the PR or commit that closed an
    issue. So we have to parse the event list and hope to find a 'reference'
    event that contains a commit_id and a commit_url that caused that event.
    Then, if it's the one made immediately after the issue was closed and also
    points to our repository, it's probably the right one.
    '''
    events = iter(issue.get_events())
    for e in events:
        # Find the event in which the issue was closed
        if e.event != 'closed':
            continue
        # If the event closing the issue was not a commit, it was closed via PR
        # and the immediate next event is most likely the commit that closed it
        if not e.commit_id:
            e = next(events)
        if not e.commit_id or not e.commit_url:
            raise AssertionError('Issue {} was closed but no commit was associated!?'.format(issue.number))
        if not e.commit_url.startswith('https://api.github.com/repos/mesonbuild/meson/commits/'):
            raise AssertionError('Closing event for issue {} has a url to a different repo: {!r}'.format(issue.number, e.commit_url))
        return e.commit_id
    raise AssertionError('Issue {} is not closed, double-check'.format(issue.number))

def pr_get_merging_sha(issuepr):
    '''
    Find the merge commit SHA that went into the repository. If the PR was
    rebased, this will be the latest commit SHA in that series, and if it was
    squashed, this is that commit SHA.
    '''
    for e in issuepr.get_events():
        # Find the event in which the PR was merged
        if e.event != 'merged':
            continue
        if not e.commit_id or not e.commit_url:
            raise AssertionError('PR {} was merged but no commit was associated!?'.format(issuepr.number))
        if not e.commit_url.startswith('https://api.github.com/repos/mesonbuild/meson/commits/'):
            raise AssertionError('Merged event for PR {} has a url to a different repo: {!r}'.format(issuepr.number, e.commit_url))
        return e.commit_id
    raise AssertionError('PR {} is not merged, double-check'.format(issuepr.number))

def pr_get_repo_shas(issuepr, repo):
    # Fetch and store the commits in the PR
    pr = issuepr.as_pull_request()
    pr_shas = {}
    for c in pr.get_commits():
        pr_shas[(c.commit.author.date, c.commit.message)] = c.sha
    # Find the top commit that has (N = pr.commits) parents from the pull request
    merge_sha = pr_get_merging_sha(issuepr)
    merge_commit = repo.get_commit(merge_sha)
    if len(merge_commit.parents) == 2:
        print_debug('{!r} was merged'.format(issuepr))
        # It's a merge commit, the second parent is the top commit
        top_sha = merge_commit.parents[1].sha
    else:
        # It's either a rebased commit, and hence exactly what we need, or
        # a squashed commit, which is a new commit and impossible to detect.
        top_sha = merge_sha
    # Compare commit message + date of commits in the PR with the commits in
    # the repo to find the list of actual commit SHAs that went into the
    # repository
    repo_shas = []
    for c in repo.get_commits(top_sha)[:pr.commits]:
        key = (c.commit.author.date, c.commit.message)
        if key not in pr_shas:
            print('WARNING: Could not find commit {!r} from PR {!r} -- squashed?'.format(c.commit.message, issuepr))
        repo_shas.append(c.sha)
    if not repo_shas:
        print_debug('{!r} was squashed'.format(issuepr))
        # None of the commits could be found, it's probably a squashed commit. Return it.
        return [top_sha]
    if top_sha == merge_sha:
        print_debug('{!r} was rebased + merged'.format(issuepr))
    return repo_shas

def verify_issue_fixes_are_milestoned(repo, issues, pulls):
    print("Verifying that all issues have an associated pull request...", end="", flush=True)
    shas = {}
    for _, issuepr in pulls.items():
        for sha in pr_get_repo_shas(issuepr, repo):
            if sha in shas:
                raise AssertionError('Tried to add commit {} from PR {!r}, but already have the same commit from PR {!r}'.format(sha, issuepr, shas[sha]))
            shas[sha] = issuepr

    for _, issue in issues.items():
        sha = issue_get_closing_sha(issue)
        if sha not in shas:
            print('WARNING: Could not find a PR that closed issue {!r} ({}'.format(issue, sha))
    print(" done.");

    for sha, issuepr in shas.items():
        print_debug(sha, issuepr)

# Instance!
g = Github(config['api-token'])
# Repository!
repo = g.get_repo(config['repo'])

# Milestone number for stable release
m = repo.get_milestone(options.milestone)

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

if options.verify:
    verify_issue_fixes_are_milestoned(repo, issues, pulls)

# Fetch and write patches from all PRs
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
