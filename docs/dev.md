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

## Releasing a new version

To release a version, follow these steps:

```
export VERSION=0.2.0
hatch version "${VERSION}"
git add src/shellinspector/__about__.py
git commit -m "v${VERSION}"
git tag "v${VERSION}"
git push origin main "v${VERSION}"
```

Adhere to [semver](https://semver.org/) choose the new version number.
