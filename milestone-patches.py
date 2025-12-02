#!/usr/bin/env python3
#
# Author: Nirbheek Chauhan <nirbheek.chauhan@gmail.com>
# License: Apache-2.0
#
# A tool to fetch all the patches in the PRs for a milestone. Used for making
# stable releases for Meson with `git am <patch>`.
#
# TODO: We currently fetch patches from the PR instead of the patches that went
# into the master branch of the repository. This means that f.ex., squashed PRs
# are not handled correctly. Maybe we should fetch SHAs from the repository
# instead and use `git cherry-pick` instead. It's easier to resolve conflicts
# this way.
from __future__ import annotations

import os
import sys
import argparse
import requests
import typing as T
import subprocess
from pathlib import Path
from configparser import ConfigParser

from github import Github

# Parse arguments
parser = argparse.ArgumentParser(prog="milestone-patches")
parser.add_argument('milestone', type=int,
                    help='Github milestone number')
parser.add_argument('--no-verify', '-n', default=False, action='store_true',
                    help='Don\'t verify that all issues have their fixes milestoned')
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
    q = '''
    query($issue: Int!)
    {
      repository(owner: "mesonbuild", name: "meson") {
        issue(number: $issue) {
          closedByPullRequestsReferences(includeClosedPrs:true, first:10) {
            nodes {
              permalink
              mergeCommit { oid }
            }
          }
        }
      }
    }'''
    resp = issue.requester.graphql_query(q, {'issue': issue.number})
    for i in resp[1]['data']['repository']['issue']['closedByPullRequestsReferences']['nodes']:
        if not i['permalink'].startswith('https://github.com/mesonbuild/meson/pull/'):
            raise AssertionError('Closing PR for issue {} has a url to a different repo: {!r}'.format(issue.number, i['permalink']))
        if not i['mergeCommit']:
            continue
        return i['mergeCommit']['oid']

    if issue.state != 'closed':
        raise AssertionError('Issue {} is not closed, double-check'.format(issue.number))

    print('Issue {} was closed, but could not find associated PR'.format(issue.number))
    return None

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
    print("Fetching issues on the milestone ...", end="", flush=True)
    shas = {}
    for _, issuepr in pulls.items():
        print('.', end='', flush=True)
        for sha in pr_get_repo_shas(issuepr, repo):
            if sha in shas:
                raise AssertionError('Tried to add commit {} from PR {!r}, but already have the same commit from PR {!r}'.format(sha, issuepr, shas[sha]))
            shas[sha] = issuepr
    print(" done.", flush=True);

    print("Verifying that all issues have an associated pull request ...", end="", flush=True)
    for _, issue in issues.items():
        print('.', end='', flush=True)
        sha = issue_get_closing_sha(issue)
        if not sha:
            continue
        if sha not in shas:
            print('WARNING: Could not find a PR that closed issue {!r} ({}'.format(issue, sha))
    print(" done.", flush=True);

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
    print('.', end='')
    if issue.pull_request:
        as_pr = issue.as_pull_request()
        if not as_pr.merged:
            print('\nPull request {} was closed, not merged. Remove it from the milestone.'.format(as_pr.html_url))
            exit(1)
        pulls[issue.closed_at] = issue
    else:
        issues[issue.closed_at] = issue

print("found {} closed issues and {} merged pull-requests".format(len(issues), len(pulls)))
os.makedirs('patches', exist_ok=True)

if len(issues) > 0 and not options.no_verify:
    verify_issue_fixes_are_milestoned(repo, issues, pulls)

def pr_to_patch(shas: T.List[str]) -> T.Optional[str]:
    resp = []
    for sha in reversed(shas):
        url = repo.get_commit(sha).html_url + '.patch'
        r = requests.get(url)
        if r.status_code != 200:
            # Print url for manual checking
            print(" failed: {} ({})".format(r.status_code, url))
            return
        cherrypick = f'--trailer=(cherry picked from commit {sha})=deleteme'
        gitfilter = subprocess.Popen(['git', 'interpret-trailers', cherrypick], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        patch = gitfilter.communicate(r.text)[0]
        patch = patch.replace('=deleteme:', '')
        resp.append(patch)
        resp.append('')

    print(' ok')
    return '\n'.join(resp) + '\n'



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
    shas = pr_get_repo_shas(issuepr, repo)
    patch = pr_to_patch(shas)
    if not patch:
        continue
    print("Writing to {}".format(foname))
    with open(foname, 'w') as f:
        f.write(patch)
