# Approved user-local tool setup

Tool downloads and installation are operator-managed. Honour existing approval
for this work; do not ask for the same approval again. Profiling skills remain
read-only by default and never install kernel drivers, change sysctls, or grant
capabilities automatically. Keep vendor binaries outside the skill repository
and offline collector kit.

## Intel VTune and PCM

Use the [official VTune download page](https://www.intel.com/content/www/us/en/developer/tools/oneapi/vtune-profiler-download.html).
Record the downloaded installer hash and inspect `sh installer.sh --help` before
execution. VTune 2026.4.0.23's Linux offline installer successfully accepted:

```bash
sh intel-vtune-offline.sh -a -s --eula accept \
  --intel-sw-improvement-program-consent decline \
  --install-dir "$HOME/.local/opt/intel"
```

Only use the license-acceptance option under the operator's download/setup
authorization. Use a fresh destination and check the exit status and installation
log. No root is needed for this user-local installation. GUI dependency warnings
do not prove CLI failure: the tested minimal Ubuntu VM lacks several GUI
libraries but `bin64/vtune --version` and collection help work. GUI use is untested.
Run `vtune -help collect hotspots` before choosing knobs; see
`references/intel.md` for the tested software-sampling invocation and its access
failure. Tool installation alone does not establish profiling readiness.

Intel PCM was obtained from Ubuntu's configured, signed package index using
`apt-get download pcm libsimdjson29`. Both packages were extracted with
`dpkg-deb -x` into a fresh private user directory; no package-manager installation
or maintainer scripts were run. For this build, invoke with a command-scoped
library path:

```bash
LD_LIBRARY_PATH="$HOME/.local/opt/pcm/usr/lib/x86_64-linux-gnu" \
  "$HOME/.local/opt/pcm/usr/sbin/pcm" --version
```

Package layouts and dependencies vary. Inspect the package metadata and installed
help before reproducing the setup. Do not export the private library path
session-wide, force unsupported counters, or run register-write utilities.

## AMD uProf

Start with the [official AMD download page](https://www.amd.com/en/developer/uprof.html)
and its EULA form. Retain the form's returned download URL; old archive paths
can redirect or return 404. Session cookies and the AMD referrer may be needed
for the normal download flow. Do not treat an HTML error response as an archive.
Verify the vendor-published checksum and record SHA-256, inspect archive paths,
and extract into a fresh private user-local directory. Use absolute executable
paths and inspect `AMDuProfCLI --help` before profiling. Do not run the archive's
driver/capability setup scripts as part of extraction.

Keep JDK and profiler paths explicit rather than changing the system Java
installation. Retain native results, metadata, and tool logs before removing a
user-local installation. See `references/offline-results.md` for evidence handoff.
