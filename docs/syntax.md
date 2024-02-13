# Syntax

First, prepare a spec file, e.g. `ssh_connection.ispec`:

```
% whoami
root
% pwd
/root
```

Then, run it:

```
$ python -m test tests/ssh_connection.ispec
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

Note that there is always a final new line after the expected output, so this
will currently always fail:

```
$ echo -n a
a
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

New lines are only preserved between lines, but not after the final one.
Otherwise this would never match, since `r"aaaa\n"` can't match `aaaa`.

```
$~ echo aaaab
aaaa
```

##### Ignore

To just discard and ignore the output, use `_`:

```
%_ ls /home
%
```

### Includes

If a set of command repeates over and over in different spec files, you can
extract it into a dedicated file to be used in different files. For example,
creating a user happens over and over. Put it into `create_user.ispec`.

```
% uberspace user create -u testuser
```

Then, include it into other files by using `<` and the path. Note that the path
is always relative to the file that contains the include.

```
< create_user.ispec
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

## Sessions

You can connect to the test host more than once by adding `:session_name` to the
username. Here we connect twice, change into two different directories and then
check that the sessions are still separate:

```
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

```
[@local]$ echo a
a
[@local]$ logout
[@local]$ echo b
b
```

## Return Codes

Exit codes of all commands are checked automatically. If the code is >0, the
command is considered a failure:

```
$ python -m test false.ispec
running false.ispec
FAIL $ test -d /etc/nonexistant
command failed (RC=1)
```

To ignore the check, hide the return code like so:

```
$ test -d /etc/nonexistant || true
```

## Environment

To prepare the test envrionment, create a file called `test.ispec.env` next to
`test.ispec`:

`test.ispec`:

```
$ echo $DNS_SERVER
1.1.1.1
```

`test.ispec.env`:

```
# which DNS server to test
DNS_SERVER=1.1.1.1
```

## Parametrized tests

To run many similar tests, create a file called `test.ispec.examples` next to
`test.ispec`:

`test.ispec`:

```
$~ {PY_EXE} --version
{PY_VERSION}
```

`test.ispec.examples`

```
PY_EXE        PY_VERSION
python3.10    3.10
python3.11    3.11
```

## Examples

```
# Create a user and check the default python version
< create_user.ispec
$~ python --version
^Python 3.10
$~ pip --version
^pip.*python 3.10
```
