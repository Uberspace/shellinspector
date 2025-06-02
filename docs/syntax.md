# Syntax

First, prepare a spec file, e.g. `ssh_connection.ispec`:

```shell
% whoami
root
% pwd
/root
```

Then, run it:

```shell
$ shellinspector tests/ssh_connection.ispec
Testing 1 spec files, including examples:
PASS % whoami
PASS % pwd
```

You can also specify multiple files:

```shell
$ shellinspector tests/ssh_connection.ispec tests/other.ispec
Testing 2 spec files, including examples:

tests/ssh_connection.ispec
PASS % whoami
PASS % pwd

tests/other.ispec
PASS % echo something else

All spec files succeeded.
```

## Retry

If you pass multiple spec files and some of them fail, shellinspector will
create a `.si-retry` file. A subsequent run will only test the spec files that
are specified both as an argument and in the `.si-retry` file, allow you to
quickly iterate on failing tests without running all passing ones over and over.
The file is during each run.

It is recommended to add `.si-retry` to your `.gitignore` file.

## Config File

Shellinspector can be configured within a project using a file called
`shellinspector.yaml` somewhere up the directory tree relative to your `.ispec`
file. Only the first/nearest config file found will be considered. The search is
also stopped, if a `.git` directory is found, assuming this is the project root.

You can use all settings available in Frontmatter here.

```yaml
settings:
  timeout_seconds: 10
  include_dirs:
    - includes/
  fixture_dirs:
    - fixtures/
```

All given relative paths are relative to the `shellinspector.yaml` file itself.

## Frontmatter

Shellinspector can be configured in various ways outlined below. These config
values are set using an optional YAML section at the start of the file. This
takes precedence over the values provided in the config file. The `settings`
dict gets merged, all other values are overwritten completely.

```yaml
---
environment:
  A: B
---
% whoami
root
% pwd
/root
```

All given relative paths are relative to the directory of the current spec file.

## Test Syntax

All lines (except expected output) start with a prefix character (`P`), followed
by arguments (`command`). The following lines specify an expected output
(`expected out put ...`).

```shell
P command
expected
output
...
```

## HERE documents

HERE documents are also supported, allowing you to specify multi-line input to
commands. This can be used to create multi-line files, like so:

```shell
% cat >foo <<HERE
foo
bar
HERE
% cat foo
foo
bar
```

Please note that for usage within shellinspector the syntax needs to be exactly
has shown above - `<<HERE` at the very end and `HERE` as the deliminator.

## Fixtures

This setting can be used to define a set of commands that are run before and
after the actual test commands. The fixture is defined in two separate files,
e.g. `fixtures/user_create_pre.ispec` and `fixtures/user_create_post.ispec`.
You can then use the fixture like so, in `test.ispec`:

`_pre`:

```shell
% useradd testuser
```

`_post`:

```shell
% userdel testuser
```

```yaml
---
fixture: user_create
settings:
  fixture_dirs:
    - fixtures/
---
% test -d /home/testuser
```

The `_pre` fixture is run before the first command in `test.ispec`, the `_post`
fixture is run after the last command, even if something failed.

By default fixtures run at the start and end of a specfile. Sometimes setup and
teardown tasks are only required once for all spec files within a run. In that
case, you can use run-fixtures:

```yaml
---
fixture:
  name: user_create
  scope: run
settings:
  fixture_dirs:
    - fixtures/
---
% test -d /home/testuser
```

The `_pre` fixture is run before the first spec file is executed, the `_post`
fixture is run after the very last spec file, even if something failed. Since
SSH sessions are established and closed for each spec file independently,
changes to the shell environment by the fixture do not influence the tests. The
variable `SI_USER` is carried over anyway.

Not specifying a scope is equivalent to:

```yaml
fixture:
  name: ...
  scope: file
```

### Run commands

To plainly interact with the shell as the root user or from within an uberspace,
start the line with `$` (user) or `%` (root):

```shell
% whoami
root
$ whoami
someuser
```

#### Matching

The lines following the command line are compared to the stdout & stderr the
command prints out. There are multiple

##### Literal Match

Ensure the output of the command matches the specified exactly:

```shell
% head -n2 /etc/passwd
root:x:0:0:root:/root:/bin/bash
bin:x:1:1:bin:/bin:/usr/bin/nologin
```

Leading and trailing whitespace is always ignored, including one or multiple new
lines before or after the actual or expected output.

To test for dynamic values, you can get the value of shell variables using the
`{VAR}` syntax, like so:

```shell
$ whoami
{USER}
```

##### Regex Match

Interpret the specified output as a regex with `re.MULTILINE` and try to match
it:

```shell
%~ ls /home
.*testuser.*
%~ cat /etc/passwd
^testuser
$~ whoami
\Atestuser\Z
```

Keep in mind that `\A` and `\Z` (not `^` and `$`) are needed to match start and
end of the regex.

New lines are only preserved between lines, but not after the final one.
Otherwise this would never match, since `r"aaaa\n"` can't match `aaaa`.

```shell
$~ echo aaaab
aaaa
```

Like with literal matches, you can alo use `{VAR}` here. Keep in mind that this
conflicts with regex syntax like `[abc]{5}` to get 5 of either a, b, or c. So
take care to not name any env variables after numbers.

##### Ignore

To just discard and ignore the output, use `_`:

```shell
%_ ls /home
%
```

### Includes

If a set of command repeates over and over in different spec files, you can
extract it into a dedicated file to be used in different files. For example,
creating a user happens over and over. Put it into `create_user.ispec`.

```shell
% uberspace user create -u testuser
```

Then, include it into other files by using `<` and the path. The given path
is relative to the paths listed in the `include_dirs` key in the config file,
plus the directory of the current spec file, in that order.

```shell
< create_user.ispec
% ls /home
testuser
```

### Comments

Any lines starting with `#` are ignored:

```shell
# the next line will run the command `echo`:
$ echo a
a
# this line does nothing
# EOF
```

## Target user & machine

Use `[user@host]` to specify which user and host will be used for the
connection. `host` may be either `local` for the machine actually running
shellinspector or `remote` for the machine specified as `--target`:

```shell
# run on the local dev/ci machine
[@local]$ hostname
luto-portable
# run as a different user on uberspace8 VM
[usr1@remote]$ whoami
usr1
```

Since this is quite verbose, there are two shorcuts:

- Use just `% whoami` as a shorthand for `root@remote`.
- Use just `$ whoami` will connect to `remote` as the user specified in the
  `$SI_USER` envrionment variable of any open session.

```shell
% whoami
root
% hostname -f
remote.example.org
% export SI_USER=testor
$ whoami
testor
% hostname -f
remote.example.org
```

Using `$` without setting `$SI_USER` will cause an error.

## Sessions

You can connect to the test host more than once by adding `:session_name` to the
username. Here we connect twice, change into two different directories and then
check that the sessions are still separate:

```shell
[vagrant:session1@remote]$ cd photos
[vagrant:session2@remote]$ cd videos
[vagrant:session1@remote]$ pwd
/home/vagrant/photos
[vagrant:session2@remote]$ pwd
/home/vagrant/videos
```

## Logout

Use the `logout` command to terminate a session. If you use the same
user/session-name/host again, a new one will start automatically.

```shell
[@local]$ echo a
a
[@local]$ logout
[@local]$ echo b
b
```

## Return Codes

Exit codes of all commands are checked automatically. If the code is >0, the
command is considered a failure:

```shell
$ python -m test false.ispec
running false.ispec
FAIL $ test -d /etc/nonexistant
command failed (RC=1)
```

To ignore the check, hide the return code like so:

```shell
$ test -d /etc/nonexistant || true
```

## Environment

To set envrionment variables for this test run, add an `envrionment` key to the
frontmatter:

`test.ispec`:

```yaml
---
environment:
  DNS_SERVER: 1.1.1.1
---
$ echo $DNS_SERVER
1.1.1.1
```

## Parametrized tests

To run many similar tests, add an `examples` key to the frontmatter:

`test.ispec`:

```yaml
---
examples:
  - PY_EXE: python3.11
    PY_VERSION: 3.11
  - PY_EXE: python3.13
    PY_VERSION: 3.13
---
$~ {PY_EXE} --version
{PY_VERSION}
```

## Python code

Sometimes shellinspector checks are not enough, so you can also run python
snippets like so:

`test.ispec`:

```shell
[@local]! set_env("did_python_run", "it did")
[@local]$ echo $did_python_run
it did
```

`test.ispec.py`

```python
def set_env(context, key, value):
    context.env[key] = value
    return True
```

The extra argument `ctx` is of type `ShellinspectorContext`, you can use the
following attributes:

- `.applied_example`, `dict`, (readonly): current config, see "Parametrized tests".
- `.env`, `dict`, (read/write): shell environment variables.

Return `True` to let this command pass, return error message as non-empty str
to fail. Other values will error.

Note that even though `[@local]!` specifies a host and user, the python code is
always executed on the control machine. The host/user spec only determines which
session is used for `ctx.env`.

## Examples

```shell
# Create a user and check the default python version
< create_user.ispec
$~ python --version
^Python 3.10
$~ pip --version
^pip.*python 3.10
```
