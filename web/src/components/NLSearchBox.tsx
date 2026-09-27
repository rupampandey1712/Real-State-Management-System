import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useNavigate } from "react-router-dom";

const EXAMPLES = [
  "A 2 BHK under 80 lakh in Pune, near a metro, on a quiet street",
  "Furnished 1 BHK to rent in Koramangala below 25k, and my dog comes too",
  "3 BHK in Powai around 2.5 crore with a pool and gym",
];

/** The search is a sentence. Large variant = home hero; compact = results page. */
export default function NLSearchBox({ initial = "", large = false }: { initial?: string; large?: boolean }) {
  const [query, setQuery] = useState(initial);
  const [example, setExample] = useState(0);
  const navigate = useNavigate();
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => setQuery(initial), [initial]);
  useEffect(() => {
    if (!large || query) return;
    const timer = setInterval(() => setExample((i) => (i + 1) % EXAMPLES.length), 4500);
    return () => clearInterval(timer);
  }, [large, query]);

  const go = () => {
    if (query.trim()) navigate(`/search?q=${encodeURIComponent(query.trim())}`);
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    go();
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      go();
    }
  };

  return (
    <form onSubmit={submit} role="search" className={large ? "space-y-5" : "flex items-stretch gap-3"}>
      <label htmlFor="nl-search" className="sr-only">Describe the home you want</label>
      <textarea
        id="nl-search"
        ref={ref}
        rows={large ? 2 : 1}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={onKeyDown}
        maxLength={300}
        placeholder={EXAMPLES[large ? example : 0]}
        className={
          large
            ? "w-full resize-none border-0 border-b-2 border-ink bg-transparent pb-3 [field-sizing:content] min-h-[7.5rem] sm:min-h-0 text-[1.75rem] font-semibold leading-tight text-ink placeholder:text-slate/45 focus:border-haldi focus:outline-none sm:text-[2.5rem]"
            : "field min-w-0 flex-1 resize-none text-lg"
        }
      />
      <div className={large ? "flex flex-wrap items-center gap-4" : "flex shrink-0"}>
        <button type="submit" className="btn-primary whitespace-nowrap">Find homes</button>
        {large && <p className="text-slate">Write it the way you'd say it: budget, BHK, neighbourhood, even the feel of the street.</p>}
      </div>
    </form>
  );
}
