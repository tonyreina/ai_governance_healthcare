# Security policy

This project is a governance record for clinical AI, and its server holds the
audit trail that records who reviewed what. A vulnerability here matters, and we
would rather hear about it privately first.

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Use GitHub's private reporting: on the repository's **Security** tab, choose
**Report a vulnerability**. That opens a private advisory only the maintainer can
see. If you cannot use it, open an issue that says only that you have a security
report and would like a private channel, with no details, and the maintainer
will arrange one.

Please include what you found, how to reproduce it, and which version or commit.
A report from someone who tried it against their own deployment is welcome;
please do not test against anyone else's.

## What to expect: acknowledgment and remediation

This project has one developer, working on it as time allows. **There are no
response or fix times**, and none is promised: a report is read and handled as
soon as it can be.

Remediation is handled in order of severity. A **critical** report (remote,
unauthenticated, or one that breaks the audit trail) comes before anything else,
then high, medium and low.

When a fix is released, an advisory describes what was affected, which versions,
and what to do, and you are credited if you want to be.

If your organization needs a response commitment for a deployment it runs, that
has to come from whoever operates it for you, not from this project.

## What is in scope

The server (`server/`), the proxy configuration (`proxy/Caddyfile`), the Compose
stack, the dashboard (`app/`), and the scripts and documentation that tell an
operator how to deploy them safely. In particular: a way around the identity
boundary (forging who a request is from), reading or changing a record you have
no role on, rewriting or removing the audit log or version history, an injection
or cross-site flaw in the dashboard, and a secret leaking into a log, an image
or an export.

## What is not

- A deployment that does not follow the documented network isolation. The API
  trusts the identity the proxy asserts, which is only safe if nothing else can
  reach it; that is a documented requirement, not a flaw.
- Findings in third-party images or packages with no fix available, which we
  track but cannot fix.
- Denial of service by an authenticated, authorized user within the documented
  rate limits.
- The security of your identity provider, cloud, or host.

## How we watch for problems ourselves

Dependencies are locked with hashes and base images are pinned by digest, so
what runs is what was tested. Dependabot opens a pull request when either has an
update, and a scheduled scan checks our images for known vulnerabilities with a
fix available. See `docs/deploy.md`, "Updating", for how an operator picks up a
new base image.
