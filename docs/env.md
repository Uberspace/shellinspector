# Environment

Shell inspector provides in the shell environment:

- `SI_TARGET`: Hostname/IP address of the host we connect to using SSH, from `--target`.
- `SI_TARGET_SSH_USERNAME`: The USER part of `[USER@remote]$`, or `root` for `%` lines.
- `SI_TARGET_SSH_PORT`: Port for SSH connection of the host we connect to, from `--target`, or `22`.

These are the same regardless of the host the test is running on, e.g. for
`[@local]$` tests they also point to SSH.

## Example Usage

```
[@local]$ echo $SI_TARGET
something.uberspace.de
[@local]$ echo $SI_TARGET_SSH_PORT
22
[@local]$ echo $SI_TARGET_SSH_USERNAME
root
```
