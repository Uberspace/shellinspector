# Shell Inspector 🕵️‍️

Open a shell session locally or via SSH, execute commands, and test what comes
back.

First, prepare a spec file, e.g. `readme.inspect`:

```
[@local]$~ ping -c1 google.com
1 packets transmitted
[@local]$ whoami
shellinspector
```

Then, run it:

```
$ python -m shellinspector readme.inspect
running readme.console
PASS [@local]$~ ping -c1 google.com
FAIL [@local]$ whoami
expected: 
    shellinspector
actual: 
    luto
```

[![asciicast](https://asciinema.org/a/m2ovzpbCvOJFfudUEDhvrD09R.svg)](https://asciinema.org/a/m2ovzpbCvOJFfudUEDhvrD09R)

For more details have a look at [`docs/syntax.md`](docs/syntax.md).
