// A conflict counts as resolved when anyone in the org resolved one with the same description
// (detection ids such as "C1" repeat between detections, so the description is the identity).
export const findResolved = (shared, description) => Object.values(shared || {})
  .find((v) => v.description && v.description.trim().toLowerCase() === String(description).trim().toLowerCase()) || null;
