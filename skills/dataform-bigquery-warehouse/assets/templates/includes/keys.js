// Surrogate keys of this repository. The strategy is chosen once, here, for this system, and every
// model calls these helpers, so all generated `_sk` keys are computed the same way.
//
// Choose with the dataform-bigquery-warehouse skill (references/keys-and-sentinels.md, "Choosing a
// key strategy"). Changing the strategy later changes every key downstream: that's a breaking change
// for L3P targets and for anything that has stored keys.
//
//   md5_hex           STRING (32)  portable: Postgres, Python or any app can compute the same key
//   farm_fingerprint  INT64        BigQuery-native: smallest, fastest joins; best for BI import models
//   sha256_hex        STRING (64)  when a security policy requires SHA-2
const STRATEGY = "md5_hex";

const HASH = {
  md5_hex: (text) => `to_hex(md5(${text}))`,
  farm_fingerprint: (text) => `farm_fingerprint(${text})`,
  sha256_hex: (text) => `to_hex(sha256(${text}))`
};

if (!HASH[STRATEGY]) {
  throw new Error(`includes/keys.js: unknown STRATEGY "${STRATEGY}"`);
}

const hash = HASH[STRATEGY];

// Sentinel keys: "na" = not assigned (failed lookup, sentinel row), "nd" = no data (NULL source key).
// INT64 keys use the conventional Kimball values -1 and -2.
function unknown() {
  return STRATEGY === "farm_fingerprint" ? "-1" : hash("'na'");
}

function noData() {
  return STRATEGY === "farm_fingerprint" ? "-2" : hash("'nd'");
}

// Key of one source column, hashed once in L1. A NULL source key becomes the "no data" key.
function surrogate(column) {
  return `coalesce(${hash(`cast(${column} as string)`)}, ${noData()})`;
}

// Key of several columns: a composite business key, or a namespaced key such as
// composite("'entity_a'", "invoice.id"). Every part is coalesced and separated, so the key is
// never NULL and ('ab', 'c') never collides with ('a', 'bc').
function composite(...columns) {
  const parts = columns.map((column) => `coalesce(cast(${column} as string), 'na')`);
  return hash(`concat(${parts.join(", '|', ")})`);
}

// SQL type of the keys, for typed NULLs: cast(null as ${keys.type()})
function type() {
  return STRATEGY === "farm_fingerprint" ? "int64" : "string";
}

module.exports = {
  STRATEGY,
  unknown,
  noData,
  surrogate,
  composite,
  type
};
