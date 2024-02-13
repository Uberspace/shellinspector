# Shell Inspector 🕵️‍️

Open a shell session locally or via SSH, execute commands, and test what comes
back.

[![asciicast](https://asciinema.org/a/IfzFtiTPjabw4etcMJmpcuH8f.svg)](https://asciinema.org/a/IfzFtiTPjabw4etcMJmpcuH8f)

First, prepare a spec file, e.g. `readme.ispec`:

```
[@local]$~ ping -c1 google.com
1 packets transmitted
[@local]$ whoami
shellinspector
```

Then, run it:

```
$ python -m shellinspector readme.ispec
running readme.console
PASS [@local]$~ ping -c1 google.com
FAIL [@local]$ whoami
expected:
    shellinspector
actual:
    luto
```

For more details have a look at [`docs/syntax.md`](docs/syntax.md).
