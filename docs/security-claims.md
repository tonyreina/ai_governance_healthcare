# Security claims

<!-- rumdl-disable MD013 -->
<!-- Evidence references are single long tokens (a test path plus a test name) that cannot be wrapped. -->

Every security property this project asserts, where it asserts it, and what
backs it. The inventory exists because the same bug kept appearing: a sentence in
the docs or the UI claiming something no test checked, which turned out to be
false (#31, #55, #56, #61, #62).

`pixi run check-claims` reads this page and fails if any row is not true to
its own description. It runs in every commit and in CI.

- **Asserted in** is the file and the sentence, quoted. The quote must still be
  in that file, so when a doc changes, its row has to change with it.
- **Enforced by** names the tests that enforce the claim. Each must exist **and**
  be something CI runs, because a test nobody runs (#32) is decoration.
- **Status** is one of four values, and the honest ones matter most:
    - `enforced`: a test CI runs fails if the claim becomes false.
    - `partial`: tested, but not all of it. The gap and its issue are stated.
    - `unenforced`: true or plausible, with nothing that would notice if it
      stopped being true. The reason is stated.
    - `violated`: the sentence is **not true** today. It stays in the inventory,
      with its issue, rather than being quietly left in the docs.

A claim the code does not back is allowed to stay here, as `violated`, in plain
sight. What is not allowed is a claim that looks enforced and is not.

**Adding a claim.** Any new sentence in the docs or the UI that asserts a
security property gets a row in the same change, with the test that enforces
it. If there is no test, write the test, or soften the sentence, or list it
honestly as `unenforced`. See [CLAUDE.md](https://github.com/tonyreina/ai_governance_healthcare/blob/main/CLAUDE.md).

## The claims

### C-01 Client-supplied identity headers are stripped

- **Claim:** The proxy deletes any identity header a client sends and sets its
  own, so a client cannot choose who it is.
- **Asserted in:** `docs/self-hosting.md` — "The proxy deletes any
  `X-Auth-Request-User`, `-Name` or `-Email` the browser sent"
- **Asserted in:** `docs/running.md` — "**Identity cannot be forged.**"
- **Status:** enforced
- **Enforced by:**
  `tests/test_proxy_identity.py::a forged X-Auth-Request-* is refused`
  `tests/test_stack.py::forged identity headers are stripped`

### C-02 Every documented cloud identity configuration resolves an identity

- **Claim:** The IAP, ALB, Azure and oauth2-proxy settings each produce the
  canonical identity headers. (This was broken for months, #23.)
- **Asserted in:** `docs/self-hosting.md` — "behind an SSO front door: the
  header it sets"
- **Status:** enforced
- **Enforced by:**
  `tests/test_proxy_identity.py::request is forwarded`
  `tests/test_proxy_identity.py::no provider header reaches the API`

### C-03 A request with no identity is refused, and an unset source fails closed

- **Claim:** An empty or missing identity answers 401. It never falls back to a
  usable default.
- **Asserted in:** `proxy/Caddyfile` — "NO DEFAULT VALUE"
- **Status:** enforced
- **Enforced by:**
  `tests/test_proxy_identity.py::a request with no identity is refused`
  `tests/test_proxy_identity.py::an unset identity source fails closed`
  `server/tests/test_auth.py::test_missing_header_is_401_not_an_anonymous_user`

### C-04 The API reads identity from the proxy header and nowhere else

- **Claim:** Not from a body, a query parameter or a cookie. The audit log's
  author is overwritten with the proxy identity.
- **Asserted in:** `README.md` — "the API reads identity from the proxy and
  nowhere else"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_auth.py::test_identity_comes_from_the_configured_header`
  `server/tests/test_api.py::test_log_author_is_the_proxy_identity_not_the_body`

### C-05 The API is reachable only through the proxy

- **Claim:** The API publishes no host port, and nothing but the proxy shares
  the internet-facing network with it.
- **Asserted in:** `docs/self-hosting.md` — "the API publishes no host port"
- **Asserted in:** `README.md` — "so it must be unreachable except through the
  proxy."
- **Status:** enforced
- **Enforced by:**
  `tests/test_compose_isolation.py::publishing a port on the api is noticed`
  `tests/test_compose_isolation.py::a new service on the edge network is noticed`

### C-06 The database has no route off the host

- **Claim:** Postgres sits on an `internal: true` network and publishes no port.
- **Asserted in:** `docs/self-hosting.md` — "on an `internal: true` network with
  no route off the host at all"
- **Status:** enforced
- **Enforced by:**
  `tests/test_compose_isolation.py::an internal network made routable is noticed`
  `tests/test_compose_isolation.py::publishing a port on the database is noticed`

### C-07 The stack binds to loopback by default

- **Claim:** It speaks plain HTTP, so it is published on 127.0.0.1 unless the
  operator changes it.
- **Asserted in:** `README.md` — "The stack binds to loopback by default"
- **Status:** enforced
- **Enforced by:**
  `tests/test_compose_isolation.py::the proxy binding every interface is noticed`

### C-08 The development override cannot be picked up by accident

- **Claim:** It is a named file, never compose.override.yaml, which a bare
  `docker compose up` would load silently. It deliberately publishes
  the API.
- **Asserted in:** `docs/running.md` — "can never pick it up by accident"
- **Status:** enforced
- **Enforced by:**
  `tests/test_compose_isolation.py::a compose.override.yaml is noticed`

### C-09 `make check-isolation` asserts the isolation model

- **Claim:** The docs say the target asserts that the API is unreachable and
  that a forged identity is stripped.
- **Asserted in:** `docs/self-hosting.md` — "`make check-isolation` asserts all
  of this against a running stack."
- **Status:** enforced
- **Enforced by:**
  `tests/test_check_isolation.py::a published port on`
  `tests/test_check_isolation.py::a listening port is noticed`
  `tests/test_check_isolation.py::a proxy that forwards the header is noticed`
  `tests/test_check_isolation.py::with nothing running it exits non-zero, not 0`
  `tests/test_stack.py::check_isolation.py finds the isolation model intact`

### C-10 Access control is enforced on the server

- **Claim:** A reader cannot write, a writer cannot delete, and a stranger gets
  404, not 403, so existence is not confirmed.
- **Asserted in:** `docs/running.md` — "| Access control enforced | **No** |
  Partly | **Yes, server-side** |"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_access.py::TestEnforcement::test_reader_may_not_patch`
  `server/tests/test_access.py::TestEnforcement::test_writer_may_not_delete`
  `server/tests/test_access.py::TestEnforcement::test_stranger_gets_404_not_403`
  `server/tests/test_access.py::TestEnforcement::test_list_hides_projects_you_cannot_read`

### C-11 A writer cannot grant themselves ownership

- **Claim:** Only an owner may change who has access, and a project cannot be
  left with no owner.
- **Asserted in:** `server/app/access.py` — "Only an owner may change who has
  access"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_access.py::TestEnforcement::test_writer_may_not_grant_themselves_ownership`
  `server/tests/test_access.py::TestEnforcement::test_last_owner_cannot_be_removed`

### C-12 A checkpoint sign-off is attributed to the authenticated user

- **Claim:** `signedBy` and `signedAt` are written by the server from the proxy
  identity and its clock, whatever the client sends. (Violated until
  #31.)
- **Asserted in:** `docs/deploy.md` — "**A checkpoint sign-off means
  something.**"
- **Asserted in:** `docs/running.md` — "| Checkpoint sign-off means something |
  **No, self-asserted** | Yes | Yes |"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_signoff.py::TestTheForgeryFromTheIssue::test_a_writer_cannot_sign_off_as_the_cmo`
  `server/tests/test_signoff.py::TestWhoSignedAndWhen::test_a_new_decision_is_attributed_to_the_caller_not_the_claim`
  `tests/test_stack.py::the sign-off is attributed to the proxy identity, not the claim`

### C-13 In the Claude artifact mode, identity and sign-off hold

- **Claim:** The comparison table says the artifact mode has a signed-in
  identity and a meaningful sign-off.
- **Asserted in:** `docs/running.md` — "| Signed-in identity | **None** | Yes |
  Yes, from your SSO |"
- **Status:** unenforced
- **Gap:** Rests on the Claude artifact runtime, which is outside this
  repository and cannot be exercised from a test here.

### C-14 Cross-site writes are refused

- **Claim:** A state-changing request a different site initiated is rejected by
  `Sec-Fetch-Site`, so a signed-in user's browser cannot be driven
  from another page.
- **Asserted in:** `server/app/main.py` — "Cross-site writes are refused."
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_csrf.py::TestCrossSiteWrites::test_a_cross_site_delete_is_refused`
  `server/tests/test_csrf.py::TestCrossSiteWrites::test_every_write_method_is_covered`

### C-15 Security headers are on every response

- **Claim:** The Content-Security-Policy, HSTS, nosniff and frame denial apply
  to `/api` and the dashboard alike, and `Server` is removed.
- **Asserted in:** `proxy/Caddyfile` — "Security headers, at the SITE level so
  /api/* gets them too."
- **Status:** enforced
- **Enforced by:**
  `tests/test_proxy_identity.py::content-security-policy`
  `tests/test_proxy_identity.py::no Server header`
  `server/tests/test_api_hardening.py::test_api_responses_get_security_headers`

### C-16 Request bodies are bounded

- **Claim:** The edge and the API both refuse an oversize body, and the API does
  so without buffering it.
- **Asserted in:** `proxy/Caddyfile` — "A project document is a governance
  record: kilobytes."
- **Status:** enforced
- **Enforced by:**
  `tests/test_proxy_identity.py::Caddy cut the over-size body off at the cap`
  `server/tests/test_api_hardening.py::test_body_limit_rejects_large_payloads`
  `server/tests/test_api_hardening.py::TestBodyLimitDoesNotBuffer::test_an_oversize_chunked_body_is_rejected`

### C-17 Abuse is rate limited

- **Claim:** Requests are counted per identity over a sliding window. The limit
  is per replica.
- **Asserted in:** `server/app/main.py` — "Per-key request accounting over a
  moving window."
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_api_hardening.py::test_rate_limit_blocks_burst_requests`
  `server/tests/test_api_hardening.py::TestRateLimiterMemory::test_the_window_really_slides`

### C-18 The audit log is append-only

- **Claim:** No route changes or removes a log entry, and the database refuses
  any UPDATE except the redaction a purge performs, which it verifies
  by comparing the result with a function. Deleting a project removes
  its live log, and records that it did (C-45).
- **Asserted in:** `README.md` — "Audit log | Yes, append-only"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_api.py::test_the_database_itself_refuses_to_update_a_log_entry`
  `server/tests/test_api.py::test_there_is_no_route_to_change_or_remove_a_log_entry`
  `server/tests/test_api.py::test_log_timestamp_is_the_server_clock`
  `server/tests/test_disposal.py::TestTheDatabaseAllowsARedactionAndNothingElse::test_an_arbitrary_update_is_refused`
  `server/tests/test_disposal.py::TestTheDatabaseAllowsARedactionAndNothingElse::test_a_partial_redaction_is_refused`
  `server/tests/test_disposal.py::TestTheDatabaseAllowsARedactionAndNothingElse::test_changing_when_or_who_is_refused`

### C-19 Version history cannot be rewritten

- **Claim:** Every revision is kept, and the only permitted change to one is a
  purge.
- **Asserted in:** `docs/running.md` — "| Version snapshots | No | No | **Yes**
  |"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_versions.py::TestVersions::test_history_is_append_only`
  `server/tests/test_versions.py::TestPurge::test_history_cannot_be_rewritten_by_hand`

### C-20 History survives deletion and stays restricted

- **Claim:** Deleting a project does not erase its history, and deleting a
  restricted record does not widen access to it.
- **Asserted in:** `server/migrations/002_versions.sql` — "No foreign key to
  projects, deliberately."
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_versions.py::TestVersions::test_history_survives_deletion`
  `server/tests/test_versions.py::TestDeletedHistoryStaysRestricted::test_a_stranger_cannot_read_a_deleted_projects_history`

### C-21 Disposal leaves a tombstone, not a gap

- **Claim:** A purge empties a snapshot's content and keeps its revision,
  author, timestamp and original hash. Only an owner may purge.
- **Asserted in:** `server/migrations/003_version_access.sql` — "The purge below
  is deliberately NOT a delete."
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_versions.py::TestPurge::test_an_owner_can_purge_and_the_tombstone_survives`
  `server/tests/test_versions.py::TestPurge::test_a_writer_cannot_purge`

### C-22 Deleting a project does not erase its history, and the docs say so

- **Claim:** Deleting removes the live project and its live audit log. The
  version history is kept, and the guide says plainly that deletion
  is not erasure. (It used to say it deleted "a project and its log",
  which implied the opposite. #36)
- **Asserted in:** `docs/self-hosting.md` — "**Deleting a project does not erase
  its history.**"
- **Asserted in:** `docs/self-hosting.md` — "The server keeps its version
  history"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_versions.py::TestVersions::test_history_survives_deletion`
  `server/tests/test_disposal.py::TestDeletionLeavesATombstone::test_the_log_still_goes_with_the_project`

### C-23 Backups are encrypted, and a plaintext dump is refused

- **Claim:** `make backup` requires a passphrase and writes only an encrypted
  dump.
- **Asserted in:** `Makefile` — "BACKUP_PASSPHRASE is required"
- **Status:** enforced
- **Enforced by:**
  `tests/test_backup_crypto.py::make backup with no passphrase is refused`
  `tests/test_backup_crypto.py::a plaintext dump needs PLAINTEXT=1 and is refused without it`
  `tests/test_backup_crypto.py::the passphrase is in no process's argv while encrypting`
  `tests/test_backup_crypto.py::the dump is not plaintext`
  `tests/test_backup_crypto.py::a backup whose pg_dump fails exits non-zero`

### C-24 `make up` refuses to start on unsafe settings

- **Claim:** A placeholder or short database password, a literal identity source,
  and a non-loopback bind over plain HTTP are all refused, and `.env` is read the
  way compose reads it, so a blank value or a trailing comment cannot get past
  the gate.
- **Asserted in:** `README.md` — "refuses to start on unsafe settings"
- **Status:** enforced
- **Enforced by:**
  `tests/test_preflight.py::an empty password is refused`
  `tests/test_preflight.py::15 characters is refused`
  `tests/test_preflight.py::the message points at make dev for local use`
  `tests/test_preflight.py::0.0.0.0 over plain HTTP is refused`
  `tests/test_preflight.py::SITE_ADDRESS= (blank) is plain HTTP, so 0.0.0.0 is REFUSED`
  `tests/test_preflight.py::so a weak one with a long note is still refused`
  `tests/test_preflight.py::an unsafe .env exits 1`
  `tests/test_preflight.py::FORCE=1 skips the check and exits 0`

### C-25 Any database password works

- **Claim:** A password from `openssl rand -base64 32`, or one with any
  character in it, connects. (About half of them crashed the API
  before #72.)
- **Asserted in:** `.env.example` — "Any password works in POSTGRES_PASSWORD
  above"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_database_url.py::TestThePiecesBecomeAUrlThatSurvivesAnyPassword::test_every_awkward_password_round_trips`
  `server/tests/test_database_url.py::TestARealRoleWithAHostilePassword::test_it_connects_and_a_wrong_password_does_not`

### C-26 Browser-only mode says so, in a standing banner

- **Claim:** The app states in the layout that it is storing in one browser,
  with no access control or audit log, and names the risk.
- **Asserted in:** `README.md` — "The app says so in a standing banner when it
  is in this mode."
- **Status:** enforced
- **Enforced by:**
  `tests/test_boot_storage.py::static host -> standing warning is shown`
  `tests/test_boot_storage.py::static host -> warning names the risk`

### C-27 The app never silently falls back to browser storage

- **Claim:** If a server was expected and cannot be reached, or refuses the
  user, the app stops and says so.
- **Asserted in:** `README.md` — "never silently falls back"
- **Status:** enforced
- **Enforced by:**
  `tests/test_boot_storage.py::no store was created`
  `tests/test_boot_storage.py::nothing written to localStorage`

### C-28 After a save, the app says where the save went

- **Claim:** The server mode says the shared workspace and never the browser;
  only the browser-only mode may mention the browser. (Violated until
  #55.)
- **Asserted in:** `app/js/00-core/40-writes.js` — "What a save tells the user
  about where it went."
- **Status:** enforced
- **Enforced by:**
  `tests/test_boot_storage.py::server mode: a save says it went to the shared workspace`
  `tests/test_boot_storage.py::browser-only mode: a save says it stayed in this browser`
  `tests/test_boot_storage.py::only the browser-only mode may say 'browser'`

### C-29 Each storage mode is labeled distinctly

- **Claim:** The header names the mode, so a user can tell the audited server
  from the other modes.
- **Asserted in:** `app/js/00-core/30-state.js` — "and no two modes share one"
- **Status:** enforced
- **Enforced by:**
  `tests/test_boot_storage.py::artifact mode is not labeled like the self-hosted server`
  `tests/test_boot_storage.py::no two modes share a header label`
  `tests/test_boot_storage.py::every Mode has a header label`
  `tests/test_boot_storage.py::artifact mode says, in the layout, where the data lives`

### C-30 Live updates reach other users, and only those who may see the project

- **Claim:** A change arrives over the event stream without a refresh. The
  stream carries ids, not documents, and a stranger is not told a
  restricted project changed.
- **Asserted in:** `docs/running.md` — "Live updates between people"
- **Status:** enforced
- **Enforced by:**
  `tests/test_stack.py::external change arrives over SSE`
  `server/tests/test_events.py::test_a_stranger_does_not_see_a_restricted_project_change`
  `server/tests/test_events.py::test_the_stream_carries_ids_not_documents`

### C-31 The generated dashboard can never go stale

- **Claim:** A hook rebuilds docs/app/index.html on any change under app/ and
  fails the run if the file differs.
- **Asserted in:** `docs/self-hosting.md` — "so the generated file can never go
  stale"
- **Status:** enforced
- **Enforced by:**
  `.pre-commit-config.yaml::build-app`
  `.pre-commit-config.yaml::check-app`

### C-32 A test cannot be added and quietly left out of CI

- **Claim:** CI fails if a `test-*` task is not run, or a test file has no task.
- **Asserted in:** `docs/running.md` — "so a test cannot be added and quietly
  left out."
- **Status:** enforced
- **Enforced by:**
  `tests/test_workflows.py::every rule passes on .github/workflows/test.yml`
  `tests/test_workflows.py::a suite dropped from CI is noticed`

### C-33 In CI, a test that cannot run is a failure

- **Claim:** `REQUIRE_TESTS=1` turns a skip into a failure, because a skip exits
  0 and reads as a pass.
- **Asserted in:** `docs/running.md` — "to turn every skip into a failure; CI
  always does."
- **Status:** enforced
- **Enforced by:**
  `tests/test_workflows.py::REQUIRE_TESTS removed is noticed`
  `tests/test_workflows.py::REQUIRE_TESTS set to 0 is noticed`

### C-34 The walkthrough video says what it shows

- **Claim:** The page says it was recorded on the Docker stack and that the
  demonstration copy is browser-only.
- **Asserted in:** `docs/index.md` — "The video shows a **shared workspace**"
- **Status:** enforced
- **Enforced by:**
  `tests/test_docs_media.py::dropping the mode caveat is noticed`

### C-35 `PROXY_SHARED_SECRET` is a working control

- **Claim:** Set once in `.env`, the proxy sends the secret and the API refuses a
  request without it. It authenticates the proxy to the API, not a caller to the
  proxy.
- **Asserted in:** `docs/deploy.md` — "Set it once in `.env` and Compose gives
  the same value to both"
- **Status:** enforced
- **Enforced by:**
  `tests/test_proxy_identity.py::the proxy sends X-Proxy-Secret to the API`
  `tests/test_proxy_identity.py::a client-supplied X-Proxy-Secret is replaced, not forwarded`
  `tests/test_compose_isolation.py::PROXY_SHARED_SECRET missing from`
  `tests/test_stack.py::the API refuses a request that skipped the proxy's secret`
  `tests/test_stack.py::and accepts the same request carrying it`
  `server/tests/test_auth.py::test_shared_secret_blocks_a_request_that_skipped_the_proxy`

### C-36 The self-hosting identity example is the safe one

- **Claim:** The identity example the self-hosting guide shows uncommented is a
  placeholder, never a literal, and local development is sent to `make dev`.
- **Asserted in:** `docs/self-hosting.md` — "Never put a literal such as
  `dev@localhost` here."
- **Status:** enforced
- **Enforced by:**
  `tests/test_preflight.py::passes preflight`
  `tests/test_preflight.py::the scan found the examples it is meant to check`

### C-37 The AWS audience setting matches what the load balancer signs

- **Claim:** The task definition sets `IDENTITY_AUDIENCE` to the value the API
  compares against, and the API refuses to start on a listener ARN.
- **Asserted in:** `docs/deploy.md` — "loadbalancer/app/chai/a"
- **Status:** partial
- **Gap:** No test has a live ALB, so that it puts its load balancer ARN in
  `signer` rests on AWS's documented token format. #51 is fixed to that extent.
- **Enforced by:**
  `server/tests/test_auth.py::TestAlbAudienceIsTheLoadBalancerArn::test_every_arn_the_docs_show_for_the_audience_starts`
  `server/tests/test_auth.py::TestAlbAudienceIsTheLoadBalancerArn::test_a_listener_arn_is_refused_at_startup`
  `server/tests/test_auth.py::TestAlbAudienceIsTheLoadBalancerArn::test_the_load_balancer_arn_is_what_the_alb_signs`

### C-38 MFA is whatever the hospital already requires

- **Claim:** Authentication, including multi-factor, is enforced at the front
  door and not by this application.
- **Asserted in:** `docs/deploy.md` — "**MFA is whatever the hospital already
  requires**"
- **Status:** unenforced
- **Gap:** Rests on the hospital's identity provider and the cloud front door,
  which are outside this repository and cannot be exercised from a test
  here.

### C-39 Following 'Close the back door' makes the API unreachable except through SSO

- **Claim:** Each cloud section's back-door steps are, in the guide's words,
  "not hardening"; they are the deployment.
- **Asserted in:** `docs/deploy.md` — "They are the deployment."
- **Status:** unenforced
- **Gap:** Rests on each cloud's own network configuration. The guide's 'Proving
  the back door is closed' commands are for an operator to run per
  deployment; nothing here runs them.

### C-40 The API refuses identity headers from an unexpected peer

- **Claim:** With `TRUSTED_PROXY_CIDR` set, a request whose TCP peer is outside
  it is rejected, and `X-Forwarded-For` cannot satisfy the check.
- **Asserted in:** `docs/deploy.md` — "refuses identity headers arriving from
  anywhere else"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_auth.py::test_trusted_proxy_cidr_rejects_an_outside_peer`
  `server/tests/test_auth.py::test_x_forwarded_for_cannot_satisfy_the_peer_check`

### C-41 The data survives `docker compose down`

- **Claim:** Postgres writes to a named volume, which `down` leaves alone.
- **Asserted in:** `docs/self-hosting.md` — "containers and networks go; pgdata
  stays"
- **Status:** enforced
- **Enforced by:**
  `tests/test_compose_isolation.py::the database leaving its named volume is noticed`

### C-42 The database image is pinned to a major version

- **Claim:** Postgres does not migrate its on-disk format, so a floating tag
  could make a volume unreadable on an unrelated pull.
- **Asserted in:** `compose.yaml` — "Pinned to a major version, never :latest."
- **Status:** enforced
- **Enforced by:**
  `tests/test_compose_isolation.py::db image '{image}' is noticed`

### C-43 A purge destroys the content of the history and of the audit log

- **Claim:** Every revision's document is emptied and every audit-log entry is
  redacted, including its prose and any extra field the client added,
  so a value pasted in by mistake is gone from both tables. A client
  cannot exempt its own entry.
- **Asserted in:** `docs/self-hosting.md` — "A purge destroys the content of
  every revision **and of every audit-log entry**"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_disposal.py::TestAPurgeReachesTheAuditLog::test_the_value_is_gone_from_the_history_and_the_log`
  `server/tests/test_disposal.py::TestAPurgeReachesTheAuditLog::test_the_prose_is_redacted_not_just_the_structured_values`
  `server/tests/test_disposal.py::TestAPurgeReachesTheAuditLog::test_a_field_the_server_does_not_own_is_gone_too`
  `server/tests/test_disposal.py::TestAPurgeReachesTheAuditLog::test_a_client_cannot_exempt_its_own_entry_from_redaction`

### C-44 A purge leaves who, when and which field, and records itself

- **Claim:** What survives is the author, the time, the field's path and the
  fingerprint, so the history shows that something was written and
  later destroyed, not a gap. The server writes its own record of the
  purge into the log, and that record is never redacted.
- **Asserted in:** `docs/self-hosting.md` — "What stays is who changed what,
  when, which field, and the fingerprint"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_disposal.py::TestAPurgeReachesTheAuditLog::test_who_what_and_when_survive`
  `server/tests/test_disposal.py::TestAPurgeReachesTheAuditLog::test_the_purge_itself_is_recorded_in_the_log`
  `server/tests/test_disposal.py::TestAPurgeReachesTheAuditLog::test_the_record_of_a_purge_survives_the_next_purge`

### C-45 Deletion leaves a permanent tombstone

- **Claim:** A delete writes who deleted the project, when, and what its last
  revision hashed to, in an append-only table that holds no content
  and survives a purge. A refused or failed delete writes nothing.
- **Asserted in:** `docs/self-hosting.md` — "It writes a permanent tombstone to
  `project_deletion`: who deleted it, when,"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_disposal.py::TestDeletionLeavesATombstone::test_a_delete_records_who_when_and_what_it_hashed_to`
  `server/tests/test_disposal.py::TestDeletionLeavesATombstone::test_it_survives_a_purge_of_the_history`
  `server/tests/test_disposal.py::TestDeletionLeavesATombstone::test_it_cannot_be_changed_or_removed_by_hand`
  `server/tests/test_disposal.py::TestDeletionLeavesATombstone::test_a_refused_delete_writes_nothing`

### C-46 The delete dialog says what deleting does, and offers to destroy the history

- **Claim:** In the server mode the dialog says the version history is kept,
  offers destroying it as a separate unticked choice, does the
  destroy step first, and does not delete the project if that step
  fails. The modes with no history do not offer it.
- **Asserted in:** `app/js/20-app/50-exports.js` — "Its version history is
  kept."
- **Status:** enforced
- **Enforced by:**
  `tests/test_disposal_ui.py::it says the version history is KEPT`
  `tests/test_disposal_ui.py::history first, then the project, in that order`
  `tests/test_disposal_ui.py::the project is NOT deleted if its history could not be destroyed`

### C-47 Backups made before a purge still hold the data

- **Claim:** The guide states that a backup taken earlier keeps the destroyed
  content. `make restore` no longer brings it back unnoticed: it re-applies the
  live database's purges, and says so when it cannot (C-75).
- **Asserted in:** `docs/self-hosting.md` — "Backups made earlier still hold the data."
- **Status:** enforced
- **Enforced by:**
  `tests/test_purge_ledger.py::restoring a dump from before the purge brings the content back`
  `tests/test_purge_ledger.py::the mistaken content is gone again`

### C-48 A change cannot be merged to main unless CI passes

- **Claim:** `main` requires the `tests passed` check, pinned to GitHub Actions,
  with no administrator bypass, so a pending or red run blocks the merge.
- **Asserted in:** `docs/running.md` — "a pull request cannot be merged while it is pending or red"
- **Status:** unenforced
- **Gap:** A repository setting, not a file, so no test in the repository can
  detect it being switched off. It was verified by hand, by trying to merge a
  throwaway PR with the check pending and then red; both were refused. Re-check it
  with `gh api repos/OWNER/REPO/rules/branches/main`.

### C-49 The dashboard's multi-line fields do not feed the browser's spellchecker

- **Claim:** The free-text fields turn spellcheck and form history off, so what is
  typed into them is not sent to a cloud spellchecker by the dashboard's own
  markup.
- **Asserted in:** `docs/deploy.md` — "The dashboard turns spellcheck and form
  history off on its multi-line fields"
- **Status:** partial
- **Gap:** Single-line inputs (owners, metric names, dates) keep the browser's
  default, on purpose, and a browser or extension may ignore the attribute. The
  deployment guide therefore also tells operators to disable cloud-backed
  spellcheck by policy, which nothing here can enforce. #59
- **Enforced by:**
  `tests/test_text_fields.py::every editable textarea opts out of spellcheck and form history`
  `tests/test_text_fields.py::a field with the browser defaults is noticed`

### C-50 `make up` refuses a Google identity source without its prefix

- **Claim:** Google IAP's `accounts.google.com:` prefix must be stripped, and
  `make up` refuses a Google identity source that does not set it.
- **Asserted in:** `docs/self-hosting.md` — "`make up` refuses a Google source
  without it"
- **Status:** enforced
- **Enforced by:**
  `tests/test_preflight.py::a Google identity source with no strip prefix is refused`
  `tests/test_preflight.py::uncommenting the template's Google block, in place, passes preflight`
  `server/tests/test_auth.py::TestThePrefixIsStrippedOnEveryPath::test_the_same_person_gets_the_same_id_by_either_path`

### C-51 The proxy runs unprivileged, with a read-only filesystem and no extra capabilities

- **Claim:** The only internet-facing service runs as a non-root user, drops every
  capability but one, and cannot write its own filesystem, so a compromise starts
  with far less than root.
- **Asserted in:** `docs/self-hosting.md` — "it runs as an unprivileged user
  (uid 65532), drops every Linux"
- **Status:** enforced
- **Enforced by:**
  `tests/test_compose_isolation.py::the proxy running as root`
  `tests/test_compose_isolation.py::the cloud proxy image: dropping USER is noticed`
  `tests/test_stack.py::the proxy runs as an unprivileged user`
  `tests/test_stack.py::the proxy and the api have a read-only root filesystem`

### C-52 Denied access is logged

- **Claim:** A refused request on a project the caller has no right to leaves one
  `access.denied` line naming who, which project, what was needed and what they
  held, without the document's contents.
- **Asserted in:** `server/README.md` — "produces one `access.denied` security event"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_denial_log.py::test_a_stranger_reading_a_project_is_logged`
  `server/tests/test_denial_log.py::test_a_reader_trying_to_write_is_logged`
  `server/tests/test_denial_log.py::test_the_line_does_not_leak_the_document`
  `server/tests/test_denial_log.py::test_permitted_requests_log_no_denial`

### C-53 The API cannot disable the append-only triggers

- **Claim:** The API serves as a restricted database role that cannot disable a
  trigger, truncate a table, alter the schema or hold the owner's credential, so
  the audit log and history are append-only against the application and not only
  against its bugs.
- **Asserted in:** `docs/self-hosting.md` — "it **cannot** disable or drop a
  trigger, truncate, alter a table or create one"
- **Status:** partial
- **Gap:** A PostgreSQL superuser bypasses it, and the owner's password is still
  in `.env` on the host and in the `migrate` job. A deployment that does not set
  `APP_POSTGRES_PASSWORD` serves as the owner (reported on `/api/health`, logged,
  and failed by `make doctor`). The cloud job definitions have not been run against
  a real managed database. #48
- **Enforced by:**
  `server/tests/test_roles.py::test_it_is_refused_every_statement_that_removes_a_guarantee`
  `server/tests/test_roles.py::test_its_table_privileges_are_exactly_the_documented_ones`
  `server/tests/test_roles.py::test_every_table_has_a_decided_grant`
  `tests/test_compose_isolation.py::the api being given the owner's password`
  `tests/test_stack.py::using the credential the API holds, the triggers cannot be disabled`
  `tests/test_stack.py::the API container holds no owner credential`

### C-54 The name lookup answers only for people the caller can already see

- **Claim:** `GET /api/principals` is not a staff directory anyone can walk: it
  answers for the caller and for people named on a project the caller can read,
  and for no one else.
- **Asserted in:** `server/README.md` — "It answers **only for people the caller can
  already see**"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_principals.py::test_it_is_not_a_directory_anyone_can_enumerate`
  `server/tests/test_principals.py::test_the_lookup_resolves_people_on_a_project_you_can_read`
  `server/tests/test_principals.py::test_the_batch_is_bounded`

### C-55 Every use of emergency access is recorded in the project's own audit log

- **Claim:** An identity with emergency access holds owner rights on every project,
  and each use is recorded in that project's own audit log, which a purge never
  redacts, and as a warning an alert can match.
- **Asserted in:** `docs/deploy.md` — "every use is recorded where the
  project's owners will see it"
- **Status:** partial
- **Gap:** Reads of one project by one person are throttled to one entry per ten
  minutes (every read is still an `access.breakglass` security event), and a delete cannot
  leave a log entry because the log goes with the project; it is recorded by the
  warning and the tombstone. Nothing here tests that a deployment alerts on the
  warning. #42
- **Enforced by:**
  `server/tests/test_breakglass.py::test_every_use_on_a_project_is_recorded_in_its_own_log`
  `server/tests/test_breakglass.py::test_the_entry_survives_a_purge`
  `server/tests/test_breakglass.py::test_reads_are_throttled_but_writes_are_not`
  `server/tests/test_breakglass.py::test_without_configuration_nobody_has_emergency_access`
  `server/tests/test_breakglass.py::test_the_record_is_visible_to_the_projects_new_owners`

### C-56 An event stream cannot outlive a revoked session by more than its lifetime

- **Claim:** The API ends an event stream after `SSE_MAX_LIFETIME_SECONDS`, so the
  browser reconnects through the front door and is authenticated again; a revoked
  session loses its stream within that time.
- **Asserted in:** `docs/deploy.md` — "A revoked session therefore loses its stream
  within this many seconds."
- **Status:** partial
- **Gap:** Tested that the API closes the stream and that a reconnect with no identity
  is refused. Nothing here runs a real front door, so that a real IAP, ALB or Easy
  Auth refuses the reconnect after revocation rests on how those products work. #49
- **Enforced by:**
  `server/tests/test_session.py::test_a_stream_is_closed_by_the_server_after_its_lifetime`
  `server/tests/test_session.py::test_reconnecting_works_and_is_authenticated_again`
  `tests/test_session_ui.py::a stream that is closed for good is reported`

### C-57 The front doors' session settings are listed correctly

- **Claim:** The table in the deployment guide names where each front door's session
  lifetime and sign-out are configured.
- **Asserted in:** `docs/deploy.md` — "the IAP reauthentication policy on the
  protected resource (session duration)"
- **Status:** unenforced
- **Gap:** Nothing here starts an IAP, an ALB, an Easy Auth or an oauth2-proxy
  session, so these come from the providers' documentation and could be out of date.
  The page says so. #49

### C-58 Security events are named and the docs list exactly them

- **Claim:** Every security-relevant event has a stable name and fields, written as
  one JSON object tagged `"stream": "security"`, and the table in the deployment
  guide is the complete list.
- **Asserted in:** `docs/deploy.md` — "a test fails if this table and the code ever
  disagree"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_security_events.py::test_the_documented_events_are_exactly_the_ones_the_code_can_emit`
  `server/tests/test_security_events.py::test_every_line_is_one_json_object_with_a_stream`
  `server/tests/test_security_events.py::test_a_request_with_no_identity_is_a_named_event`
  `server/tests/test_security_events.py::test_a_hostile_actor_id_cannot_forge_a_second_line`
  `tests/test_stack.py::creates, deletes and purges are named security events`

### C-59 Security events are collected, retained and alerted on

- **Claim:** The deployment guide tells an operator how to collect, retain and alert on
  the security stream on each platform.
- **Asserted in:** `docs/deploy.md` — "Where it goes."
- **Status:** unenforced
- **Gap:** This repository emits the events and tests that it does. It collects,
  retains and alerts on nothing: the sink, the filters and the retention are the
  operator's, and the per-cloud settings come from the providers' documentation and
  have not been run. The guide says so. #38

### C-60 Every read of a record is recorded, and the trail cannot be edited

- **Claim:** A list, a version read, a log read and a stream attach are each recorded
  in the transaction of the read, in an append-only table that outlives the project,
  so a read that cannot be recorded is not served.
- **Asserted in:** `docs/deploy.md` — "A read that cannot be recorded is not served."
- **Status:** partial
- **Gap:** Exports are built in the browser and reported by a beacon a client can
  omit: they are a record of ordinary use, bounded by the recorded reads that fetched
  the data. The table is append-only against the application and the restricted role;
  a database owner can still disable its trigger, which is why the same facts are also
  security events. How long it is kept is undecided (#57). #33
- **Enforced by:**
  `server/tests/test_access_audit.py::test_each_read_route_records_what_it_returned`
  `server/tests/test_access_audit.py::test_a_read_that_fails_leaves_no_row`
  `server/tests/test_access_audit.py::test_the_trail_is_append_only`
  `server/tests/test_access_audit.py::test_the_trail_outlives_the_project`
  `server/tests/test_access_audit.py::test_the_check_constraint_and_the_enum_agree`
  `tests/test_export_beacon.py::the PDF export is reported`
  `tests/test_stack.py::each read was recorded in the real database`

### C-61 A backup can be verified by restoring it, and a restore asks first

- **Claim:** `make verify-backup` restores a dump into a throwaway PostgreSQL and
  fails unless the tables, rows and append-only triggers came back, and `make restore`
  asks for `YES` before overwriting the live database.
- **Asserted in:** `docs/self-hosting.md` — "`make verify-backup` restores the newest
  dump"
- **Status:** enforced
- **Enforced by:**
  `tests/test_verify_backup.py::a good encrypted dump verifies`
  `tests/test_verify_backup.py::a dump that restores without the append-only triggers fails`
  `tests/test_verify_backup.py::the wrong passphrase fails`
  `tests/test_verify_backup.py::a truncated dump fails`
  `tests/test_verify_backup.py::with no answer it aborts and touches nothing`

### C-62 The per-platform backup settings are listed correctly

- **Claim:** The deployment guide names the flags that set backup retention,
  point-in-time recovery, deletion protection and an off-account copy on each
  managed database.
- **Asserted in:** `docs/deploy.md` — "Two rules apply on every platform."
- **Status:** unenforced
- **Gap:** Nothing here creates a Cloud SQL, RDS or Azure database, so the flags come
  from the providers' documentation and could be out of date. The page says so and
  does not recommend a retention length. #52

### C-63 A production-shaped stack is not brought up without an encryption decision

- **Claim:** `make up` refuses a stack reachable beyond this machine, using its own
  database volume, until the operator confirms the disk is encrypted, and does not
  claim to be able to check it.
- **Asserted in:** `docs/self-hosting.md` — "`make up` refuses a stack that is
  reachable beyond this machine"
- **Status:** enforced
- **Enforced by:**
  `tests/test_preflight.py::a non-loopback bind with no confirmation is refused`
  `tests/test_preflight.py::STORAGE_ENCRYPTION_CONFIRMED=1 accepts it`
  `tests/test_preflight.py::loopback needs no confirmation: that is a laptop`
  `tests/test_doctor.py::when the host cannot be inspected it says it cannot tell, not that it is fine`

### C-64 The managed databases' encryption settings are described correctly

- **Claim:** Cloud SQL and Azure encrypt storage by default, and RDS only if
  `--storage-encrypted` is passed at creation.
- **Asserted in:** `docs/deploy.md` — "**off unless you pass `--storage-encrypted`
  when you create the instance**"
- **Status:** unenforced
- **Gap:** Nothing here creates a managed database, so these come from the providers'
  documentation. The page says so and tells the operator to confirm the setting on
  the instance they have. #47

### C-65 What runs is locked, pinned and watched

- **Claim:** The API's dependencies are installed from a hash-pinned lock, the base
  images and actions are pinned by digest or commit, Dependabot watches each
  ecosystem, and a scan fails on a fixable HIGH or CRITICAL finding in our images.
- **Asserted in:** `docs/deploy.md` — "What is running is what the repository says"
- **Status:** enforced
- **Enforced by:**
  `tests/test_supply_chain.py::every locked requirement is pinned and hashed`
  `tests/test_supply_chain.py::the API image's bases are pinned`
  `tests/test_supply_chain.py::the images compose pulls are pinned`
  `tests/test_supply_chain.py::dependabot covers pip, both Dockerfiles, compose and the actions`
  `tests/test_supply_chain.py::security.yml scans HIGH and CRITICAL, on a schedule`
  `tests/test_supply_chain.py::pip is not in the runtime image`

### C-66 The security policy promises no response times

- **Claim:** `SECURITY.md` commits to no response or fix times, so no one relying on
  it is told the project will meet one.
- **Asserted in:** `SECURITY.md` — "There are no
  response or fix times"
- **Status:** enforced
- **Enforced by:**
  `tests/test_supply_chain.py::SECURITY.md promises no response or fix times`

### C-67 Growth is reported and the disk alerts are documented

- **Claim:** `make doctor` reports how large the append-only tables are, and the
  deployment guide names the disk alert for each platform.
- **Asserted in:** `docs/deploy.md` — "Alert on the disk instead"
- **Status:** partial
- **Gap:** The report is tested; the per-platform alert metrics and flags are from the
  providers' documentation and nothing here creates a database or an alert. Nothing
  trims the tables: the retention periods are decided (R-54) but nothing applies
  them yet. #54
- **Enforced by:**
  `tests/test_doctor.py::the revision count and size are reported`
  `tests/test_doctor.py::the read trail's size is reported too, with why it grows`
  `tests/test_doctor.py::it says these tables never shrink by themselves`

### C-68 The deployment guide makes no legal claim about a region

- **Claim:** The deployment guide leaves the region to the reader and does not say
  that any region meets a legal requirement.
- **Asserted in:** `docs/deploy.md` — "This guide is not legal advice"
- **Status:** partial
- **Gap:** The test checks that the section exists, names no region as adequate or
  compliant, and that no command example names a region. It cannot tell whether
  the provider region names are current; they are marked unverified. #58
- **Enforced by:**
  `tests/test_deploy_residency.py::no command example names a concrete region`
  `tests/test_deploy_residency.py::the Data residency section is complete`

### C-69 A restore brings purged content back, and the docs say so

- **Claim:** A dump restored after a purge reinstates the purged content, so a
  purge for an erasure request is undone by an ordinary recovery unless it is
  re-applied.
- **Asserted in:** `docs/privacy.md` — "A restore brings purged content back"
- **Status:** enforced
- **Enforced by:**
  `tests/test_subject_access.py::a restore of a dump from before a purge brings the purged content back`

### C-70 Subject access finds every place an identifier is stored

- **Claim:** `make subject-access` reports every table and column that records who
  did something, and changes nothing.
- **Asserted in:** `docs/privacy.md` — "It changes nothing."
- **Status:** partial
- **Gap:** Columns named `*_by`, `by_id` or `actor` are checked against the query;
  an identifier stored under another name, or only inside new jsonb, is not. #57
- **Enforced by:**
  `tests/test_subject_access.py::every column that records who did something is searched`
  `tests/test_subject_access.py::it changed nothing`

### C-71 An export carries its own provenance

- **Claim:** Each export states which storage mode produced it, in the header's own
  words, and browser-only exports say sign-offs are self-asserted.
- **Asserted in:** `app/js/00-core/30-state.js` — "Sign-offs here are self-asserted"
- **Status:** enforced
- **Enforced by:**
  `tests/test_export_provenance.py::the HTML report states the mode`
  `tests/test_export_provenance.py::browser-only exports say sign-offs are self-asserted`
  `tests/test_export_provenance.py::the JSON export states the mode`

### C-72 The data scope is stated in every mode

- **Claim:** Every storage mode, the self-hosted server included, tells the user
  never to enter patient-identifiable information, and the docs say so first.
- **Asserted in:** `app/js/00-core/30-state.js` — "Governance metadata only: never enter patient-identifiable information."
- **Status:** partial
- **Gap:** A statement of policy. Nothing inspects what is typed into the
  free-text fields, so the tests prove the instruction is shown, not that it is
  followed. Detection is R-22, open. #34
- **Enforced by:**
  `tests/test_boot_storage.py::healthy API -> the data scope is stated in the layout`
  `tests/test_boot_storage.py::static host -> the warning states the same data scope`
  `tests/test_data_scope.py::the comparison table says Never in every mode`

### C-73 The PHI scan never repeats what it finds

- **Claim:** `make phi-scan` reports the project, field and revisions of a match,
  never the matched text, and a clean run does not say no patient information is
  present.
- **Asserted in:** `docs/self-hosting.md` — "never the matched text"
- **Status:** enforced
- **Enforced by:**
  `tests/test_phi_scan.py::the matched text is never printed`
  `tests/test_phi_scan.py::a clean run does not claim there is no patient information`

### C-74 The PHI scan reaches the history

- **Claim:** The scan reads every unpurged revision and unredacted audit entry, not
  only the live record, so a value edited out of the record is still found.
- **Asserted in:** `docs/self-hosting.md` — "every revision not yet purged"
- **Status:** partial
- **Gap:** It finds only the patterns it has. A name, a date or a free-form case
  description is not checked, by design (R-50). Earlier backups are not scanned.
  #66
- **Enforced by:**
  `tests/test_phi_scan.py::the history is scanned, and the revisions are named`
  `tests/test_phi_scan.py::the audit log is scanned`

### C-75 A restore puts purges back

- **Claim:** `make restore` re-applies every purge the live database holds after it
  restores an older dump, and says so when it cannot.
- **Asserted in:** `docs/privacy.md` — "`make restore` puts the purges back."
- **Status:** partial
- **Gap:** When the live database cannot be read, the purges come back only if
  someone rebuilds the ledger from the security log; purge events from before
  this change lack the fields and must be re-applied by hand. #116
- **Enforced by:**
  `tests/test_purge_ledger.py::the mistaken content is gone again`
  `tests/test_purge_ledger.py::work written after the restore is untouched`
  `tests/test_purge_ledger.py::capture, then the restore, then reapply`
