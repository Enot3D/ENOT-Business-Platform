import { ProjectPage } from "@/components/research";

export default async function Page({ params, searchParams }: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ cursor?: string }>;
}) {
  const [{ id }, { cursor }] = await Promise.all([params, searchParams]);
  return <ProjectPage id={id} cursor={typeof cursor === "string" ? cursor : undefined} />;
}
