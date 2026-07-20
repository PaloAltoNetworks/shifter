import { Link } from "react-router-dom";

import { PageHeader } from "@/components/page-header";
import { Card, CardContent } from "@/components/ui/card";

import { ctfChallengesPath, ctfRangePath, ctfScoreboardPath, ctfTeamPath } from "./routes";

const TOPICS = [
  {
    title: "Solving challenges",
    body: "Open a challenge from the Challenges page, read its description and any hints, then submit the flag in the format shown. Unlocking a hint deducts its penalty from that challenge's score.",
    to: ctfChallengesPath(),
    linkLabel: "Go to challenges",
  },
  {
    title: "Your range",
    body: "Some challenges run against a dedicated range. Check the Range page for its status and connection details once it is ready.",
    to: ctfRangePath(),
    linkLabel: "Go to range",
  },
  {
    title: "Scoring and rank",
    body: "The Scoreboard shows live rankings for your event. When the organizer freezes the board near the end, a Frozen indicator appears.",
    to: ctfScoreboardPath(),
    linkLabel: "Go to scoreboard",
  },
  {
    title: "Teams",
    body: "In team events, your team and its members appear on the Team page. Solo events show an empty team state.",
    to: ctfTeamPath(),
    linkLabel: "Go to team",
  },
] as const;

export function HelpPage() {
  return (
    <>
      <PageHeader title="Help" description="How the CTF workspace works" />
      <div className="grid gap-4 sm:grid-cols-2">
        {TOPICS.map((topic) => (
          <Card key={topic.title}>
            <CardContent>
              <h2 className="text-sm font-semibold">{topic.title}</h2>
              <p className="mt-2 text-sm text-muted-foreground">{topic.body}</p>
              <Link className="mt-3 inline-block text-sm underline" to={topic.to}>
                {topic.linkLabel}
              </Link>
            </CardContent>
          </Card>
        ))}
      </div>
    </>
  );
}
