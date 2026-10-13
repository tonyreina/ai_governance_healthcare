/* ============================================================
   Access control
   Three roles, held per project:

     owner   everything, including deleting, archiving, and
             changing who else has access
     writer  fill in the checklist, metrics, model card and
             checkpoint decisions
     reader  see the record, change nothing

   WHAT THIS IS AND IS NOT. Everything in this file is user
   interface. A browser decides what to SHOW; it cannot decide what
   a server will ACCEPT, because the person using it can edit it.
   Real enforcement lives in server/app/access.py, which checks the
   same rules against an identity the proxy supplies and the browser
   cannot choose. If you add a permission here, add it there too, or
   you have added a label rather than a control.

   IDENTITY IS A PRECONDITION. Roles mean nothing without a
   trustworthy answer to "who is this", and the browser-only mode has
   none: localStorage has no users. In that mode the roles are
   recorded but not enforced, and the tool says so rather than
   implying a protection it cannot provide.

   NO OWNER MEANS NO ACCESS (R-75). A project whose owner list is
   empty is refused to everyone, whatever its writer and reader
   lists say; only a break-glass identity the server is configured
   with can reach it, and all it can do is assign an owner. The
   browser never sees such a record, because the server will not send
   it. This file refuses it too rather than showing it open, so a
   change of rule on one side cannot quietly reopen it on the other.
   ============================================================ */
const ROLES = ["owner", "writer", "reader"];
const ROLE_LABEL = { owner: "Owner", writer: "Write access", reader: "Read-only" };
/* What the reader sees for a role, and the sentence that says which they hold. The
   English ROLE_LABEL above is kept for anything a record or an export stores. */
const ROLE_KEY = Object.freeze({ owner: "role.owner", writer: "role.writer", reader: "role.reader" });
const ROLE_YOU_KEY = Object.freeze({ owner: "access.you.owner", writer: "access.you.writer", reader: "access.you.reader" });
const roleLabel = r => t(ROLE_KEY[r]);

const blankAccess = () => ({ owners: [], writers: [], readers: [] });

function accessOf(p) {
  const a = (p || {}).access || {};
  return {
    owners: Array.isArray(a.owners) ? a.owners : [],
    writers: Array.isArray(a.writers) ? a.writers : [],
    readers: Array.isArray(a.readers) ? a.readers : [],
  };
}

/* A project with no owner. Refused to everyone, not open to everyone. */
const unclaimed = p => accessOf(p).owners.length === 0;

/* Whether roles can mean anything here at all. Without an identity
   there is nobody to check a list against. */
const identityKnown = () => !!ME.id;

/* The current user's role, or "" for no access. Order matters:
   the most powerful role a user holds is the one that applies. */
function roleOf(p, who) {
  const id = who || ME.id;
  const a = accessOf(p);
  if (!id) return "owner";  // no identity: nothing is enforced, see identityKnown()
  if (a.owners.includes(id)) return "owner";
  if (a.writers.includes(id)) return "writer";
  if (a.readers.includes(id)) return "reader";
  return "";
}

/* Permission predicates. Each takes the project, defaulting to the
   open one. A project with no owner grants nobody anything. */
function canRead(p) {
  const proj = p || S;
  if (!proj) return false;
  if (!identityKnown()) return true;
  return !!roleOf(proj);
}

function canWrite(p) {
  const proj = p || S;
  if (!proj) return false;
  if (!identityKnown()) return true;
  return ["owner", "writer"].includes(roleOf(proj));
}

/* Deleting, archiving and granting access are owner-only, as is
   anything else that changes who can do what. */
function canOwn(p) {
  const proj = p || S;
  if (!proj) return false;
  if (!identityKnown()) return true;
  return roleOf(proj) === "owner";
}

/* Grant or revoke. Returns a patch rather than applying one, so the
   caller decides how it reaches the store. A person holds at most
   one role: granting a new one removes the others. */
function accessPatch(p, id, role) {
  const a = accessOf(p);
  const next = {
    owners: a.owners.filter(x => x !== id),
    writers: a.writers.filter(x => x !== id),
    readers: a.readers.filter(x => x !== id),
  };
  if (role === "owner") next.owners.push(id);
  else if (role === "writer") next.writers.push(id);
  else if (role === "reader") next.readers.push(id);
  return next;
}

/* Refuse to remove the last owner. A project with no owner is refused
   to everyone, its own team included (R-75). */
function wouldOrphan(p, id, role) {
  const a = accessOf(p);
  return a.owners.length === 1 && a.owners[0] === id && role !== "owner";
}
