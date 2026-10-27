// Mirrors backend/app/roles.py. What a role *allows* always comes from the server
// (SessionInfo.user.capabilities); this file only names things for people.

export type Role = "administrator" | "manager" | "technician" | "auditor";

export type Capability =
  | "manage_customers"
  | "edit_customers"
  | "delete_customers"
  | "manage_service_catalog"
  | "manage_agreements"
  | "import_data"
  | "administer"
  | "read_audit_log";

export const ROLES: { role: Role; name: string; description: string }[] = [
  {
    role: "administrator",
    name: "Administrator",
    description:
      "Everything: all customers, who's assigned to them, users, security, keys and settings.",
  },
  {
    role: "manager",
    name: "Manager",
    description:
      "Runs customers and what they pay for: adds customers, assigns technicians, and manages " +
      "the service catalog and agreements. Sees every customer. No admin panel, and no deleting " +
      "customers.",
  },
  {
    role: "technician",
    name: "Technician",
    description: "Works with the customers they're assigned to: reads and updates their records.",
  },
  {
    role: "auditor",
    name: "Auditor",
    description: "Reads the audit log and every customer's metadata.",
  },
];

export function roleName(role: Role): string {
  return ROLES.find((r) => r.role === role)?.name ?? role;
}
