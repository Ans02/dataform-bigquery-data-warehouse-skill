// Shared literals. Dataform exposes every file in includes/ as a global named after the file,
// so models read these as constants.<name>. Keep hardcoded ids here, each with the reason,
// instead of scattering literals across models.

// Test and training customers created in the ERP; never part of reporting.
const excluded_customer_cds = ["900001", "900002"];

module.exports = {
  excluded_customer_cds
};
