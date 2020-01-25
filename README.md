Script to fetch patches for stable release branches

Uses the `github` python3 module

```sh
$ pip3 install --user pygithub
```

Copy the config over
```sh
$ cp config-example.cfg config.cfg
```

Generate a personal access token by going to https://github.com/settings/tokens/new,
then add it to the config file

```ini
api-token = replace_this_with_your_token
```

Then run the script:

```
$ ./milestone-patches.py 44
```

Where '44' is the milestone number, f.ex.
https://github.com/mesonbuild/meson/milestone/44

Downloads each patch into `./patches`, prefixed with a timestamp that should be
followed when applying the patches.

To aid in the developer workflow, when you've applied patches, move them to
`./patches/done` and they will be skipped when you run the script a second
time.
