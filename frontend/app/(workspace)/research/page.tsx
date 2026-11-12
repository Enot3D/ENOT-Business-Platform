import { ResearchPage } from "@/components/research";

export default async function Page({ searchParams }: { searchParams: Promise<{ cursor?: string }> }) {
  const { cursor } = await searchParams;
  return <ResearchPage cursor={typeof cursor === "string" ? cursor : undefined} />;
}
