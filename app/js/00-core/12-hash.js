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
   evidence that a record was not altered. Both travel with the JSON
   export and with the HTML, PDF and Markdown reports, so the choice
   stays with the reader (#150).

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

/* SHA-256, implemented here for the same reason as MD5: the exports are built
   synchronously (the PDF prints exportHTML(), and a report is one string), and the
   browser's crypto.subtle is asynchronous, and absent on some file:// origins. The
   constants are derived, not typed: the first 32 bits of the fractional parts of the
   square roots (initial state) and cube roots (round constants) of the first primes,
   which is how FIPS 180-4 defines them. tests/test_fingerprint.py checks the digest
   against Python's hashlib on every padding boundary and on non-ASCII text. */
const SHA256_PRIMES = (() => {
  const out = [];
  for (let n = 2; out.length < 64; n++) {
    let prime = true;
    for (let d = 2; d * d <= n; d++) if (n % d === 0) { prime = false; break; }
    if (prime) out.push(n);
  }
  return out;
})();
const SHA256_H0 = SHA256_PRIMES.slice(0, 8).map(p => Math.floor((Math.sqrt(p) % 1) * 4294967296));
const SHA256_K = SHA256_PRIMES.map(p => Math.floor((Math.cbrt(p) % 1) * 4294967296));

function sha256(input) { return sha256Bytes(new TextEncoder().encode(input)); }

/* The same digest over raw bytes, for a file a person attaches as evidence. */
function sha256Bytes(bytes) {
  const bitLen = bytes.length * 8;
  const padded = new Uint8Array((((bytes.length + 8) >> 6) + 1) * 64);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const view = new DataView(padded.buffer);
  view.setUint32(padded.length - 8, Math.floor(bitLen / 4294967296));   // big-endian
  view.setUint32(padded.length - 4, bitLen >>> 0);

  const H = SHA256_H0.slice();
  const W = new Uint32Array(64);
  const rotr = (x, n) => (x >>> n) | (x << (32 - n));
  for (let chunk = 0; chunk < padded.length; chunk += 64) {
    for (let i = 0; i < 16; i++) W[i] = view.getUint32(chunk + i * 4);
    for (let i = 16; i < 64; i++) {
      const s0 = rotr(W[i - 15], 7) ^ rotr(W[i - 15], 18) ^ (W[i - 15] >>> 3);
      const s1 = rotr(W[i - 2], 17) ^ rotr(W[i - 2], 19) ^ (W[i - 2] >>> 10);
      W[i] = (W[i - 16] + s0 + W[i - 7] + s1) >>> 0;
    }
    let [a, b, c, d, e, f, g, h] = H;
    for (let i = 0; i < 64; i++) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const t1 = (h + S1 + ((e & f) ^ (~e & g)) + SHA256_K[i] + W[i]) >>> 0;
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const t2 = (S0 + ((a & b) ^ (a & c) ^ (b & c))) >>> 0;
      h = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0;
    }
    [a, b, c, d, e, f, g, h].forEach((v, i) => { H[i] = (H[i] + v) >>> 0; });
  }
  return H.map(x => x.toString(16).padStart(8, "0")).join("");
}

/* The fingerprint of a project, synchronously for MD5. */
function contentHash(doc) {
  return md5(canonicalJSON(doc));
}

/* Both digests, over the same canonical form, for exports. */
function contentHashes(doc) {
  const canon = canonicalJSON(doc);
  return { md5: md5(canon), sha256: sha256(canon) };
}

/* Short form for display. Enough to distinguish versions by eye,
   and labeled as a prefix so nobody quotes it as the whole digest. */
const shortHash = h => (h || "").slice(0, 10);
