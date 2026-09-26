/**
 * Model helpers for Person 2 Employer Foundation UI.
 */

export function validateSkillLevel(levelStr: string): { valid: boolean; value: number; error?: string } {
  const val = parseFloat(levelStr);
  if (isNaN(val)) {
    return { valid: false, value: 0, error: "Proficiency must be a valid number" };
  }
  if (val < 0 || val > 1) {
    return { valid: false, value: val, error: "Proficiency must be between 0.0 and 1.0" };
  }
  return { valid: true, value: val };
}

export function formatProficiencyPercent(level: number | null | undefined): string {
  if (level == null) return "N/A";
  return `${Math.round(level * 100)}%`;
}

export function formatEmploymentType(type: string | null | undefined): string {
  if (!type) return "Unspecified";
  return type
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ");
}

export function canManageMembers(role: string | null | undefined): boolean {
  return role === "owner";
}
