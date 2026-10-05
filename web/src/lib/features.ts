import { useQuery } from "@tanstack/react-query";

import { api } from "./api";
import type { AIFeatures } from "./types";

const ALL_ON: AIFeatures = { nl_search: true, ai_describe: true, ai_improve: true, listing_qa: true };

/** AI features switched on by admins at runtime (FR-7.4). While loading, or if the AI service is down,
 *  features count as on: each one already degrades gracefully if its call fails. */
export function useAIFeatures(): AIFeatures {
  const { data } = useQuery({
    queryKey: ["ai-features"],
    queryFn: () => api<AIFeatures>("/ai/features"),
    staleTime: 60_000,
    retry: false,
  });
  return data ?? ALL_ON;
}
