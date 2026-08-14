import type { Metadata } from "next";

import { InfluencerListScreen } from "@/features/influencers/influencer-list-screen";

export const metadata: Metadata = { title: "Influencers" };

export default function InfluencersPage() {
  return <InfluencerListScreen />;
}
