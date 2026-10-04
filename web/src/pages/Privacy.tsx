import { Link } from "react-router-dom";

/** DPDP Act 2023 notice: what we collect, why, who sees it, how long we keep it, and your rights.
 *  Plain-language summary written by engineering — Legal must review the wording before launch. */
export default function Privacy() {
  const section = "space-y-2 border-t border-rule pt-5";
  return (
    <article className="max-w-prose space-y-6">
      <h1 className="text-title font-extrabold tracking-tight">How we use your details</h1>
      <p className="text-lg text-slate">EstateAI follows India's Digital Personal Data Protection Act, 2023. Here is what that means in practice.</p>

      <section className={section}>
        <h2 className="text-xl font-bold">What we collect and why</h2>
        <ul className="list-disc space-y-1 pl-5">
          <li><strong>Your email</strong>, to sign you in. Nothing else is needed to browse or ask questions.</li>
          <li><strong>Name, email and phone in an enquiry</strong>, only when you tick the consent box, and only so that listing's agent can reply.</li>
          <li><strong>Agents' name, phone, agency and RERA agent number</strong>, to verify agents before they can list homes.</li>
          <li><strong>Saved homes and searches</strong>, so you can come back to them.</li>
        </ul>
      </section>

      <section className={section}>
        <h2 className="text-xl font-bold">AI features</h2>
        <p>Search, the listing assistant and the description writer use Google Gemini. We never send your name, email, phone or other contact details to it: emails, phone numbers and ID numbers are removed from what you type before it leaves our servers. AI answers come only from the listing and its documents, and can be incomplete — verify with the agent.</p>
      </section>

      <section className={section}>
        <h2 className="text-xl font-bold">How long we keep it</h2>
        <ul className="list-disc space-y-1 pl-5">
          <li>Enquiries: 2 years, then deleted.</li>
          <li>AI request logs (with contact details removed): 30 days.</li>
          <li>Deleted accounts: your details are erased at once and the account is purged within 30 days.</li>
        </ul>
      </section>

      <section className={section}>
        <h2 className="text-xl font-bold">Your rights</h2>
        <p>
          You can delete your account and data at any time from <Link to="/account" className="link">your account</Link>.
          That removes your saved homes and searches and the contact details in enquiries you sent. If you are an agent,
          your listings are archived. To correct your details, raise a concern, or report a data breach, write to the
          grievance officer at privacy@estateai.example (placeholder until launch).
        </p>
      </section>
    </article>
  );
}
