# Portable bounded host input: design and plan

Scope: issue #25's stdin transport only. Preserve the explicit opt-in, five-second
read deadline, 8 MiB byte bound, EOF requirement, strict UTF-8/JSON parsing,
terminal/closed-input refusal and existing error schemas. Input remains data,
never execution authorization. No new dependency or Git/evidence portability claim.

## Strategy

Use a short-lived isolated Python child for the blocking binary read on every
platform. Invoke the running interpreter with `-I -S -c` and fixed reader code;
inherit only stdin, capture stdout and discard stderr. The child reads at most
`MAX_BYTES + 1`, writes those bytes and exits. It imports no project code, loads
no site hooks, and neither evaluates nor executes input. The parent enforces a
monotonic deadline using `communicate(timeout=...)`, kills and reaps the child
on failure (including interruption), then applies the existing byte check,
UTF-8 decode and strict JSON parser. Closing the writer is required even for a
complete JSON value. Captured output is bounded by the fixed child reader.

The child owns no descendants. A blocked read is terminated with the process,
so repeated library calls leave neither background readers nor orphan children.
Pipe draining through `communicate` avoids deadlock when output exceeds pipe
capacity. Interpreter startup consumes the same deadline; OS process creation
and termination are ordinary OS operations, not hard real-time guarantees.
One additional interpreter launch per explicit host-context read is the cost.
The caller must exclusively own stdin, as with the existing descriptor reader.

Alternatives: POSIX `select` fails for Windows pipes and high-numbered POSIX
fds. Daemon threads cannot safely cancel a blocked read and may consume later
input. Windows native polling adds ctypes/handle and text-mode management and
platform-specific concurrency assumptions. A fixed isolated child uses supported
stdlib process lifetime management and lets Linux exercise the Windows path.

## Implementation / verification

1. Add real subprocess tests in `tests/test_host_input_transport.py`: ordinary
   and high-fd pipes, unicode, exact/over byte bound, malformed UTF-8/JSON,
   empty/closed stdin, no/partial/complete input without EOF, and repeated timeout
   calls with later input. Keep current lifecycle/TTY and schema regressions.
   Run before implementation; high-fd POSIX acceptance must fail under `select`.
2. Replace only `cli.read_host_context_stdin` transport with the isolated bounded
   child, retaining decoding/parser/error behavior. Run the focused tests.
3. Add narrow Windows/macOS CI jobs for transport tests and installed entrypoint
   smoke tests (`--version`, `--help`, instructions/schema/Skill). Keep the full
   Linux matrix. Document that these smoke checks do not test the entire Git,
   cache or evidence stack on those operating systems.
4. Run `python -m unittest discover -v`, release/output checks and the standalone
   build/install checks. Store logs outside the checkout. Commit source, tests,
   docs and CI only. Controller owns independent review, hosted CI and publishing.

## Review focus

Check timeout cleanup with the writer still open; draining large stdout without
waiting for child exit first; exact-bound EOF; binary input without Windows text
translation; startup-hook exclusion; failure before any GitHub operation. Native
Windows/macOS results remain pending until CI runs; do not claim them locally.
