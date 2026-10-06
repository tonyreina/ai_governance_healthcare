/* ============================================================
   Content hashing
   A short fingerprint of a project's contents, so a printed report
   can be tied to the exact record it came from, and so a later
   reader can tell whether anything moved.

   WHAT MD5 DOES AND DOES NOT DO. It answers "is this the same
   record?" perfectly well. It does NOT make the record tamper-
   evident: MD5 has been collision-broken since 2004, and anyone who
   can change the record can also compute a replacement hash. Treat
   it as a version fingerprint, not a seal.

   A SHA-256 is computed alongside for anyone who needs the stronger
   property. It is the one to quote if a hash will ever be offered as
   evidence that a record was not altered. Both travel with every
   export so the choice stays with the reader.

   CANONICALIZATION IS THE WHOLE PROBLEM. Two JSON documents with the
   same contents hash differently if their keys are in a different
   order, so the input is serialized with keys sorted at every depth.
   Volatile fields are excluded: a hash that changes when nothing
   substantive did is a hash nobody will trust. See CANON_SKIP.
   ============================================================ */

/* Excluded from the fingerprint, each for a reason:
     updatedAt/updatedBy  touched by every save, including a no-op
     cardUpdatedAt        same
     _state               the app's working copy, not the record
     contentHash          cannot hash a document containing its own hash */
const CANON_SKIP = new Set([
  "updatedAt", "updatedBy", "cardUpdatedAt", "_state", "contentHash", "generated",
]);

/* Deterministic JSON: keys sorted at every level, volatile fields
   dropped, undefined treated as absent. */
function canonicalize(value) {
  if (value === null || typeof value !== "object") return value;
  if (Array.isArray(value)) return value.map(canonicalize);
  const out = {};
  for (const key of Object.keys(value).sort()) {
    if (CANON_SKIP.has(key)) continue;
    const v = value[key];
    if (v !== undefined) out[key] = canonicalize(v);
  }
  return out;
}

const canonicalJSON = doc => JSON.stringify(canonicalize(doc));

/* MD5, implemented here because browsers do not provide it:
   crypto.subtle offers SHA family digests only, and deliberately so.
   Compact RFC 1321 implementation over a UTF-8 byte array. */
function md5(input) {
  const bytes = new TextEncoder().encode(input);
  const S = [7,12,17,22,7,12,17,22,7,12,17,22,7,12,17,22,
             5,9,14,20,5,9,14,20,5,9,14,20,5,9,14,20,
             4,11,16,23,4,11,16,23,4,11,16,23,4,11,16,23,
             6,10,15,21,6,10,15,21,6,10,15,21,6,10,15,21];
  const K = new Uint32Array(64);
  for (let i = 0; i < 64; i++) K[i] = Math.floor(Math.abs(Math.sin(i + 1)) * 4294967296);

  const bitLen = bytes.length * 8;
  const padded = new Uint8Array((((bytes.length + 8) >> 6) + 1) * 64);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  new DataView(padded.buffer).setUint32(padded.length - 8, bitLen >>> 0, true);
  new DataView(padded.buffer).setUint32(padded.length - 4, Math.floor(bitLen / 4294967296), true);

  let [a0, b0, c0, d0] = [0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476];
  const view = new DataView(padded.buffer);

  for (let chunk = 0; chunk < padded.length; chunk += 64) {
    const M = new Uint32Array(16);
    for (let i = 0; i < 16; i++) M[i] = view.getUint32(chunk + i * 4, true);
    let [A, B, C, D] = [a0, b0, c0, d0];
    for (let i = 0; i < 64; i++) {
      let F, g;
      if (i < 16) { F = (B & C) | (~B & D); g = i; }
      else if (i < 32) { F = (D & B) | (~D & C); g = (5 * i + 1) % 16; }
      else if (i < 48) { F = B ^ C ^ D; g = (3 * i + 5) % 16; }
      else { F = C ^ (B | ~D); g = (7 * i) % 16; }
      F = (F + A + K[i] + M[g]) >>> 0;
      A = D; D = C; C = B;
      B = (B + (((F << S[i]) | (F >>> (32 - S[i]))) >>> 0)) >>> 0;
    }
    a0 = (a0 + A) >>> 0; b0 = (b0 + B) >>> 0;
    c0 = (c0 + C) >>> 0; d0 = (d0 + D) >>> 0;
  }

  const hex = n => [0, 8, 16, 24].map(s => ((n >>> s) & 0xff).toString(16).padStart(2, "0")).join("");
  return hex(a0) + hex(b0) + hex(c0) + hex(d0);
}

async function sha256(input) {
  if (!(globalThis.crypto && crypto.subtle)) return "";   // file:// in some browsers
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(input));
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, "0")).join("");
}

/* The fingerprint of a project, synchronously for MD5. */
function contentHash(doc) {
  return md5(canonicalJSON(doc));
}

/* Both digests, for exports. Async because SHA-256 is. */
async function contentHashes(doc) {
  const canon = canonicalJSON(doc);
  return { md5: md5(canon), sha256: await sha256(canon), bytes: canon.length };
}

/* Short form for display. Enough to distinguish versions by eye,
   and labeled as a prefix so nobody quotes it as the whole digest. */
const shortHash = h => (h || "").slice(0, 10);
