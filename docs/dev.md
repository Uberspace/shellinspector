# Developer Docs

## Setup

1. [install hatch](https://hatch.pypa.io/latest/install/#pipx)
2. run `hatch build` to get things running
3. install pre-commit hooks: `hatch run pre-commit install --install-hooks`

## Running

Use `hatch run` to start shellinspector:

```
$ hatch run python -m shellinspector
usage: __main__.py [-h] [--target-host TARGET_HOST] spec_files [spec_files ...]
__main__.py: error: the following arguments are required: spec_files
```

## Tests

Testing is done using `pytest`. You can test using the python version you used
to install hatch using

```
$ hatch run default:cov
========== test session starts ==========
platform linux -- Python 3.10.10, pytest-7.2.2, pluggy-1.0.0
rootdir: /home/luto/uberspace/shellinspector
plugins: cov-4.0.0
collected 17 items

tests/test_parser.py ................. [100%]

========== 17 passed in 0.14s ==========
```

To get a coverage report in HTML add `--cov-report html` to the command and
check `htmlcov/index.html`.

## SSH-Server

Use `docker-compose` to start a local SSH server on port `2222` with root access
using the `tests/keys/id_ed25519` key.

```
$ docker-compose up -d
```

Then, use `--target` and `--identity` to run tests:

```
$ hatch run python -m shellinspector tests/e2e/*.ispec --target 127.0.0.1:2222 --identity tests/keys/id_ed25519
PASS % whoami
PASS [whoami@remote]% whoami
PASS [whoami@remote]% echo TEST > /root/testfile
PASS % echo a
(...)
```

## Releasing a new version

To release a version, first bump the version (`patch`, `minor`, `major`):

```
hatch version minor
```

Then share it with the world:

```
git add src/shellinspector/__about__.py
git commit -m "v$(hatch version)"
git tag "v$(hatch version)"
git push origin main "v$(hatch version)"
```

Adhere to [semver](https://semver.org/) to choose the new version number.
