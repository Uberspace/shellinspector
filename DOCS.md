# Automated Testing

A small tool to send commands to a test host via SSH, which their output against
an expected one and report the status.

## Usage

First, prepare a spec file, e.g. `ssh_connection.spec`:

```
% whoami
root
% pwd
/root
```

Then, run it:

```
$ python -m test tests/ssh_connection.console
PASS % whoami
PASS % pwd
```

## Syntax

All lines (except expected output) start with a prefix character (`P`), followed
by arguments (`command`). The following lines specify an expected output
(`expected out put ...`).

```
P command
expected
output
...
```

### Run commands

To plainly interact with the shell as the root user or from within an uberspace,
start the line with `$` (user) or `%` (root):

```
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

```
% head -n2 /etc/passwd
root:x:0:0:root:/root:/bin/bash
bin:x:1:1:bin:/bin:/usr/bin/nologin
```

##### Regex Match

Interpret the specified output as a regex with `re.MULTILINE` and try to match
it:

```
%~ ls /home
.*testuser.*
%~ cat /etc/passwd
^testuser
$~ whoami
\Atestuser\Z
```

Keep in mind that `\A` and `\Z` (not `^` and `$`) are needed to match start and
end of the regex.

##### Ignore

To just discard and ignore the output, use `_`:

```
%_ ls /home
%
```

### Includes

If a set of command repeates over and over in different spec files, you can
extract it into a dedicated file to be used in different files. For example,
creating a user happens over and over. Put it into `create_user.speci`.

```
% uberspace user create -u testuser
```

Then, include it into other files by using `<` and the path. Note that the path
is always relative to the file that contains the include.

```
< create_user.speci
% ls /home
testuser
```

### Comments

Any lines starting with `#` are ignored:

```
# the next line will run the command `echo`:
$ echo a
a
# this line does nothing
# EOF
```

## Target user & machine

By default commands run inside the uberspace8 VM as the specified user (`%` for
root, `$` for the newest user). To override this, expand the lines to look like
a shell prompt:

```
# run on the local dev/ci machine
[@local]$ hostname
luto-portable
# run as a different user on uberspace8 VM
[usr1@remote]$ whoami
usr1
```

## Return Codes

Exit codes of all commands are checked automatically. If the code is >0, the
command is considered a failure:

```
$ python -m test false.spec
running false.spec
FAIL $ test -d /etc/nonexistant
command failed (RC=1)
```

To ignore the check, hide the return code like so:

```
$ test -d /etc/nonexistant || true
```

## Examples

```
# Create a user and check the default python version
< create_user.speci
$~ python --version
^Python 3.10
$~ pip --version
^pip.*python 3.10
```
