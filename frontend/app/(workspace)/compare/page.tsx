import { ComparePage } from "@/components/comparison";
import { readFilters } from "@/lib/format";

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const query = await searchParams;
  return <ComparePage filters={readFilters({ get: (key) => typeof query[key] === "string" ? query[key] : null })} />;
}
