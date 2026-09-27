import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import type { Favourite } from "../lib/types";

export function useFavourites() {
  const { user } = useAuth();
  return useQuery({
    queryKey: ["favourites"],
    queryFn: () => api<Favourite[]>("/me/favourites"),
    enabled: !!user,
  });
}

/** Save / unsave a listing. Signed-out visitors are sent to sign in. */
export default function FavouriteButton({ listingId, compact = false }: { listingId: string; compact?: boolean }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const { data: favourites } = useFavourites();
  const saved = favourites?.some((f) => f.listingId === listingId) ?? false;

  const toggle = useMutation({
    mutationFn: () => api(`/me/favourites/${listingId}`, { method: saved ? "DELETE" : "PUT" }),
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: ["favourites"] });
      const previous = queryClient.getQueryData<Favourite[]>(["favourites"]) ?? [];
      queryClient.setQueryData<Favourite[]>(["favourites"], saved
        ? previous.filter((f) => f.listingId !== listingId)
        : [{ listingId, createdAt: new Date().toISOString() }, ...previous]);
      return { previous };
    },
    onError: (_e, _v, ctx) => queryClient.setQueryData(["favourites"], ctx?.previous),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["favourites"] }),
  });

  const base = compact
    ? "rounded-md bg-paper/95 px-2.5 py-1 text-sm font-semibold shadow-[0_0_0_1px_var(--color-rule)]"
    : "btn-quiet";

  if (!user) {
    return <Link to="/login" className={base}>Save</Link>;
  }
  return (
    <button type="button" onClick={() => toggle.mutate()} aria-pressed={saved} className={`${base} ${saved ? "text-leaf" : "text-ink"}`}>
      {saved ? "Saved" : "Save"}
    </button>
  );
}
