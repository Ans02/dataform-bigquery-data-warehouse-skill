// SQL helpers shared by several models, exposed as the global `helpers`.

// Typed string array literal, safe for empty lists (an empty `in ()` would not compile).
// Usage: where coalesce(col, '') not in unnest(${helpers.stringArray(constants.some_list)})
function stringArray(values) {
  const items = values.map((v) => `'${String(v).replace(/\\/g, "\\\\").replace(/'/g, "\\'")}'`);
  return `array<string>[${items.join(", ")}]`;
}

module.exports = {
  stringArray
};
