# Self-hosting

All persistence goes through two small classes in `docs/app/index.html`,
`DbStore` and `LocalStore`, which implement one interface:

| Method | Purpose |
|---|---|
| `subscribeAll(cb)` | Stream the project list; returns an unsubscribe function |
| `create(id, data)` | Create a project |
| `update(id, patch)` | Deep-merge a patch into a project |
| `remove(id)` | Delete a project and its log |
| `log(id, entry)` | Append an audit-log entry |
| `subscribeLog(id, cb)` | Stream the most recent log entries for a project |

To back the tool with your own server — Firestore, Supabase, a FastAPI service,
or anything else — add a third class implementing those six methods and select
it at boot.

!!! warning "Sign-off needs real identity"

    `LocalStore` has no concept of a user, so checkpoint sign-offs it records
    are self-asserted. If sign-offs need to carry weight for audit, your backend
    must supply an authenticated identity, as the artifact database does.

## Deploying this site

The GitHub Actions workflow at `.github/workflows/pages.yml` builds the
documentation with [Zensical](https://zensical.org) and publishes it on every
push to `main`. The built site includes the dashboard at `/app/`.

Enable it once under **Settings → Pages → Build and deployment → Source: GitHub
Actions**.

To build locally:

```bash
pixi run docs-serve    # live preview at http://localhost:8000
pixi run docs-build    # writes ./site
```
