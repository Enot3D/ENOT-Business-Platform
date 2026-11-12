import { NichePage } from "@/components/niche";
import { readFilters } from "@/lib/format";

export default async function Page({ params, searchParams }: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  const filters = readFilters({ get: (key) => typeof query[key] === "string" ? query[key] : null });
  return <NichePage id={id} datasetId={typeof query.dataset_id === "string" ? query.dataset_id : undefined} filters={filters} />;
}
