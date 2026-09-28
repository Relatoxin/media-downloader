# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's **Security advisories** for this repository. Do not open a public issue with credentials, cookies, private URLs, or a working exploit.

Include the affected version, reproduction steps using synthetic data, expected impact, and any suggested mitigation. You should receive an initial response within seven days.

## Supported version

Only the latest commit on the default branch is supported during the pre-release stage.

## Scope

Relevant reports include unintended non-loopback exposure, cross-origin access to the companion API, unsafe filename or path handling, leakage of request headers/cookies, and command execution through crafted media metadata. DRM bypass requests and failures caused only by unsupported third-party sites are out of scope.
