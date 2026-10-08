# Deploying with SSO on Google Cloud, AWS and Azure

This page describes how to run the dashboard and its API as a managed
container service on Google Cloud, AWS or Azure, with the sign-in handled
by the cloud's own front door rather than by the application.

The application does not authenticate anybody. It reads an identity
header that a reverse proxy puts on every request and uses it for
`GET /api/me`, for audit-log attribution, and for checkpoint sign-offs.
That is a deliberate choice, and it buys a lot: no password handling, no
session store, no OIDC client library, and SSO that matches whatever the
hospital already uses. It also has exactly one hard requirement.

!!! danger "The front door is the entire security model"

    An identity header is only as trustworthy as the guarantee that no
    request can reach the container without passing through the proxy
    that sets it. If anyone can open a TCP connection to the container
    directly, they can send `X-Goog-Authenticated-User-Email:
    cmo@hospital.org` and the API will believe them.

    Every section below has a **Close the back door** subsection. Those
    steps are not hardening. They are the deployment.

## What you are deploying

### The container

One image serving both the static dashboard and the API described in
[Self-hosting](self-hosting.md). It listens on a single port, speaks
plain HTTP (TLS is terminated at the front door), and expects:

| Variable | Purpose |
|---|---|
| `PORT` | Port to bind. Set by the platform on all three clouds. |
| `DATABASE_URL` | PostgreSQL connection string. |
| `IDENTITY_MODE` | `iap`, `alb` or `easyauth` — which header to read. |
| `IDENTITY_AUDIENCE` | Expected `aud` (GCP), listener ARN (AWS) or client ID (Azure). Read **only** when `IDENTITY_HEADER_FORMAT=jwt` — the API refuses to start otherwise. |

`GET /api/health` returns `{"status":"ok","version":"..."}` and must not
require authentication — every platform below health-checks it from
inside the load balancer, where no identity header exists.

### The database

All three clouds offer managed PostgreSQL, and all three should be
reached over a private network path with no public endpoint. The project
document is stored as a `jsonb` column; `PATCH` performs the recursive
merge described in [Self-hosting](self-hosting.md), in which objects
merge key by key at every level and arrays replace wholesale.

Rotate the database credential with the provider and update `DATABASE_URL`;
there is no `pgdata` volume here and no `db` service, so the
[rotation trap in the compose stack](self-hosting.md#rotating-the-database-password)
does not apply. Prefer the platform's identity-based connection — Cloud SQL IAM
auth, RDS IAM auth, Entra ID — over a password you have to rotate at all.

!!! note "Do not implement the merge with `jsonb` concatenation"

    PostgreSQL's `||` operator on `jsonb` merges only the top level, so
    `{"items":{"s4-2":{"status":"met"}}}` would discard every other key
    under `items`. Use `jsonb_set` recursively, a PL/pgSQL function, or
    read-modify-write inside a transaction.

### Streaming: `/api/events`

`GET /api/events` is a long-lived `text/event-stream` response. Three
things break it on managed platforms:

- **Response buffering.** Send `Cache-Control: no-cache` and
  `X-Accel-Buffering: no`, and flush after every event.
- **Timeouts.** Covered per cloud below. Send a comment heartbeat
  (`: ping\n\n`) every 15–30 seconds so idle timers never fire.
- **More than one replica.** An event written on replica A must reach a
  browser subscribed on replica B. Use PostgreSQL `LISTEN`/`NOTIFY` as
  the fan-out bus, or pin the service to a single replica until you do.

## The auth model: reverse-proxy header trust

Each cloud front door does the same three things: it intercepts the
request, it redirects the browser through the identity provider, and it
forwards the request to the container with the resulting identity in
HTTP headers. What differs is which headers, and whether they can be
cryptographically verified.

### Why there is no password login

This is the first question a security review asks, so the answer is
recorded here rather than left to be rediscovered.

There is no user table, no password hash, no registration form and no
token endpoint. Sign-in is the hospital's existing identity provider,
and the application only ever learns who you are from the proxy in
front of it.

That is a decision, not an omission. Adding local accounts — the
`OAuth2PasswordRequestForm` pattern from the FastAPI tutorial, or
anything like it — would mean taking on:

- a credential store, and the hashing and rotation policy that goes with it;
- lockout, complexity and reuse rules;
- multi-factor enrollment and recovery, which an organization handling
  patient data is expected to have;
- token issuance, expiry and revocation;
- an audit trail for credential events, separate from the one this tool
  already keeps for governance decisions.

Every one of those is a thing that can be got wrong, in a tool whose
current authentication surface is reading one header. None of them is
the problem this tool exists to solve.

What delegating to the identity provider buys is more specific than
"less code":

**Offboarding actually works.** A clinician who leaves is disabled once,
in the directory, and loses access here at the same moment they lose
access to everything else. With local accounts, this tool becomes one
more place somebody has to remember to revoke — and the one nobody
remembers, because it is used by a committee that meets monthly.

**MFA is whatever the hospital already requires**, enforced at the front
door, with no second enrollment for users to abandon halfway.

**Password policy is somebody else's job**, and that somebody has already
argued it out with the security office.

**A checkpoint sign-off means something.** The identity attached to it
was asserted by the organization's IdP, not chosen by whoever was at the
keyboard. That is the difference between an audit record and a text
field — see the note on `localStorage` mode in [Running it](running.md).

The API enforces this rather than trusting the browser: `signedBy` and
`signedAt` are written by the server from the proxy's identity and its own
clock, whatever a client sends. Changing a decision re-attributes it to whoever
changed it; clearing one clears its attribution; re-sending an unchanged gate is
a harmless no-op. The committee's own words (`by`, `date`, `rationale`) stay as
written. Two consequences worth knowing: a record imported from elsewhere is
attributed to whoever imports it, because they are the one asserting it here,
and with `REQUIRE_IDENTITY=false` nothing is attributed, which `/api/health`
reports rather than hides.

#### If you have no identity provider

Run one in front; do not move authentication into the application. Put
[oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/) or
[Keycloak](https://www.keycloak.org/) ahead of Caddy and point
`IDENTITY_*_SOURCE` at the headers it sets — the
`Self-hosted oauth2-proxy / Keycloak gatekeeper` block in `.env.example`.
The application is unchanged, and the credential handling stays in
software built for it.

#### A second lock between the proxy and the API

`PROXY_SHARED_SECRET` is a second lock between the proxy and the API, not a way
for a caller to sign in. Set it once in `.env` and Compose gives the same value
to both: the proxy sends it as `X-Proxy-Secret`, and the API answers 403 to any
request that arrives without it. Generate one with `openssl rand -hex 32`. It is
defense in depth beside closing the network, not a substitute for it.

#### If you need non-interactive access

Scripts, scheduled jobs and CI are not users and should not have user
passwords. Authenticate them at the proxy — a service account in the
cloud front door — and leave the browser path alone. The exporters under
`examples/` read exported JSON and need no API access at all.

### Plain headers versus signed assertions

Every front door sets a convenient plaintext header such as
`x-goog-authenticated-user-email` or `x-amzn-oidc-identity`. Two of the
three also set a **signed JWT assertion** alongside it.

!!! warning "Prefer the signed assertion — but know what this image does with it"

    The plain headers are indistinguishable from headers an attacker sets by
    hand. A signed assertion *can* be told apart, because it carries a
    signature checkable against the provider's public key.

    **This image does not perform that check.** It decodes the assertion to
    read its claims and, with `IDENTITY_HEADER_FORMAT=jwt`, compares the `aud`
    claim to `IDENTITY_AUDIENCE`. That catches a token minted for another
    service in the same account; it does not catch a forgery, because an
    unverified signature constrains nothing.

    So prefer the assertion — the audience check is worth having, and it is the
    header a future verifying implementation will use. But do not treat it as
    defense in depth today. Closing direct access to the container is the only
    control actually standing between an attacker and a forged identity.

Google's own documentation is blunt about this: "If an attacker bypasses
IAP, the attacker can forge the IAP unsigned identity headers." AWS is
equally direct: "you must verify the signature of `x-amzn-oidc-data`."

### What a verifying `/api/me` would do — not implemented in this image

!!! danger "This image does not verify signatures. Network isolation is the control."

    Read this before deciding whether the stack is safe enough for your
    environment, because the rest of this page assumes you have.

    `server/app/auth.py` **decodes** a signed assertion to read its claims. It
    does **not** verify the signature, the issuer or the expiry, and it cannot:
    no public key is ever fetched. A forged assertion presented to the
    container directly is accepted.

    That is the auth model this project chose — trust a header set by a front
    door, and make the front door the only way in. It is a legitimate choice,
    and it is why every section below spends more space on closing direct
    access than on anything else. But it means the network control is not
    defense in depth. **It is the whole defense.** If the container is
    reachable without passing the front door, identity is forgeable.

    `IDENTITY_AUDIENCE` does give you one real check: with
    `IDENTITY_HEADER_FORMAT=jwt` the `aud` claim is compared to the value you
    set, which catches a token minted for a *different* service in the same
    cloud account. It catches misconfiguration. It does not catch forgery.

The upgrade path, should you want real verification:

```text
1. Read the signed assertion header. If missing -> 401.
2. Verify the signature against the provider's public key.
3. Verify the audience/signer matches THIS service, not merely that
   the token is valid somewhere in the cloud provider's fleet.
4. Verify issuer and expiry.
5. Return {id, name, email} from the verified claims.
```

Step 3 is the one people skip. A signature check alone proves the token
came from the cloud provider — not that it was minted for your service.

!!! danger "Never read identity from the request body or a query string"

    The browser must have no way to influence who it is. Strip any
    inbound copy of the identity headers at the edge of your handler
    before routing, so a client-supplied `X-MS-CLIENT-PRINCIPAL-NAME`
    cannot shadow the one the platform set.

## Google Cloud: Cloud Run behind Identity-Aware Proxy

### Architecture

```text
Browser
  |  HTTPS
  v
Identity-Aware Proxy  <-- Google Workspace / Cloud Identity
  |  adds x-goog-iap-jwt-assertion
  v
Cloud Run service (--no-allow-unauthenticated, --iap)
  |  private IP, Direct VPC egress
  v
Cloud SQL for PostgreSQL (no public IP)
```

IAP can now be enabled directly on a Cloud Run service. This is the
current recommended shape: it protects the `run.app` endpoint itself,
so you do not have to provision an external Application Load Balancer,
a serverless NEG and a managed certificate just to get a front door.

!!! note "The load-balancer route still exists"

    If you need Cloud Armor, a custom domain with your own certificate,
    or path-based routing to several backends, put an external
    Application Load Balancer in front and enable IAP on the backend
    service instead. The audience format changes — see below.

### The headers IAP sets

| Header | Contents | Verifiable? |
|---|---|---|
| `x-goog-iap-jwt-assertion` | Signed JWT (ES256) with the user's identity | **Yes** |
| `x-goog-authenticated-user-email` | `accounts.google.com:user@example.org` | No |
| `x-goog-authenticated-user-id` | `accounts.google.com:1234567890` | No |

Note the namespace prefix on the plain headers: the value is *not* a
bare email address. Code that forgets to strip `accounts.google.com:`
will store a malformed identity in the audit log.

IAP also uses `X-Serverless-Authorization` to authenticate itself to
Cloud Run; Cloud Run strips that header's signature before your
container sees the request. Do not build anything on it.

### Verify the assertion

Validate `x-goog-iap-jwt-assertion` as an ES256 JWT:

- **Keys**: `https://www.gstatic.com/iap/verify/public_key-jwk`
  (JWK set) or `https://www.gstatic.com/iap/verify/public_key` (PEM).
- **Issuer**: `https://cloud.google.com/iap`
- **Audience**, and this is the part that pins the token to *your*
  service:

    | Enablement | `aud` |
    |---|---|
    | IAP directly on Cloud Run | `/projects/PROJECT_NUMBER/locations/REGION/services/SERVICE_NAME` |
    | IAP on a load-balancer backend service | `/projects/PROJECT_NUMBER/global/backendServices/SERVICE_ID` |

The identity you want is the `email` and `sub` claims of the verified
payload — use those, not the plain headers.

### Close the back door

On Cloud Run the enforcement is IAM, not network ACLs. Deploy with
`--no-allow-unauthenticated` so the service refuses any caller that
cannot present a Google-signed ID token with the `run.invoker`
permission, then grant that permission to the IAP service agent and to
nobody else:

```bash
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" \
  --format='value(projectNumber)')
IAP_SA="service-${PROJECT_NUMBER}@gcp-sa-iap.iam.gserviceaccount.com"

gcloud run services add-iam-policy-binding chai-api \
  --region=us-central1 \
  --member="serviceAccount:${IAP_SA}" \
  --role=roles/run.invoker
```

Then confirm nothing else holds it:

```bash
gcloud run services get-iam-policy chai-api --region=us-central1
```

!!! danger "`allUsers` with `roles/run.invoker` is the back door"

    If that policy lists `allUsers` or `allAuthenticatedUsers` as an
    invoker, the `run.app` URL answers requests that never touched IAP,
    and every identity header becomes a free-text field. The output
    above should contain exactly one invoker: the IAP service agent.

!!! danger "Do not lock down ingress on this path"

    Two commands get recommended constantly for Cloud Run, and **both break
    this architecture**:

    ```bash
    # WRONG on the IAP-direct path -- do not run these here.
    gcloud run services update chai-api --region=us-central1 \
      --ingress=internal-and-cloud-load-balancing
    gcloud run services update chai-api --region=us-central1 --no-default-url
    ```

    With IAP enabled directly on the service, the default `run.app` URL **is**
    the IAP front door. `--no-default-url` deletes it, and
    `--ingress=internal-and-cloud-load-balancing` rejects the IAP-fronted
    traffic that arrives over it. The service stops answering for everyone.

    On this path, ingress stays `all` and the default URL stays enabled. What
    protects the service is the IAM policy above — the only invoker is the IAP
    service agent — not an ingress setting.

    Those two commands are correct on the load-balancer path below, where the
    load balancer is the front door and the `run.app` URL is genuinely a
    bypass.

If you took the load-balancer route instead (Cloud Armor, custom
certificate, path-based routing), then the `run.app` URL *is* a bypass and
both locks apply:

```bash
# Only on the LOAD BALANCER path, where the LB is the front door.
gcloud run services update chai-api --region=us-central1 \
  --ingress=internal-and-cloud-load-balancing
gcloud run services update chai-api --region=us-central1 --no-default-url
```

### Managed PostgreSQL

Cloud SQL for PostgreSQL with **no public IP**, reached over private
services access. Attach it to the service and let Cloud Run manage the
connector:

```bash
gcloud sql instances create chai-db \
  --database-version=POSTGRES_16 \
  --region=us-central1 \
  --tier=db-custom-2-7680 \
  --no-assign-ip \
  --network="projects/${PROJECT_ID}/global/networks/default" \
  --enable-google-private-path
```

### Secrets

Secret Manager, mounted as environment variables, read by the runtime
service account — never baked into the image or passed as `--set-env-vars`.

A `DATABASE_URL` you write by hand must have its password percent-encoded:
a `/`, `@`, `:`, `?` or `#` in it ends the URL early and the API refuses to
start, with a message saying so. The stack's own `POSTGRES_PASSWORD` does not
have this problem, because the API builds the URL and does the encoding.

```bash
# percent-encode the password first:
python3 -c 'import sys, urllib.parse as u
print(u.quote(sys.argv[1], safe=""))' 'the-password'

printf '%s' "postgresql://chai:ENCODED@/chai?host=/cloudsql/${INSTANCE}" \
  | gcloud secrets create chai-database-url --data-file=-

gcloud secrets add-iam-policy-binding chai-database-url \
  --member="serviceAccount:chai-run@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role=roles/secretmanager.secretAccessor
```

### Step by step

```bash
PROJECT_ID=my-project
REGION=us-central1
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" \
  --format='value(projectNumber)')
IAP_SA="service-${PROJECT_NUMBER}@gcp-sa-iap.iam.gserviceaccount.com"
AUD="/projects/${PROJECT_NUMBER}/locations/${REGION}/services/chai-api"

gcloud services enable run.googleapis.com iap.googleapis.com \
  sqladmin.googleapis.com secretmanager.googleapis.com

# 1. Runtime identity with least privilege.
gcloud iam service-accounts create chai-run \
  --display-name="CHAI governance API"

# 2. Build and push.
gcloud builds submit --tag "${REGION}-docker.pkg.dev/${PROJECT_ID}/chai/api:v1"

# 3. Deploy with IAP on and anonymous invocation off.
gcloud run deploy chai-api \
  --region="$REGION" \
  --image="${REGION}-docker.pkg.dev/${PROJECT_ID}/chai/api:v1" \
  --service-account="chai-run@${PROJECT_ID}.iam.gserviceaccount.com" \
  --add-cloudsql-instances="${PROJECT_ID}:${REGION}:chai-db" \
  --set-secrets=DATABASE_URL=chai-database-url:latest \
  --set-env-vars="IDENTITY_MODE=iap" \
  --set-env-vars="IDENTITY_HEADER=x-goog-iap-jwt-assertion" \
  --set-env-vars="IDENTITY_HEADER_FORMAT=jwt" \
  --set-env-vars="IDENTITY_AUDIENCE=${AUD}" \
  --min-instances=1 \
  --max-instances=1 \
  --timeout=3600 \
  --no-allow-unauthenticated \
  --iap

# 4. Let IAP, and only IAP, invoke the service.
gcloud run services add-iam-policy-binding chai-api \
  --region="$REGION" \
  --member="serviceAccount:${IAP_SA}" \
  --role=roles/run.invoker

# 5. Decide who may sign in.
gcloud iap web add-iam-policy-binding \
  --resource-type=cloud-run \
  --region="$REGION" \
  --service=chai-api \
  --member="group:ai-governance@hospital.org" \
  --role=roles/iap.httpsResourceAccessor
```

!!! note "`--max-instances=1` is a placeholder, not a recommendation"

    It is there because `/api/events` has no cross-replica fan-out until
    you add `LISTEN`/`NOTIFY`. Raise it once you have. `--timeout=3600`
    sets the hard request limit to the Cloud Run maximum of 60 minutes;
    SSE clients must still reconnect when it expires, which the browser
    `EventSource` does on its own.

## AWS: ECS Fargate behind an Application Load Balancer

!!! warning "App Runner is closed to new customers"

    AWS has closed App Runner to new customers as of 30 April 2026.
    Existing customers may continue to use it, but no new features are
    planned, and App Runner cannot be registered as an ALB target
    anyway — which rules it out for header-trust auth. AWS points new
    workloads at **ECS Express Mode**, which provisions an ECS service
    on Fargate plus an Application Load Balancer from a single API call.
    Express Mode's load balancer is an ordinary ALB in your account, so
    everything below applies; you attach the authenticate rule to the
    listener it created.

### Architecture

```text
Browser
  |  HTTPS :443
  v
Application Load Balancer (public subnets)
  |  listener rule: authenticate-oidc -> Entra ID / Okta / Cognito
  |  adds x-amzn-oidc-data
  v
ECS Fargate tasks (private subnets, no public IP)
  |  security group allows :8080 only from the ALB's security group
  v
RDS for PostgreSQL (private subnets, not publicly accessible)
```

Use `authenticate-oidc` to point the ALB straight at the hospital IdP,
or `authenticate-cognito` if you want a Cognito user pool in between to
federate several IdPs or to add a group-to-role mapping. Both action
types require an **HTTPS** listener.

### The headers the ALB sets

| Header | Contents | Verifiable? |
|---|---|---|
| `x-amzn-oidc-data` | Signed JWT (ES256) of the user-info claims | **Yes** |
| `x-amzn-oidc-identity` | The `sub` claim, plaintext | No |
| `x-amzn-oidc-accesstoken` | The access token, plaintext | No |

AWS labels the latter two "legacy unsigned headers" kept for backward
compatibility, and states plainly that they "cannot be independently
verified by your application."

### Verify the assertion

```text
header: {"alg":"ES256",
         "kid":"<uuid>",
         "signer":"arn:aws:elasticloadbalancing:...:loadbalancer/app/...",
         "iss":"<idp issuer>",
         "client":"<client id>",
         "exp":<unix>}
payload: {"sub":"...","email":"...","name":"...", ...}
```

1. Read `kid` from the JWT header.
2. Fetch the key from
   `https://public-keys.auth.elb.<region>.amazonaws.com/<kid>`.
3. Verify the ES256 signature.
4. **Check `signer` equals your load balancer's ARN.**
5. Take `sub` and `email` from the verified payload.

!!! danger "Skipping the `signer` check is a known, named vulnerability"

    Any AWS customer in the region can create an ALB, point it at their
    own IdP, and obtain a token the regional public key validates. If
    your API accepts any well-signed `x-amzn-oidc-data` without
    comparing `signer` to your own ALB's ARN, an attacker mints their
    own identities. This was published as the "ALBeast" class of
    misconfiguration, and AWS's documentation now states the signer
    check as a requirement, not a suggestion.

Two decoding gotchas: the ALB's JWT segments are base64url **with**
padding characters, which strict decoders reject; and the key endpoint
returns a raw PEM, not a JWKS document.

### Close the back door

The ALB does not isolate anything by itself. Two controls do:

```bash
# 1. The tasks have no public IP and live in private subnets.
NETCFG="awsvpcConfiguration={subnets=[$PRIVATE_A,$PRIVATE_B],\
securityGroups=[$TASK_SG],assignPublicIp=DISABLED}"

aws ecs create-service \
  --cluster chai \
  --service-name chai-api \
  --task-definition chai-api:1 \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "$NETCFG" \
  --load-balancers \
    "targetGroupArn=$TG_ARN,containerName=api,containerPort=8080"

# 2. The task security group accepts :8080 from the ALB's security
#    group only -- reference the group ID, never a CIDR.
aws ec2 authorize-security-group-ingress \
  --group-id "$TASK_SG" \
  --protocol tcp --port 8080 \
  --source-group "$ALB_SG"
```

Referencing `$ALB_SG` rather than a CIDR is what AWS recommends, and it
survives the ALB changing IP addresses. Verify afterwards that the task
security group has no `0.0.0.0/0` rule and no rule sourced from the VPC
CIDR:

```bash
aws ec2 describe-security-groups --group-ids "$TASK_SG" \
  --query 'SecurityGroups[0].IpPermissions'
```

!!! danger "The authenticate action must be the listener default"

    A rule that authenticates `/` while the default action forwards
    everything else leaves `/api/*` wide open to anyone who reaches the
    ALB. Put `authenticate-oidc` on the **default action** of the HTTPS
    listener, ordered before the `forward`, and add exceptions only for
    paths that genuinely must be anonymous. Remember that anything
    inside the VPC can also reach an internal ALB directly.

### Managed PostgreSQL

```bash
aws rds create-db-instance \
  --db-instance-identifier chai-db \
  --engine postgres \
  --engine-version 16.4 \
  --db-instance-class db.t4g.medium \
  --allocated-storage 50 \
  --db-subnet-group-name chai-private \
  --vpc-security-group-ids "$DB_SG" \
  --no-publicly-accessible \
  --storage-encrypted \
  --manage-master-user-password
```

`--manage-master-user-password` has RDS create and rotate the password
in Secrets Manager, so no credential is ever typed on a command line.
Open `$DB_SG` on 5432 to `$TASK_SG` and to nothing else.

### Secrets

Secrets Manager, injected by the ECS agent through the task definition's
`secrets` block, so values never appear in the task definition JSON,
in `describe-task-definition` output, or in the container environment
dump of a crash report:

```json
"secrets": [
  {
    "name": "DATABASE_URL",
    "valueFrom":
      "arn:aws:secretsmanager:us-east-1:1234:secret:chai/db-url"
  }
]
```

### Identity on the task definition

!!! warning "Set `IDENTITY_MODE` explicitly, or the task reads the wrong header"

    The API's default preset is `proxy`, whose identity header is
    `X-Forwarded-Email` — a header an ALB neither sets nor strips. Leave
    `IDENTITY_MODE` unset and legitimate users get 401, while a request that
    *does* carry `X-Forwarded-Email` is one a client supplied by hand.

```json
"environment": [
  { "name": "IDENTITY_MODE", "value": "alb" },
  { "name": "IDENTITY_AUDIENCE",
    "value":
      "arn:aws:elasticloadbalancing:us-east-1:1234:listener/app/chai/a/b" },
  { "name": "TRUSTED_PROXY_CIDR", "value": "10.0.0.0/16" },
  { "name": "REQUIRE_IDENTITY", "value": "true" }
]
```

`alb` is the one preset whose format is already `jwt`, so it reads
`x-amzn-oidc-data` and compares the `aud` claim to `IDENTITY_AUDIENCE`.
Set `TRUSTED_PROXY_CIDR` to the VPC range the load balancer's ENIs sit in,
so the task refuses identity headers arriving from anywhere else.

The OIDC client secret used by the listener rule is a separate concern:
it is stored in the listener configuration itself, so restrict
`elasticloadbalancing:DescribeRules` in your IAM policies.

### Step by step

```bash
REGION=us-east-1

# 1. ALB in public subnets, with its own security group.
ALB_ARN=$(aws elbv2 create-load-balancer \
  --name chai-alb --type application --scheme internet-facing \
  --subnets "$PUBLIC_A" "$PUBLIC_B" --security-groups "$ALB_SG" \
  --query 'LoadBalancers[0].LoadBalancerArn' --output text)

# 2. IP target group -- awsvpc tasks register by ENI address.
TG_ARN=$(aws elbv2 create-target-group \
  --name chai-tg --protocol HTTP --port 8080 --vpc-id "$VPC_ID" \
  --target-type ip --health-check-path /api/health \
  --query 'TargetGroups[0].TargetGroupArn' --output text)

# 3. HTTPS listener whose DEFAULT action authenticates.
aws elbv2 create-listener \
  --load-balancer-arn "$ALB_ARN" \
  --protocol HTTPS --port 443 \
  --certificates "CertificateArn=$ACM_ARN" \
  --ssl-policy ELBSecurityPolicy-TLS13-1-2-2021-06 \
  --default-actions file://actions.json

# 4. Long-poll friendly idle timeout for /api/events.
aws elbv2 modify-load-balancer-attributes \
  --load-balancer-arn "$ALB_ARN" \
  --attributes Key=idle_timeout.timeout_seconds,Value=4000

# 5. Lock the tasks to the ALB.
aws ec2 authorize-security-group-ingress \
  --group-id "$TASK_SG" --protocol tcp --port 8080 \
  --source-group "$ALB_SG"
```

`actions.json`:

```json
[
  {
    "Type": "authenticate-oidc",
    "Order": 1,
    "AuthenticateOidcConfig": {
      "Issuer": "https://login.microsoftonline.com/<tenant-id>/v2.0",
      "AuthorizationEndpoint": "https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/authorize",
      "TokenEndpoint": "https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/token",
      "UserInfoEndpoint": "https://graph.microsoft.com/oidc/userinfo",
      "ClientId": "<client-id>",
      "ClientSecret": "<client-secret>",
      "Scope": "openid email profile",
      "SessionTimeout": 28800,
      "OnUnauthenticatedRequest": "authenticate"
    }
  },
  { "Type": "forward", "Order": 2, "TargetGroupArn": "<tg-arn>" }
]
```

Register `https://<alb-dns-or-cname>/oauth2/idpresponse` as the redirect
URI in the IdP — that path is fixed by the ALB.

!!! note "`OnUnauthenticatedRequest` and single-page apps"

    `authenticate` redirects the browser to the IdP, which is right for
    the initial page load but turns an expired-session `fetch()` into an
    opaque CORS failure. If you split rules by path, use `deny` for
    `/api/*` so the app receives a clean `401` and can reload the shell.

## Azure: Container Apps with Easy Auth and Entra ID

### Architecture

```text
Browser
  |  HTTPS
  v
Container Apps ingress
  |
  v
Easy Auth sidecar (one per replica)  <-- Microsoft Entra ID
  |  adds X-MS-CLIENT-PRINCIPAL
  v
Application container
  |  VNet-integrated
  v
Azure Database for PostgreSQL flexible server (private access)
```

Azure's model differs structurally from the other two. The front door is
not a separate network hop: the authentication middleware runs as a
sidecar container inside every replica, intercepting each request before
it reaches the application container. There is consequently no ingress
path that skips it — which is a real advantage, as long as you never
weaken the sidecar's own configuration.

App Service with Easy Auth behaves identically and uses the same
headers; Container Apps is the better fit here because the workload is a
plain container with no App Service runtime underneath.

### The headers Easy Auth injects

| Header | Contents | Verifiable? |
|---|---|---|
| `X-MS-CLIENT-PRINCIPAL` | Base64-encoded JSON of all claims | No |
| `X-MS-CLIENT-PRINCIPAL-ID` | Caller ID set by the IdP | No |
| `X-MS-CLIENT-PRINCIPAL-NAME` | Human-readable name, usually the UPN | No |
| `X-MS-CLIENT-PRINCIPAL-IDP` | Which provider authenticated the caller | No |
| `X-MS-TOKEN-AAD-ID-TOKEN` | The Entra ID token — requires the token store | **Yes** |
| `X-MS-TOKEN-AAD-ACCESS-TOKEN` | The Entra access token — requires the token store | Yes |

`X-MS-CLIENT-PRINCIPAL` decodes to:

```json
{
  "auth_typ": "aad",
  "claims": [ { "typ": "name", "val": "Dana Okafor" },
              { "typ": "preferred_username", "val": "dana@hospital.org" } ],
  "name_typ": "name",
  "role_typ": "roles"
}
```

Microsoft notes that "external requests aren't allowed to set these
headers, so they're present only if set by App Service" — the platform
strips inbound copies. That guarantee holds only for traffic that
actually traverses the platform ingress.

### Verify the assertion

!!! warning "Easy Auth's identity headers are not signed"

    Unlike IAP and the ALB, Azure gives you base64 JSON, not a JWT. To
    get a verifiable assertion you must **enable the token store** and
    validate `X-MS-TOKEN-AAD-ID-TOKEN` yourself:

    - **Keys**: `https://login.microsoftonline.com/<tenant-id>/discovery/v2.0/keys`
    - **Issuer**: `https://login.microsoftonline.com/<tenant-id>/v2.0`
    - **Audience**: your app registration's client ID — this is the
      check that pins the token to your service.

    If the token header is absent for your flow, the server-side
    fallback is to call the token-store endpoint `/.auth/me` on
    `localhost`, forwarding the inbound request's cookies, and read the
    claims from the JSON it returns. `/.auth/logout` ends the session,
    and `/.auth/login/aad` starts one.

### Close the back door

Because the sidecar is in-replica, the risk is not a network bypass but
a configuration that tells the sidecar to let requests through:

```bash
az containerapp auth update \
  --name chai-api --resource-group chai-rg \
  --enabled true \
  --unauthenticated-client-action Return401 \
  --redirect-provider AzureActiveDirectory \
  --require-https true \
  --token-store true \
  --blob-container-uri "https://chaistore.blob.core.windows.net/tokens"
```

!!! note "Two things about the token store flags"

    `--blob-container-identity` is omitted deliberately. The literal string
    `system` is not an accepted value: the flag takes the *resource ID* of a
    user-assigned managed identity, and leaving it empty is what selects the
    system-assigned identity. Passing `system` fails.

    Both blob flags are Preview, and the whole `containerapp` command group
    needs its extension: run `az extension add --name containerapp` first.

!!! danger "Three settings that reopen the door"

    - `--unauthenticated-client-action AllowAnonymous` passes
      unauthenticated traffic straight to your container with no
      identity headers at all. Use `Return401` for an API, or
      `RedirectToLoginPage` if the same origin also serves the app
      shell. Never `AllowAnonymous`.
    - `--excluded-paths` removes authentication from the paths listed.
      Keep it empty, or limited to `/api/health`.
    - `--require-https false` allows the session cookie over plaintext.
      Keep ingress `allowInsecure` off:
      `az containerapp ingress update -n chai-api -g chai-rg
      --allow-insecure false`.

For defense in depth, take the app off the public internet entirely and
front it with Application Gateway or Front Door:

```bash
# Internal-only environment: ingress reachable only from the VNet.
az containerapp env create \
  --name chai-env --resource-group chai-rg --location eastus \
  --infrastructure-subnet-resource-id "$INFRA_SUBNET_ID" \
  --internal-only true \
  --enable-workload-profiles true

# Or keep a workload-profiles environment public-facing but reachable
# only through a private endpoint.
az containerapp env update \
  --name chai-env --resource-group chai-rg \
  --public-network-access Disabled
```

Private endpoints require a workload-profiles environment and a subnet
of `/27` or larger, and enabling them means disabling public network
access — the two settings are mutually exclusive by design.

### Managed PostgreSQL

```bash
az postgres flexible-server create \
  --name chai-db --resource-group chai-rg --location eastus \
  --version 16 --tier GeneralPurpose --sku-name Standard_D2ds_v5 \
  --vnet chai-vnet --subnet db-subnet \
  --public-access None \
  --active-directory-auth Enabled --password-auth Disabled
```

`--public-access None` with `--vnet` gives the server a private IP and
no public endpoint. `--active-directory-auth Enabled` with
`--password-auth Disabled` lets the container app authenticate to
PostgreSQL with its managed identity, so there is no database password
to store at all.

### Secrets

Key Vault, referenced by the container app's secret collection and
resolved with a managed identity:

```bash
az containerapp secret set \
  --name chai-api --resource-group chai-rg \
  --secrets "db-url=keyvaultref:https://chai-kv.vault.azure.net/secrets/db-url,identityref:system"
```

The Entra client secret for Easy Auth is stored the same way and
referenced by name in the auth configuration.

### Step by step

```bash
RG=chai-rg
APP=chai-api
TENANT=$(az account show --query tenantId -o tsv)

# 1. App registration for the front door.
APP_ID=$(az ad app create \
  --display-name "CHAI governance" \
  --sign-in-audience AzureADMyOrg \
  --query appId -o tsv)

az ad app update --id "$APP_ID" --enable-id-token-issuance true

az ad app update --id "$APP_ID" --web-redirect-uris \
  "https://${APP}.<env>.eastus.azurecontainerapps.io/.auth/login/aad/callback"

SECRET=$(az ad app credential reset --id "$APP_ID" \
  --display-name easyauth --query password -o tsv)

az ad sp create --id "$APP_ID"

# 2. Deploy the container with ingress and a managed identity.
az containerapp create \
  --name "$APP" --resource-group "$RG" --environment chai-env \
  --image "chaiacr.azurecr.io/chai-api:v1" \
  --target-port 8080 --ingress external --transport auto \
  --system-assigned \
  --min-replicas 1 --max-replicas 1 \
  --env-vars IDENTITY_MODE=easyauth \
             IDENTITY_HEADER=X-MS-TOKEN-AAD-ID-TOKEN \
             IDENTITY_HEADER_FORMAT=jwt \
             "IDENTITY_AUDIENCE=$APP_ID" \
             "DATABASE_URL=secretref:db-url"

az containerapp ingress update -n "$APP" -g "$RG" --allow-insecure false

# 3. Wire Entra ID into Easy Auth.
az containerapp auth microsoft update \
  --name "$APP" --resource-group "$RG" \
  --client-id "$APP_ID" --client-secret "$SECRET" \
  --tenant-id "$TENANT" --yes

# 4. Require authentication and turn on the token store.
az containerapp auth update \
  --name "$APP" --resource-group "$RG" \
  --enabled true \
  --unauthenticated-client-action Return401 \
  --redirect-provider AzureActiveDirectory \
  --require-https true \
  --token-store true

# 5. Raise the ingress idle timeout for /api/events (environment-wide,
#    minimum 4 and maximum 30 minutes).
# `update` only edits premium ingress that is already enabled, and `add` is
# what enables it. `add` also requires a workload profile to run on, so
# create one first. This is a chargeable dedicated profile.
az containerapp env workload-profile add \
  --name chai-env --resource-group "$RG" \
  --workload-profile-name ingress-d4 --workload-profile-type D4 \
  --min-nodes 1 --max-nodes 1

az containerapp env premium-ingress add \
  --name chai-env --resource-group "$RG" \
  --workload-profile-name ingress-d4 \
  --request-idle-timeout 30
```

By default any user in the tenant can obtain a token for the
application. Restrict it to the governance group under **Enterprise
applications → Properties → Assignment required**, then assign the
group.

## Header reference

| | Google Cloud | AWS | Azure |
|---|---|---|---|
| Front door | Identity-Aware Proxy | ALB `authenticate-oidc` | Easy Auth sidecar |
| IdP | Workspace / Cloud Identity | Any OIDC IdP, or Cognito | Microsoft Entra ID |
| Signed assertion | `x-goog-iap-jwt-assertion` | `x-amzn-oidc-data` | `X-MS-TOKEN-AAD-ID-TOKEN` |
| Plain identity | `x-goog-authenticated-user-email` | `x-amzn-oidc-identity` | `X-MS-CLIENT-PRINCIPAL-NAME` |
| Signing key source | `www.gstatic.com/iap/verify/public_key-jwk` | `public-keys.auth.elb.<region>.amazonaws.com/<kid>` | Entra JWKS for the tenant |
| Pin-to-service check | `aud` = project/location/service | `signer` = ALB ARN | `aud` = client ID |
| Bypass control | `--no-allow-unauthenticated` + invoker IAM | Task SG sourced from ALB SG | `Return401` + private endpoint |
| Session endpoints | IAP-managed | `/oauth2/idpresponse` | `/.auth/login/aad`, `/.auth/me`, `/.auth/logout` |

## Proving the back door is closed

Do this once per environment, and again after any network change. From
a host that is *not* the front door — your laptop, or a VM in an
unrelated subnet — forge the header and confirm you are refused:

```bash
# Google Cloud: expect 403 from Cloud Run, not 200 from your app.
curl -i https://chai-api-abc123-uc.a.run.app/api/me \
  -H 'X-Goog-Authenticated-User-Email: accounts.google.com:ceo@hospital.org'

# AWS: from an EC2 instance in the VPC but outside the ALB's SG,
# expect a connection timeout, not a response.
curl -i --max-time 5 http://10.0.2.17:8080/api/me \
  -H 'x-amzn-oidc-identity: ceo@hospital.org'

# Azure: expect 401, and no identity echoed back.
curl -i https://chai-api.<env>.eastus.azurecontainerapps.io/api/me \
  -H 'X-MS-CLIENT-PRINCIPAL-NAME: ceo@hospital.org'
```

A `200` with `ceo@hospital.org` in the body means the deployment is
open, every audit-log entry is unreliable, and every checkpoint
sign-off is repudiable. Treat it as an incident, not a to-do.

!!! note "Add this to CI"

    The check is three `curl` calls and a string match. Run it on every
    deploy; a network change six months from now will not announce
    itself.
