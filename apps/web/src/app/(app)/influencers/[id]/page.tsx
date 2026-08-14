import type { Metadata } from "next";

import { InfluencerDetailScreen } from "@/features/influencers/influencer-detail-screen";

export const metadata: Metadata = { title: "Influencer" };

export default async function InfluencerDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <InfluencerDetailScreen influencerId={id} />;
}
