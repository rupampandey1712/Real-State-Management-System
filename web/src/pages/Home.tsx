import { Link } from "react-router-dom";

import NLSearchBox from "../components/NLSearchBox";

const NEIGHBOURHOODS: Record<string, string[]> = {
  Pune: ["Kharadi", "Baner", "Hinjewadi", "Wakad", "Viman Nagar", "Kothrud"],
  Bengaluru: ["Koramangala", "Indiranagar", "Whitefield", "HSR Layout", "Hebbal"],
  Mumbai: ["Andheri West", "Powai", "Bandra West", "Thane West", "Goregaon East"],
};

export default function Home() {
  return (
    <div className="space-y-20 pb-10 pt-6 sm:pt-14">
      <section className="max-w-4xl space-y-8">
        <h1 className="text-title font-extrabold tracking-tight text-ink sm:text-display">
          Tell us about the home you want.
        </h1>
        <NLSearchBox large />
      </section>

      <section className="grid gap-10 border-t border-rule pt-10 lg:grid-cols-[1fr_1.1fr]">
        <div className="max-w-md space-y-3">
          <h2 className="text-2xl font-bold">Ask any listing a question</h2>
          <p className="text-slate">
            Every home has an assistant that answers from the listing and the documents the agent uploaded,
            like society rules or brochures. Each answer shows where it came from. If the listing doesn't say,
            it tells you so and lets you ask the agent.
          </p>
        </div>
        <figure className="rounded-lg border border-rule bg-paper p-6" aria-label="Example conversation">
          <p className="text-right font-semibold text-ink">Is covered parking included?</p>
          <p className="mt-3 border-l-2 border-haldi pl-4">
            Yes, one covered parking spot is included.
            <span className="ml-1 rounded bg-haldi-wash px-1.5 text-sm font-semibold text-ink">Listing: Covered parking</span>
          </p>
          <p className="mt-5 text-right font-semibold text-ink">Can I keep a dog?</p>
          <p className="mt-3 border-l-2 border-haldi pl-4">
            The society rules allow pets, as long as dogs are leashed in common areas.
            <span className="ml-1 rounded bg-haldi-wash px-1.5 text-sm font-semibold text-ink">Society rules, page 3</span>
          </p>
        </figure>
      </section>

      <section className="space-y-6 border-t border-rule pt-10">
        <h2 className="text-2xl font-bold">Or start from a neighbourhood</h2>
        <div className="grid gap-8 sm:grid-cols-3">
          {Object.entries(NEIGHBOURHOODS).map(([city, localities]) => (
            <div key={city}>
              <h3 className="mb-2 text-lg font-bold text-ink">{city}</h3>
              <ul className="space-y-1">
                {localities.map((locality) => (
                  <li key={locality}>
                    <Link to={`/search?city=${city}&locality=${encodeURIComponent(locality)}`} className="link text-lg font-normal">
                      {locality}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
