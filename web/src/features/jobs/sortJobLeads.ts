import type { JobLead, LeadMatch } from "../../shared/api/types";

export function sortJobLeadsForReview(
  leads: JobLead[],
  matches: LeadMatch[],
  preferredLocation: string,
): JobLead[] {
  const preferred = normalizeLocation(preferredLocation);
  const scores = new Map(matches.map((match) => [match.lead_id, match.score]));

  return leads
    .map((lead, index) => ({ lead, index }))
    .sort((left, right) => {
      const locationDifference = locationRank(left.lead.location, preferred)
        - locationRank(right.lead.location, preferred);
      if (locationDifference !== 0) return locationDifference;

      const scoreDifference = (scores.get(right.lead.id) ?? -1)
        - (scores.get(left.lead.id) ?? -1);
      return scoreDifference || left.index - right.index;
    })
    .map(({ lead }) => lead);
}

function locationRank(location: string | null, preferred: string) {
  if (!preferred) return 0;
  return normalizeLocation(location ?? "").includes(preferred) ? 0 : 1;
}

function normalizeLocation(value: string) {
  return value
    .toLocaleLowerCase("tr-TR")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replaceAll("ı", "i")
    .replace(/[^a-z0-9]/g, "");
}
